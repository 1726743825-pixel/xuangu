"""Create core market and selection tables.

Revision ID: 20260808_0001
Revises:
Create Date: 2026-08-08
"""

from collections.abc import Sequence
from datetime import date, datetime
import json

from alembic import op
import sqlalchemy as sa


revision: str = "20260808_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    ]


def _prepare_legacy_tables() -> set[str]:
    """Move the pre-Alembic tables aside so their data can be imported."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    legacy_tables: set[str] = set()
    required_columns = {
        "stocks": {"code", "list_date", "is_st", "created_at", "updated_at"},
        "selection_results": {"stock_code", "signals", "created_at", "updated_at"},
        "job_runs": {"id", "created_at", "updated_at"},
    }
    existing_tables = set(inspector.get_table_names())
    for table_name, required in required_columns.items():
        if table_name not in existing_tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if not required.issubset(columns):
            legacy_name = f"_legacy_{table_name}"
            op.rename_table(table_name, legacy_name)
            legacy_tables.add(legacy_name)
    return legacy_tables


def _parse_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _import_legacy_data(legacy_tables: set[str]) -> None:
    bind = op.get_bind()
    legacy_tables |= {
        name for name in sa.inspect(bind).get_table_names() if name.startswith("_legacy_")
    }
    now = datetime.now()

    if "_legacy_stocks" in legacy_tables:
        rows = bind.execute(sa.text("SELECT code, name, industry, updated_at FROM _legacy_stocks")).mappings()
        for row in rows:
            bind.execute(
                sa.text(
                    "INSERT OR IGNORE INTO stocks "
                    "(code,name,industry,list_date,is_st,created_at,updated_at) "
                    "VALUES (:code,:name,:industry,NULL,0,:created_at,:updated_at)"
                ),
                {
                    **row,
                    "created_at": _parse_datetime(row["updated_at"]) or now,
                    "updated_at": _parse_datetime(row["updated_at"]) or now,
                },
            )

    if "_legacy_selection_results" in legacy_tables:
        rows = list(bind.execute(sa.text("SELECT * FROM _legacy_selection_results")).mappings())
        for row in rows:
            bind.execute(
                sa.text(
                    "INSERT OR IGNORE INTO stocks "
                    "(code,name,industry,list_date,is_st,created_at,updated_at) "
                    "VALUES (:code,:name,:industry,NULL,0,:now,:now)"
                ),
                {"code": row["code"], "name": row["name"], "industry": row["industry"], "now": now},
            )
            try:
                reasons = json.loads(row["reasons_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                reasons = []
            try:
                indicators = json.loads(row["indicators_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                indicators = {}
            bind.execute(
                sa.text(
                    "INSERT INTO selection_results "
                    "(id,stock_code,trade_date,strategy_name,signals,score,created_at,updated_at) "
                    "VALUES (:id,:stock_code,:trade_date,:strategy_name,:signals,:score,:now,:now)"
                ),
                {
                    "id": row["id"],
                    "stock_code": row["code"],
                    "trade_date": _parse_date(row["trade_date"]),
                    "strategy_name": row["strategy_name"] or "默认策略",
                    "signals": json.dumps(
                        {
                            "reasons": reasons,
                            "indicators": indicators,
                            "price": row["price"],
                            "change_pct": row["change_pct"],
                        },
                        ensure_ascii=False,
                    ),
                    "score": row["score"],
                    "now": now,
                },
            )

    if "_legacy_job_runs" in legacy_tables:
        rows = bind.execute(sa.text("SELECT * FROM _legacy_job_runs")).mappings()
        for row in rows:
            bind.execute(
                sa.text(
                    "INSERT INTO job_runs "
                    "(id,status,trade_date,started_at,finished_at,result_count,error,created_at,updated_at) "
                    "VALUES (:id,:status,:trade_date,:started_at,:finished_at,:result_count,:error,:created_at,:updated_at)"
                ),
                {
                    **row,
                    "trade_date": _parse_date(row["trade_date"]),
                    "started_at": _parse_datetime(row["started_at"]),
                    "finished_at": _parse_datetime(row["finished_at"]),
                    "created_at": _parse_datetime(row["started_at"]) or now,
                    "updated_at": _parse_datetime(row["finished_at"] or row["started_at"]) or now,
                },
            )

    for table_name in ("_legacy_job_runs", "_legacy_selection_results", "_legacy_stocks"):
        if table_name in legacy_tables:
            op.drop_table(table_name)


def upgrade() -> None:
    legacy_tables = _prepare_legacy_tables()
    op.create_table(
        "stocks",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("is_st", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("code"),
        if_not_exists=True,
    )
    op.create_table(
        "trade_calendar",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("trade_date"),
        if_not_exists=True,
    )
    op.create_table(
        "daily_quotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("volume", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=4), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["stock_code"], ["stocks.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_code", "trade_date", name="uq_daily_quotes_stock_trade_date"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_daily_quotes_stock_code_trade_date",
        "daily_quotes",
        ["stock_code", "trade_date"],
        unique=False,
        if_not_exists=True,
    )
    op.create_table(
        "selection_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["stock_code"], ["stocks.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_code", "trade_date", "strategy_name", name="uq_selection_stock_date_strategy"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_selection_results_stock_code_trade_date",
        "selection_results",
        ["stock_code", "trade_date"],
        unique=False,
        if_not_exists=True,
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("result_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    _import_legacy_data(legacy_tables)


def downgrade() -> None:
    op.drop_table("job_runs")
    op.drop_index("ix_selection_results_stock_code_trade_date", table_name="selection_results")
    op.drop_table("selection_results")
    op.drop_index("ix_daily_quotes_stock_code_trade_date", table_name="daily_quotes")
    op.drop_table("daily_quotes")
    op.drop_table("trade_calendar")
    op.drop_table("stocks")
