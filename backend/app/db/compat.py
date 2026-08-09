from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Base, DailyQuote, IntradayQuote, JobRun, SelectionResult, Stock

from .dao import intraday_quotes, job_runs, selection_results, stocks
from .session import SessionLocal, engine


def _as_date(value: str) -> date:
    return date.fromisoformat(value)


def _as_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


_SHANGHAI = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


def _as_shanghai_naive(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(_SHANGHAI).replace(tzinfo=None)


def init_db() -> None:
    """Create tables for tests/development; deployments should run Alembic migrations."""
    Base.metadata.create_all(bind=engine)


def _save_selections(session: Session, results: list[dict[str, Any]]) -> None:
    for item in results:
        stocks.upsert(
            session,
            values={
                "code": item.get("stock_code") or item["code"],
                "name": item.get("stock_name") or item["name"],
                "industry": item.get("industry"),
                "is_st": item.get("is_st", False),
            },
            commit=False,
        )
        selection_results.upsert(
            session,
            values={
                "stock_code": item.get("stock_code") or item["code"],
                "trade_date": _as_date(item["trade_date"]),
                "strategy_name": item.get("strategy_name") or "默认策略",
                    "signals": item.get("signals") or {
                        "reasons": item.get("reasons", []),
                        "indicators": item.get("indicators", {}),
                        "price": item.get("price"),
                        "change_pct": item.get("change_pct"),
                        "turnover_rate": item.get("turnover_rate"),
                        "board_count": item.get("board_count"),
                },
                "score": item.get("score"),
            },
            commit=False,
        )


def save_selections(results: list[dict[str, Any]]) -> None:
    with SessionLocal.begin() as session:
        _save_selections(session, results)


def replace_strategy_selections(
    trade_date: str, strategy_name: str, results: list[dict[str, Any]]
) -> None:
    """Atomically replace exactly one strategy's results for one trade date."""
    with SessionLocal.begin() as session:
        session.execute(
            delete(SelectionResult).where(
                SelectionResult.trade_date == _as_date(trade_date),
                SelectionResult.strategy_name == strategy_name,
            )
        )
        _save_selections(session, results)


def delete_trade_date_data(trade_date: str) -> dict[str, int]:
    """Atomically delete one Shanghai trading date without touching stock masters."""
    target = _as_date(trade_date)
    intraday_start = datetime.combine(target, time.min)
    intraday_end = intraday_start + timedelta(days=1)
    with SessionLocal.begin() as session:
        selection_count = session.execute(
            delete(SelectionResult).where(SelectionResult.trade_date == target)
        ).rowcount or 0
        daily_count = session.execute(
            delete(DailyQuote).where(DailyQuote.trade_date == target)
        ).rowcount or 0
        intraday_count = session.execute(
            delete(IntradayQuote).where(
                IntradayQuote.trade_datetime >= intraday_start,
                IntradayQuote.trade_datetime < intraday_end,
            )
        ).rowcount or 0
    counts = {
        "selection_results_deleted": int(selection_count),
        "daily_quotes_deleted": int(daily_count),
        "intraday_quotes_deleted": int(intraday_count),
    }
    logger.info("trade-date cleanup completed date=%s counts=%s", target.isoformat(), counts)
    return counts


def _selection_dict(row: SelectionResult) -> dict[str, Any]:
    signals = row.signals or {}
    return {
        "code": row.stock_code,
        "trade_date": row.trade_date.isoformat(),
        "name": row.stock.name,
        "price": signals.get("price"),
        "change_pct": signals.get("change_pct"),
        "score": row.score,
        "strategy_name": row.strategy_name,
        "industry": row.stock.industry,
        "turnover_rate": signals.get("turnover_rate"),
        "board_count": signals.get("board_count"),
        "reasons": signals.get("reasons", []),
        "indicators": signals.get("indicators", {}),
    }


def read_selections(trade_date: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = selection_results.list_by_trade_date(session, _as_date(trade_date))
        return [_selection_dict(row) for row in rows]


def read_selection(stock_code: str, trade_date: str | None = None) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = selection_results.latest_for_stock(
            session, stock_code, _as_date(trade_date) if trade_date else None
        )
        return _selection_dict(row) if row else None


def save_job(
    status: str,
    trade_date: str,
    started_at: str,
    finished_at: str | None = None,
    result_count: int = 0,
    error: str | None = None,
) -> int:
    with SessionLocal() as session:
        job = job_runs.create(
            session,
            values={
                "status": status,
                "trade_date": _as_date(trade_date),
                "started_at": _as_datetime(started_at),
                "finished_at": _as_datetime(finished_at),
                "result_count": result_count,
                "error": error,
            },
        )
        return job.id


def _job_dict(job: JobRun) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "trade_date": job.trade_date.isoformat(),
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "result_count": job.result_count,
        "error": job.error,
    }


def latest_job() -> dict[str, Any] | None:
    with SessionLocal() as session:
        job = job_runs.latest(session)
        return _job_dict(job) if job else None


def has_daily_quotes(trade_date: str) -> bool:
    """Whether at least one persisted bar exists for the requested session."""
    from .dao import daily_quotes

    with SessionLocal() as session:
        return bool(
            session.scalar(
                select(func.count()).select_from(daily_quotes.model).where(
                    daily_quotes.model.trade_date == _as_date(trade_date)
                )
            )
        )


def read_stock_universe() -> list[dict[str, Any]]:
    """Return the persisted stock master so daily sync avoids repeated master fetches."""
    with SessionLocal() as session:
        rows = session.scalars(select(Stock).order_by(Stock.code)).all()
        return [
            {"code": row.code, "name": row.name, "industry": row.industry, "is_st": row.is_st}
            for row in rows
        ]


def save_daily_quotes(rows: list[dict[str, Any]]) -> int:
    """Persist normalised Tencent OHLCV rows and their stock master attributes."""
    from .dao import daily_quotes

    with SessionLocal.begin() as session:
        for row in rows:
            stocks.upsert(
                session,
                values={
                    "code": row["code"],
                    "name": row["name"],
                    "industry": row.get("industry"),
                    "is_st": bool(row.get("is_st", False)),
                },
                commit=False,
            )
            daily_quotes.upsert(
                session,
                values={
                    "stock_code": row["code"],
                    "trade_date": _as_date(row["trade_date"]),
                    "open": row["open"], "high": row["high"], "low": row["low"],
                    "close": row["close"], "volume": row.get("volume"),
                    "amount": row.get("amount"),
                },
                commit=False,
            )
        return len(rows)


def save_intraday_quotes(rows: list[dict[str, Any]]) -> int:
    """Persist local, real intraday bars in SQLite's Asia/Shanghai-naive form."""
    with SessionLocal.begin() as session:
        for row in rows:
            stocks.upsert(
                session,
                values={
                    "code": row["code"],
                    "name": row["name"],
                    "industry": row.get("industry"),
                    "is_st": bool(row.get("is_st", False)),
                },
                commit=False,
            )
            intraday_quotes.upsert(
                session,
                values={
                    "stock_code": row["code"],
                    "interval": row["interval"],
                    "trade_datetime": _as_shanghai_naive(row["trade_datetime"]),
                    "open": row["open"], "high": row["high"], "low": row["low"],
                    "close": row["close"], "volume": row["volume"],
                    "amount": row.get("amount"),
                    "amount_estimated": row["amount_estimated"],
                },
                commit=False,
            )
        return len(rows)


def read_daily_bars(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Return persisted OHLCV data through the DAO boundary."""
    from .dao import daily_quotes

    with SessionLocal() as session:
        rows = daily_quotes.list_between(session, _as_date(start_date), _as_date(end_date))
        return [
            {
                "stock_code": row.stock_code,
                "stock_name": row.stock.name,
                "trade_date": row.trade_date.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
        ]


def read_strategy_selections(
    strategy_name: str, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    """Return persisted strategy signals through the DAO boundary."""
    with SessionLocal() as session:
        rows = selection_results.list_for_strategy(
            session, strategy_name, _as_date(start_date), _as_date(end_date)
        )
        return [
            {"stock_code": row.stock_code, "trade_date": row.trade_date.isoformat()}
            for row in rows
        ]
