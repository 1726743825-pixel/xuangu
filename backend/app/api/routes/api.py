from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import os
import secrets
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.session import get_db
from ... import db
from ...data.market_data import latest_trading_date
from ...integrations.market_adapter import get_quote
from ...jobs import execute_quote_sync, execute_selection
from ...models import DailyQuote, SelectionResult as SelectionResultModel, Stock
from ...schemas import (
    APIResponse,
    HealthData,
    Quote,
    QuoteImportRequest,
    QuoteImportResult,
    RunSelectionAccepted,
    RunSelectionRequest,
    SelectionImportRequest,
    SelectionImportResult,
    SelectionPage,
    SelectionResult,
    StockDetail,
    StockPage,
    StockSummary,
)

router = APIRouter(prefix="/api", tags=["API"])


def _selection_schema(row: SelectionResultModel) -> SelectionResult:
    signals = row.signals or {}
    return SelectionResult(
        code=row.stock_code,
        name=row.stock.name,
        trade_date=row.trade_date.isoformat(),
        price=signals.get("price"),
        change_pct=signals.get("change_pct"),
        score=row.score,
        strategy_name=row.strategy_name,
        industry=row.stock.industry,
        reasons=signals.get("reasons", []),
        indicators=signals.get("indicators", {}),
    )


@router.get("/health", response_model=APIResponse[HealthData])
def health() -> APIResponse[HealthData]:
    return APIResponse(data=HealthData(status="ok", service="xuangu-api"))


@router.get("/stocks", response_model=APIResponse[StockPage])
def list_stocks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    industry: str | None = Query(None, min_length=1, max_length=128),
    session: Session = Depends(get_db),
) -> APIResponse[StockPage]:
    filters = [Stock.industry == industry] if industry else []
    total = session.scalar(select(func.count()).select_from(Stock).where(*filters)) or 0
    rows = session.scalars(
        select(Stock).where(*filters).order_by(Stock.code).offset((page - 1) * size).limit(size)
    ).all()
    return APIResponse(data=StockPage(
        items=[StockSummary.model_validate(row) for row in rows], page=page, size=size, total=total
    ))


@router.get("/selections", response_model=APIResponse[SelectionPage])
def list_selections(
    trade_date: date | None = Query(None, alias="date"),
    strategy: str | None = Query(None, min_length=1, max_length=128),
    session: Session = Depends(get_db),
) -> APIResponse[SelectionPage]:
    target = trade_date or date.today()
    statement = select(SelectionResultModel).join(Stock).where(SelectionResultModel.trade_date == target)
    if strategy:
        statement = statement.where(SelectionResultModel.strategy_name == strategy)
    rows = session.scalars(statement.order_by(SelectionResultModel.score.desc())).unique().all()
    return APIResponse(data=SelectionPage(
        date=target, strategy=strategy, items=[_selection_schema(row) for row in rows], count=len(rows)
    ))


def _run_selection_in_background(trade_date: date) -> None:
    execute_selection(trade_date.isoformat())


def _sync_quotes_in_background(trade_date: date) -> None:
    execute_quote_sync(trade_date.isoformat())


def _require_job_token(x_job_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("JOB_API_TOKEN", "").strip()
    if expected and (not x_job_token or not secrets.compare_digest(x_job_token, expected)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="定时任务令牌无效")


@router.post("/selections/run", response_model=APIResponse[RunSelectionAccepted], status_code=status.HTTP_202_ACCEPTED)
def run_selection(
    background_tasks: BackgroundTasks,
    request: RunSelectionRequest | None = Body(default=None),
    _: None = Depends(_require_job_token),
) -> APIResponse[RunSelectionAccepted]:
    target = request.trade_date if request and request.trade_date else date.today()
    background_tasks.add_task(_run_selection_in_background, target)
    return APIResponse(data=RunSelectionAccepted(status="accepted", date=target, message="选股任务已提交"))


@router.post("/selections/import", response_model=APIResponse[SelectionImportResult])
def import_selections(
    request: SelectionImportRequest,
    _: None = Depends(_require_job_token),
) -> APIResponse[SelectionImportResult]:
    """Persist results produced by the scheduled local (domestic-network) selector."""
    target = request.trade_date.isoformat()
    db.save_selections([
        {
            **item.model_dump(),
            "trade_date": target,
        }
        for item in request.items
    ])
    return APIResponse(data=SelectionImportResult(date=request.trade_date, count=len(request.items)))


@router.post("/quotes/import", response_model=APIResponse[QuoteImportResult])
def import_quotes(
    request: QuoteImportRequest,
    _: None = Depends(_require_job_token),
) -> APIResponse[QuoteImportResult]:
    """Store local, real daily bars without querying an external market-data source."""
    dates = [item.trade_date for item in request.quotes]
    db.save_daily_quotes([
        {
            "code": item.stock_code,
            "name": item.stock_name,
            "trade_date": item.trade_date.isoformat(),
            "open": item.open,
            "high": item.high,
            "low": item.low,
            "close": item.close,
            "volume": item.volume,
        }
        for item in request.quotes
    ])
    return APIResponse(data=QuoteImportResult(
        count=len(request.quotes), start_date=min(dates), end_date=max(dates)
    ))


@router.post("/quotes/sync", response_model=APIResponse[RunSelectionAccepted], status_code=status.HTTP_202_ACCEPTED)
def sync_quotes(
    background_tasks: BackgroundTasks,
    request: RunSelectionRequest | None = Body(default=None),
    _: None = Depends(_require_job_token),
) -> APIResponse[RunSelectionAccepted]:
    target = request.trade_date if request and request.trade_date else date.fromisoformat(latest_trading_date())
    background_tasks.add_task(_sync_quotes_in_background, target)
    return APIResponse(data=RunSelectionAccepted(status="accepted", date=target, message="行情同步任务已提交"))


@router.get("/stock/{code}/detail", response_model=APIResponse[StockDetail])
def stock_detail(code: str, session: Session = Depends(get_db)) -> APIResponse[StockDetail]:
    stock = session.get(Stock, code)
    if stock is None:
        raise HTTPException(status_code=404, detail="股票不存在")
    latest = session.scalar(
        select(DailyQuote).where(DailyQuote.stock_code == code).order_by(DailyQuote.trade_date.desc()).limit(1)
    )
    quote = None
    if latest:
        quote = Quote(code=code, name=stock.name, price=latest.close, updated_at=latest.trade_date.isoformat())
    else:
        fallback = get_quote(code)
        quote = Quote(**{**fallback, "name": stock.name})
    return APIResponse(data=StockDetail(
        **StockSummary.model_validate(stock).model_dump(), latest_quote=quote
    ))


def _weekly_bars(rows: list[DailyQuote]) -> list[list[object]]:
    grouped: dict[tuple[int, int], list[DailyQuote]] = defaultdict(list)
    for row in rows:
        iso = row.trade_date.isocalendar()
        grouped[(iso.year, iso.week)].append(row)
    values: list[list[object]] = []
    for bars in grouped.values():
        first, last = bars[0], bars[-1]
        values.append([last.trade_date.isoformat(), float(first.open or 0), float(last.close or 0),
                       float(min(bar.low for bar in bars if bar.low is not None)),
                       float(max(bar.high for bar in bars if bar.high is not None)),
                       float(sum((bar.volume or 0) for bar in bars))])
    return values


@router.get("/stock/{code}/kline", response_model=APIResponse[list[list[object]]])
def stock_kline(
    code: str,
    period: Literal["daily", "weekly"] = Query("daily"),
    session: Session = Depends(get_db),
) -> APIResponse[list[list[object]]]:
    if session.get(Stock, code) is None:
        raise HTTPException(status_code=404, detail="股票不存在")
    rows = session.scalars(
        select(DailyQuote).where(DailyQuote.stock_code == code).order_by(DailyQuote.trade_date).limit(500)
    ).all()
    if period == "weekly":
        values = _weekly_bars(rows)
    else:
        values = [[row.trade_date.isoformat(), float(row.open or 0), float(row.close or 0),
                   float(row.low or 0), float(row.high or 0), float(row.volume or 0)] for row in rows]
    return APIResponse(data=values)
