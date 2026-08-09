from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .stock import Stock


class IntradayQuote(TimestampMixin, Base):
    """A normalised intraday OHLCV bar.

    ``interval`` is a provider-neutral interval token (currently ``30m`` is
    planned).  The timestamp is the start time of the bar in Asia/Shanghai,
    stored as a timezone-naive ``datetime`` to remain compatible with SQLite.
    """

    __tablename__ = "intraday_quotes"
    __table_args__ = (
        UniqueConstraint(
            "stock_code", "interval", "trade_datetime",
            name="uq_intraday_quotes_stock_interval_datetime",
        ),
        Index(
            "ix_intraday_quotes_stock_interval_datetime",
            "stock_code", "interval", "trade_datetime",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.code", ondelete="CASCADE"), nullable=False
    )
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    amount_estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str | None] = mapped_column(String(64))

    stock: Mapped["Stock"] = relationship(back_populates="intraday_quotes")
