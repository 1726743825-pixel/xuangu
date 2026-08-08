from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class TradeCalendar(TimestampMixin, Base):
    __tablename__ = "trade_calendar"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
