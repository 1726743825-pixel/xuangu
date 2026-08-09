from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .session import engine


def _config() -> Config:
    backend_root = Path(__file__).resolve().parents[2]
    return Config(str(backend_root / "alembic.ini"))


def _stamp_unversioned_metadata_database(config: Config) -> None:
    """Adopt databases formerly created by ``Base.metadata.create_all``."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not tables or "alembic_version" in tables:
        return
    modern_core = {"stocks", "daily_quotes", "selection_results", "trade_calendar", "job_runs"}
    if not modern_core <= tables:
        return
    stock_columns = {column["name"] for column in inspector.get_columns("stocks")}
    selection_columns = {
        column["name"] for column in inspector.get_columns("selection_results")
    }
    if not {"list_date", "is_st"} <= stock_columns or not {"stock_code", "signals"} <= selection_columns:
        return

    revision = "20260808_0001"
    if "intraday_quotes" in tables:
        intraday_columns = {
            column["name"] for column in inspector.get_columns("intraday_quotes")
        }
        revision = (
            "20260809_0003" if "amount_estimated" in intraday_columns else "20260809_0002"
        )
    if (
        {"selection_price", "selection_price_date"} <= selection_columns
        and {"stock_quote_snapshots", "market_snapshots"} <= tables
    ):
        revision = "20260809_0004"
    command.stamp(config, revision)


def upgrade_database() -> None:
    config = _config()
    _stamp_unversioned_metadata_database(config)
    command.upgrade(config, "head")
