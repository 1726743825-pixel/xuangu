"""Add provenance to persisted daily and intraday bars.

Revision ID: 20260809_0005
Revises: 20260809_0004
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0005"
down_revision: str | Sequence[str] | None = "20260809_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, metadata-only additions preserve every existing Volume row.
    op.add_column("daily_quotes", sa.Column("source", sa.String(length=64), nullable=True))
    op.add_column("intraday_quotes", sa.Column("source", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("intraday_quotes", "source")
    op.drop_column("daily_quotes", "source")
