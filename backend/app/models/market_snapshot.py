from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class MarketSnapshot(TimestampMixin, Base):
    """The latest snapshot for a market index, independent of stock masters."""

    __tablename__ = "market_snapshots"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
