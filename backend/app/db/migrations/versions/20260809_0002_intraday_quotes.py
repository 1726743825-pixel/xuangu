"""Add provider-neutral intraday OHLCV storage.

Revision ID: 20260809_0002
Revises: 20260808_0001
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0002"
down_revision: str | None = "20260808_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intraday_quotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=16), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("trade_datetime", sa.DateTime(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("volume", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(["stock_code"], ["stocks.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_code", "interval", "trade_datetime",
            name="uq_intraday_quotes_stock_interval_datetime",
        ),
    )
    op.create_index(
        "ix_intraday_quotes_stock_interval_datetime",
        "intraday_quotes",
        ["stock_code", "interval", "trade_datetime"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_intraday_quotes_stock_interval_datetime", table_name="intraday_quotes")
    op.drop_table("intraday_quotes")
