"""Persist fixed selection prices and latest market snapshots.

Revision ID: 20260809_0004
Revises: 20260809_0003
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0004"
down_revision: str | Sequence[str] | None = "20260809_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable additions preserve every pre-existing selection row. New writes
    # enforce the paired price/date contract at the repository boundary.
    op.add_column(
        "selection_results",
        sa.Column("selection_price", sa.Numeric(precision=18, scale=4), nullable=True),
    )
    op.add_column(
        "selection_results",
        sa.Column("selection_price_date", sa.Date(), nullable=True),
    )

    op.create_table(
        "stock_quote_snapshots",
        sa.Column("stock_code", sa.String(length=16), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("change_pct", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(["stock_code"], ["stocks.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("stock_code"),
    )
    op.create_index(
        "ix_stock_quote_snapshots_as_of", "stock_quote_snapshots", ["as_of"], unique=False
    )

    op.create_table(
        "market_snapshots",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("level", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("change_pct", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index("ix_market_snapshots_as_of", "market_snapshots", ["as_of"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_market_snapshots_as_of", table_name="market_snapshots")
    op.drop_table("market_snapshots")
    op.drop_index("ix_stock_quote_snapshots_as_of", table_name="stock_quote_snapshots")
    op.drop_table("stock_quote_snapshots")
    op.drop_column("selection_results", "selection_price_date")
    op.drop_column("selection_results", "selection_price")
