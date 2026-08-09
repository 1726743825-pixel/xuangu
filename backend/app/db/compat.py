from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import logging
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import DailyQuote, IntradayQuote, JobRun, SelectionResult, Stock

from .dao import (
    intraday_quotes,
    job_runs,
    market_snapshots,
    selection_results,
    stock_quote_snapshots,
    stocks,
)
from .session import SessionLocal


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


def _finite_decimal(value: Any, field: str, *, nullable: bool = False) -> Decimal | None:
    if value is None and nullable:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _validated_ohlcv(
    row: dict[str, Any], *, interval: str | None = None
) -> dict[str, Decimal | None]:
    values = {
        field: _finite_decimal(row.get(field), field)
        for field in ("open", "high", "low", "close")
    }
    low = values["low"]
    high = values["high"]
    if low is None or high is None:
        raise ValueError("OHLC values are required")
    if low > high:
        raise ValueError("OHLC invariant requires low <= high")
    if any(value is None or value <= 0 for value in values.values()):
        raise ValueError("OHLC prices must be positive")
    for field in ("open", "close"):
        value = values[field]
        if value is None or value < low or value > high:
            raise ValueError("OHLC invariant requires low <= open/close <= high")
    volume = _finite_decimal(row.get("volume"), "volume", nullable=True)
    amount = _finite_decimal(row.get("amount"), "amount", nullable=True)
    if volume is not None and volume < 0:
        raise ValueError("volume must be non-negative")
    if amount is not None and amount < 0:
        raise ValueError("amount must be non-negative")
    if interval is not None and interval != "30m":
        raise ValueError("only the persisted 30m interval is supported")
    return {**values, "volume": volume, "amount": amount}


def init_db() -> None:
    """Upgrade the configured database, including pre-Alembic SQLite volumes."""
    from .migration_runner import upgrade_database

    upgrade_database()


def _save_selections(session: Session, results: list[dict[str, Any]]) -> None:
    for item in results:
        trade_date = _as_date(item["trade_date"])
        selection_price = _finite_decimal(
            item.get("selection_price", item.get("price")), "selection_price", nullable=True
        )
        raw_price_date = item.get("selection_price_date")
        selection_price_date = (
            _as_date(raw_price_date)
            if raw_price_date
            else (trade_date if selection_price is not None else None)
        )
        if (selection_price is None) != (selection_price_date is None):
            raise ValueError("selection_price and selection_price_date must be set together")
        if selection_price is not None and selection_price < 0:
            raise ValueError("selection_price must be non-negative")
        if selection_price_date is not None and selection_price_date != trade_date:
            raise ValueError("selection_price_date must equal trade_date")
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
                "trade_date": trade_date,
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
                "selection_price": selection_price,
                "selection_price_date": selection_price_date,
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
    fixed_price = row.selection_price
    fixed_price_date = row.selection_price_date
    if fixed_price is None and signals.get("price") is not None:
        # Compatibility for pre-migration rows. This is the import-time signal
        # value and never a Stock or live-snapshot value.
        fixed_price = signals["price"]
        fixed_price_date = row.trade_date
    return {
        "code": row.stock_code,
        "trade_date": row.trade_date.isoformat(),
        "name": row.stock.name,
        "price": fixed_price,
        "selection_price": fixed_price,
        "selection_price_date": fixed_price_date.isoformat() if fixed_price_date else None,
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
            values = _validated_ohlcv(row)
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
                    "open": values["open"], "high": values["high"], "low": values["low"],
                    "close": values["close"], "volume": values["volume"],
                    "amount": values["amount"],
                },
                commit=False,
            )
        return len(rows)


def save_intraday_quotes(rows: list[dict[str, Any]]) -> int:
    """Persist local, real intraday bars in SQLite's Asia/Shanghai-naive form."""
    with SessionLocal.begin() as session:
        for row in rows:
            interval = row["interval"]
            values = _validated_ohlcv(row, interval=interval)
            trade_datetime = _as_shanghai_naive(row["trade_datetime"])
            if (
                trade_datetime.second
                or trade_datetime.microsecond
                or trade_datetime.minute not in {0, 30}
            ):
                raise ValueError("30m trade_datetime must align to a half-hour boundary")
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
                    "interval": interval,
                    "trade_datetime": trade_datetime,
                    "open": values["open"], "high": values["high"], "low": values["low"],
                    "close": values["close"], "volume": values["volume"],
                    "amount": values["amount"],
                    "amount_estimated": row["amount_estimated"],
                },
                commit=False,
            )
        return len(rows)


def save_stock_quote_snapshots(rows: list[dict[str, Any]]) -> int:
    """Persist local quote snapshots without changing fixed selection prices."""
    with SessionLocal.begin() as session:
        for row in rows:
            price = _finite_decimal(row.get("price"), "price")
            change_pct = _finite_decimal(row.get("change_pct"), "change_pct", nullable=True)
            if price is None or price < 0:
                raise ValueError("price must be non-negative")
            source = str(row.get("source") or "").strip()
            if not source:
                raise ValueError("source is required")
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
            stock_quote_snapshots.upsert(
                session,
                values={
                    "stock_code": row["code"],
                    "price": price,
                    "change_pct": change_pct,
                    "as_of": _as_shanghai_naive(row["as_of"]),
                    "source": source,
                },
                commit=False,
            )
    return len(rows)


def read_latest_stock_snapshot(stock_code: str) -> dict[str, Any] | None:
    """Read only the latest quote snapshot; Stock has no fallback price."""
    with SessionLocal() as session:
        row = stock_quote_snapshots.latest(session, stock_code)
        if row is None:
            return None
        return {
            "code": row.stock_code,
            "price": row.price,
            "change_pct": row.change_pct,
            "as_of": row.as_of.isoformat(),
            "source": row.source,
        }


def save_market_snapshots(rows: list[dict[str, Any]]) -> int:
    """Idempotently persist latest snapshots for the configured market indices."""
    with SessionLocal.begin() as session:
        for row in rows:
            level = _finite_decimal(row.get("level"), "level")
            change_pct = _finite_decimal(row.get("change_pct"), "change_pct", nullable=True)
            if level is None or level < 0:
                raise ValueError("level must be non-negative")
            source = str(row.get("source") or "").strip()
            if not source:
                raise ValueError("source is required")
            market_snapshots.upsert(
                session,
                values={
                    "code": row["code"],
                    "name": row["name"],
                    "level": level,
                    "change_pct": change_pct,
                    "as_of": _as_shanghai_naive(row["as_of"]),
                    "source": source,
                },
                commit=False,
            )
    return len(rows)


def read_market_snapshots(codes: list[str] | None = None) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = market_snapshots.list_latest(session, codes)
        return [
            {
                "code": row.code,
                "name": row.name,
                "level": row.level,
                "change_pct": row.change_pct,
                "as_of": row.as_of.isoformat(),
                "source": row.source,
            }
            for row in rows
        ]


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
