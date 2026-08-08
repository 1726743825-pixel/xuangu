from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.models import Base, JobRun, SelectionResult

from .dao import job_runs, selection_results, stocks
from .session import SessionLocal, engine


def _as_date(value: str) -> date:
    return date.fromisoformat(value)


def _as_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def init_db() -> None:
    """Create tables for tests/development; deployments should run Alembic migrations."""
    Base.metadata.create_all(bind=engine)


def save_selections(results: list[dict[str, Any]]) -> None:
    with SessionLocal.begin() as session:
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
                    },
                    "score": item.get("score"),
                },
                commit=False,
            )


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
