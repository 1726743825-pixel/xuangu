from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .stock import Stock


class StockQuoteSnapshot(TimestampMixin, Base):
    """The latest independently sourced quote for one stock."""

    __tablename__ = "stock_quote_snapshots"

    stock_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.code", ondelete="CASCADE"), primary_key=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    stock: Mapped["Stock"] = relationship(back_populates="quote_snapshot")
