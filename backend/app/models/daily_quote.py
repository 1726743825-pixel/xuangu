from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .stock import Stock


class DailyQuote(TimestampMixin, Base):
    __tablename__ = "daily_quotes"
    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_daily_quotes_stock_trade_date"),
        Index("ix_daily_quotes_stock_code_trade_date", "stock_code", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.code", ondelete="CASCADE"), nullable=False
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    source: Mapped[str | None] = mapped_column(String(64))

    stock: Mapped["Stock"] = relationship(back_populates="daily_quotes")
