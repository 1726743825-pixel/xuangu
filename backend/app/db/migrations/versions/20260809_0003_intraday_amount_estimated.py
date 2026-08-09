"""Track whether imported intraday amount is estimated.

Revision ID: 20260809_0003
Revises: 20260809_0002
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0003"
down_revision: str | Sequence[str] | None = "20260809_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "intraday_quotes",
        sa.Column("amount_estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("intraday_quotes", "amount_estimated")
