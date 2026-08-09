from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .daily_quote import DailyQuote
    from .intraday_quote import IntradayQuote
    from .selection_result import SelectionResult
    from .stock_quote_snapshot import StockQuoteSnapshot


class Stock(TimestampMixin, Base):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128))
    list_date: Mapped[date | None] = mapped_column(Date)
    is_st: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)

    daily_quotes: Mapped[list["DailyQuote"]] = relationship(back_populates="stock")
    intraday_quotes: Mapped[list["IntradayQuote"]] = relationship(back_populates="stock")
    selection_results: Mapped[list["SelectionResult"]] = relationship(back_populates="stock")
    quote_snapshot: Mapped["StockQuoteSnapshot | None"] = relationship(
        back_populates="stock", uselist=False
    )
