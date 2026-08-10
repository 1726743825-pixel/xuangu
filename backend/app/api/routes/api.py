from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from math import isfinite
import os
import secrets
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.session import get_db
from ... import db
from ...data.market_data import latest_trading_date
from ...integrations.market_adapter import get_quote
from ...jobs import execute_quote_sync, execute_selection
from ...models import (
    DailyQuote,
    IntradayQuote,
    MarketSnapshot,
    SelectionResult as SelectionResultModel,
    Stock,
    StockQuoteSnapshot,
)
from ...schemas import (
    APIResponse,
    HealthData,
    IntradayQuoteImportRequest,
    IntradayQuoteImportResult,
    MARKET_INDEX_DEFINITIONS,
    MarketIndexItem,
    MarketIndices,
    MarketSnapshotImportRequest,
    MarketSnapshotImportResult,
    Quote,
    QuoteImportRequest,
    QuoteImportResult,
    RunSelectionAccepted,
    RunSelectionRequest,
    SelectionImportRequest,
    SelectionImportResult,
    SelectionPage,
    SelectionPerformance,
    SelectionResult,
    HoldingPeriodReturn,
    StockDetail,
    StockPage,
    StockSummary,
    TradeDateCleanupRequest,
    TradeDateCleanupResult,
)

router = APIRouter(prefix="/api", tags=["API"])


def _shanghai_iso(value: datetime) -> str:
    return value.replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()


def _selection_schema(
    row: SelectionResultModel, snapshot: StockQuoteSnapshot | None = None
) -> SelectionResult:
    signals = row.signals or {}
    selection_price = float(row.selection_price) if row.selection_price is not None else None
    return SelectionResult(
        code=row.stock_code,
        name=row.stock.name,
        trade_date=row.trade_date.isoformat(),
        price=selection_price,
        selection_price=selection_price,
        selection_price_date=row.selection_price_date,
        current_price=float(snapshot.price) if snapshot is not None else None,
        current_price_as_of=_shanghai_iso(snapshot.as_of) if snapshot is not None else None,
        change_pct=signals.get("change_pct"),
        score=row.score,
        strategy_name=row.strategy_name,
        industry=row.stock.industry or signals.get("industry"),
        turnover_rate=signals.get("turnover_rate"),
        board_count=signals.get("board_count"),
        reasons=signals.get("reasons", []),
        indicators=signals.get("indicators", {}),
    )


@router.get("/health", response_model=APIResponse[HealthData])
def health() -> APIResponse[HealthData]:
    return APIResponse(data=HealthData(status="ok", service="xuangu-api"))


@router.get("/market/indices", response_model=APIResponse[MarketIndices])
def market_indices(session: Session = Depends(get_db)) -> APIResponse[MarketIndices]:
    codes = [code for _, code in MARKET_INDEX_DEFINITIONS]
    stored = {
        row.code: row
        for row in session.scalars(select(MarketSnapshot).where(MarketSnapshot.code.in_(codes))).all()
    }
    items = []
    for name, code in MARKET_INDEX_DEFINITIONS:
        row = stored.get(code)
        items.append(MarketIndexItem(
            name=name,
            code=code,
            price=float(row.level) if row is not None else None,
            change_pct=float(row.change_pct) if row is not None and row.change_pct is not None else None,
            as_of=_shanghai_iso(row.as_of) if row is not None else None,
        ))
    return APIResponse(data=MarketIndices(items=items))


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
    codes = [row.stock_code for row in rows]
    snapshots = {
        row.stock_code: row
        for row in session.scalars(
            select(StockQuoteSnapshot).where(StockQuoteSnapshot.stock_code.in_(codes))
        ).all()
    } if codes else {}
    return APIResponse(data=SelectionPage(
        date=target,
        strategy=strategy,
        items=[_selection_schema(row, snapshots.get(row.stock_code)) for row in rows],
        count=len(rows),
    ))


_PERFORMANCE_PERIODS = (("1d", 1), ("3d", 3), ("5d", 5), ("10d", 10), ("25d", 25), ("3m", 60))


@router.get("/selections/{code}/performance", response_model=APIResponse[SelectionPerformance])
def selection_performance(
    code: str,
    trade_date: date = Query(..., alias="date"),
    strategy: str = Query(..., min_length=1, max_length=128),
    session: Session = Depends(get_db),
) -> APIResponse[SelectionPerformance]:
    """Calculate forward returns from persisted daily closes, never simulated quotes.

    ``3m`` is defined as 60 subsequent persisted trading sessions.
    """
    selection = session.scalar(
        select(SelectionResultModel)
        .join(Stock)
        .where(
            SelectionResultModel.stock_code == code,
            SelectionResultModel.trade_date == trade_date,
            SelectionResultModel.strategy_name == strategy,
        )
    )
    if selection is None:
        raise HTTPException(status_code=404, detail="未找到对应入选记录")

    quotes = session.scalars(
        select(DailyQuote)
        .where(DailyQuote.stock_code == code, DailyQuote.trade_date > trade_date)
        .order_by(DailyQuote.trade_date)
        .limit(60)
    ).all()
    base = quotes[0] if quotes else None
    base_close = float(base.open) if base and base.open is not None else None
    periods: list[HoldingPeriodReturn] = []
    for label, trading_days in _PERFORMANCE_PERIODS:
        target_index = trading_days - 1
        target = quotes[target_index] if base_close is not None and len(quotes) > target_index else None
        if target is None or target.close is None:
            periods.append(HoldingPeriodReturn(label=label, trading_days=trading_days, status="暂无数据"))
            continue
        target_close = float(target.close)
        periods.append(HoldingPeriodReturn(
            label=label,
            trading_days=trading_days,
            target_date=target.trade_date,
            close=target_close,
            return_pct=round((target_close / base_close - 1) * 100, 4),
            status="ok",
        ))
    return APIResponse(data=SelectionPerformance(
        code=code,
        name=selection.stock.name,
        trade_date=trade_date,
        strategy_name=strategy,
        base_close=base_close,
        periods=periods,
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
    results = [
        {
            **item.model_dump(),
            "trade_date": target,
            "selection_price_date": (
                item.selection_price_date.isoformat() if item.selection_price_date else None
            ),
        }
        for item in request.items
    ]
    if request.replace_existing:
        db.replace_strategy_selections(target, request.items[0].strategy_name, results)
    else:
        db.save_selections(results)
    return APIResponse(data=SelectionImportResult(date=request.trade_date, count=len(request.items)))


@router.post("/market/snapshots/import", response_model=APIResponse[MarketSnapshotImportResult])
def import_market_snapshots(
    request: MarketSnapshotImportRequest,
    session: Session = Depends(get_db),
    _: None = Depends(_require_job_token),
) -> APIResponse[MarketSnapshotImportResult]:
    """Import AKShare snapshots prepared on the domestic host; never fetch live data here."""
    available_indices = [item for item in request.indices if item.available]
    db.save_market_snapshots([
        {
            "code": item.code,
            "name": item.name,
            "level": item.price,
            "change_pct": item.change_pct,
            "as_of": item.as_of,
            "source": item.source,
        }
        for item in available_indices
    ])
    stock_rows = []
    for item in request.stocks:
        existing = session.get(Stock, item.code)
        stock_rows.append({
            "code": item.code,
            "name": item.name,
            "industry": existing.industry if existing is not None else None,
            "is_st": existing.is_st if existing is not None else False,
            "price": item.price,
            "change_pct": item.change_pct,
            "as_of": item.as_of,
            "source": item.source,
        })
    db.save_stock_quote_snapshots(stock_rows)
    return APIResponse(data=MarketSnapshotImportResult(
        indices=len(available_indices), stocks=len(request.stocks)
    ))


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
            "amount": item.amount,
            "source": item.source,
        }
        for item in request.quotes
    ])
    return APIResponse(data=QuoteImportResult(
        count=len(request.quotes), start_date=min(dates), end_date=max(dates)
    ))


@router.post("/quotes/intraday/import", response_model=APIResponse[IntradayQuoteImportResult])
def import_intraday_quotes(
    request: IntradayQuoteImportRequest,
    session: Session = Depends(get_db),
    _: None = Depends(_require_job_token),
) -> APIResponse[IntradayQuoteImportResult]:
    """Store locally supplied real 30-minute bars; no external source is queried."""
    rows = []
    for item in request.quotes:
        stock_name = item.stock_name
        if stock_name is None:
            stock = session.get(Stock, item.stock_code)
            if stock is None:
                raise HTTPException(status_code=422, detail="stock_name is required for an unknown stock")
            stock_name = stock.name
        rows.append({
            "code": item.stock_code,
            "name": stock_name,
            "interval": item.interval,
            "trade_datetime": item.trade_datetime,
            "open": item.open, "high": item.high, "low": item.low, "close": item.close,
            "volume": item.volume, "amount": item.amount,
            "amount_estimated": item.amount_estimated,
            "source": item.source,
        })
    db.save_intraday_quotes(rows)
    timestamps = [item.trade_datetime for item in request.quotes]
    return APIResponse(data=IntradayQuoteImportResult(
        count=len(rows), start_datetime=min(timestamps), end_datetime=max(timestamps)
    ))


@router.delete("/data/trade-date", response_model=APIResponse[TradeDateCleanupResult])
def cleanup_trade_date_data(
    request: TradeDateCleanupRequest,
    _: None = Depends(_require_job_token),
) -> APIResponse[TradeDateCleanupResult]:
    """Delete all result/quote rows for one explicitly confirmed Shanghai date."""
    counts = db.delete_trade_date_data(request.date.isoformat())
    return APIResponse(data=TradeDateCleanupResult(date=request.date, **counts))


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


def _valid_persisted_bar(row: DailyQuote | IntradayQuote) -> bool:
    raw = (row.open, row.high, row.low, row.close, row.volume)
    if any(value is None for value in raw):
        return False
    open_, high, low, close, volume = (float(value) for value in raw)
    return (
        all(isfinite(value) for value in (open_, high, low, close, volume))
        and min(open_, high, low, close) > 0
        and volume >= 0
        and low <= open_ <= high
        and low <= close <= high
    )


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
    period: Literal["daily", "weekly", "30m"] = Query("daily"),
    session: Session = Depends(get_db),
) -> APIResponse[list[list[object]]]:
    if session.get(Stock, code) is None:
        raise HTTPException(status_code=404, detail="股票不存在")
    if period == "30m":
        intraday_rows = session.scalars(
            select(IntradayQuote)
            .where(IntradayQuote.stock_code == code, IntradayQuote.interval == "30m")
            .order_by(IntradayQuote.trade_datetime)
        ).all()
        intraday_rows = [row for row in intraday_rows if _valid_persisted_bar(row)]
        shanghai = ZoneInfo("Asia/Shanghai")
        values = [
            [
                row.trade_datetime.replace(tzinfo=shanghai).isoformat(),
                float(row.open), float(row.close), float(row.low),
                float(row.high), float(row.volume),
            ]
            for row in intraday_rows
        ]
        return APIResponse(data=values)
    rows = session.scalars(
        select(DailyQuote).where(DailyQuote.stock_code == code).order_by(DailyQuote.trade_date).limit(500)
    ).all()
    rows = [row for row in rows if _valid_persisted_bar(row)]
    if period == "weekly":
        values = _weekly_bars(rows)
    else:
        values = [[row.trade_date.isoformat(), float(row.open), float(row.close),
                   float(row.low), float(row.high), float(row.volume)] for row in rows]
    return APIResponse(data=values)
