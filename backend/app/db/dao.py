from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, joinedload

from app.models import (
    DailyQuote,
    IntradayQuote,
    JobRun,
    MarketSnapshot,
    SelectionResult,
    Stock,
    StockQuoteSnapshot,
    TradeCalendar,
)

from .crud import CRUDBase


class StockDAO(CRUDBase[Stock]):
    def __init__(self) -> None:
        super().__init__(Stock)

    def upsert(self, session: Session, *, values: dict[str, Any], commit: bool = True) -> Stock:
        statement = sqlite_insert(Stock).values(**values)
        update_values = {key: value for key, value in values.items() if key != "code"}
        update_values["updated_at"] = func.current_timestamp()
        statement = statement.on_conflict_do_update(index_elements=[Stock.code], set_=update_values)
        session.execute(statement)
        if commit:
            session.commit()
        return session.get_one(Stock, values["code"])


class DailyQuoteDAO(CRUDBase[DailyQuote]):
    def __init__(self) -> None:
        super().__init__(DailyQuote)

    def get_by_stock_date(self, session: Session, stock_code: str, trade_date: date) -> DailyQuote | None:
        return session.scalar(
            select(DailyQuote).where(
                DailyQuote.stock_code == stock_code, DailyQuote.trade_date == trade_date
            )
        )

    def upsert(self, session: Session, *, values: dict[str, Any], commit: bool = True) -> DailyQuote:
        statement = sqlite_insert(DailyQuote).values(**values)
        mutable_fields = ("open", "high", "low", "close", "volume", "amount")
        statement = statement.on_conflict_do_update(
            index_elements=[DailyQuote.stock_code, DailyQuote.trade_date],
            set_={
                **{field: values.get(field) for field in mutable_fields},
                "updated_at": func.current_timestamp(),
            },
        )
        session.execute(statement)
        if commit:
            session.commit()
        return self.get_by_stock_date(session, values["stock_code"], values["trade_date"])  # type: ignore[return-value]

    def list_between(self, session: Session, start_date: date, end_date: date) -> Sequence[DailyQuote]:
        return session.scalars(
            select(DailyQuote)
            .options(joinedload(DailyQuote.stock))
            .where(DailyQuote.trade_date.between(start_date, end_date))
            .order_by(DailyQuote.stock_code, DailyQuote.trade_date)
        ).all()


class IntradayQuoteDAO(CRUDBase[IntradayQuote]):
    def __init__(self) -> None:
        super().__init__(IntradayQuote)

    def get_by_stock_interval_datetime(
        self, session: Session, stock_code: str, interval: str, trade_datetime: datetime
    ) -> IntradayQuote | None:
        return session.scalar(
            select(IntradayQuote).where(
                IntradayQuote.stock_code == stock_code,
                IntradayQuote.interval == interval,
                IntradayQuote.trade_datetime == trade_datetime,
            )
        )

    def upsert(self, session: Session, *, values: dict[str, Any], commit: bool = True) -> IntradayQuote:
        statement = sqlite_insert(IntradayQuote).values(**values)
        mutable_fields = ("open", "high", "low", "close", "volume", "amount", "amount_estimated")
        statement = statement.on_conflict_do_update(
            index_elements=[
                IntradayQuote.stock_code,
                IntradayQuote.interval,
                IntradayQuote.trade_datetime,
            ],
            set_={
                **{field: values.get(field) for field in mutable_fields},
                "updated_at": func.current_timestamp(),
            },
        )
        session.execute(statement)
        if commit:
            session.commit()
        return self.get_by_stock_interval_datetime(
            session, values["stock_code"], values["interval"], values["trade_datetime"]
        )  # type: ignore[return-value]

    def list_between(
        self,
        session: Session,
        stock_code: str,
        interval: str,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> Sequence[IntradayQuote]:
        return session.scalars(
            select(IntradayQuote)
            .where(
                IntradayQuote.stock_code == stock_code,
                IntradayQuote.interval == interval,
                IntradayQuote.trade_datetime.between(start_datetime, end_datetime),
            )
            .order_by(IntradayQuote.trade_datetime)
        ).all()


class SelectionResultDAO(CRUDBase[SelectionResult]):
    def __init__(self) -> None:
        super().__init__(SelectionResult)

    def upsert(self, session: Session, *, values: dict[str, Any], commit: bool = True) -> SelectionResult:
        selection_price = values.get("selection_price")
        selection_price_date = values.get("selection_price_date")
        if (selection_price is None) != (selection_price_date is None):
            raise ValueError("selection_price and selection_price_date must be set together")
        if selection_price_date is not None and selection_price_date != values["trade_date"]:
            raise ValueError("selection_price_date must equal trade_date")
        statement = sqlite_insert(SelectionResult).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                SelectionResult.stock_code,
                SelectionResult.trade_date,
                SelectionResult.strategy_name,
            ],
            set_={
                "signals": values["signals"],
                "score": values.get("score"),
                "selection_price": values.get("selection_price"),
                "selection_price_date": values.get("selection_price_date"),
                "updated_at": func.current_timestamp(),
            },
        )
        session.execute(statement)
        if commit:
            session.commit()
        return session.scalar(
            select(SelectionResult).where(
                SelectionResult.stock_code == values["stock_code"],
                SelectionResult.trade_date == values["trade_date"],
                SelectionResult.strategy_name == values["strategy_name"],
            )
        )  # type: ignore[return-value]

    def list_by_trade_date(self, session: Session, trade_date: date) -> Sequence[SelectionResult]:
        return session.scalars(
            select(SelectionResult)
            .options(joinedload(SelectionResult.stock))
            .where(SelectionResult.trade_date == trade_date)
            .order_by(SelectionResult.score.desc())
        ).all()

    def latest_for_stock(
        self, session: Session, stock_code: str, trade_date: date | None = None
    ) -> SelectionResult | None:
        statement = (
            select(SelectionResult)
            .options(joinedload(SelectionResult.stock))
            .where(SelectionResult.stock_code == stock_code)
            .order_by(SelectionResult.trade_date.desc(), SelectionResult.score.desc())
        )
        if trade_date is not None:
            statement = statement.where(SelectionResult.trade_date == trade_date)
        return session.scalar(statement.limit(1))

    def list_for_strategy(
        self, session: Session, strategy_name: str, start_date: date, end_date: date
    ) -> Sequence[SelectionResult]:
        return session.scalars(
            select(SelectionResult)
            .where(
                SelectionResult.strategy_name == strategy_name,
                SelectionResult.trade_date.between(start_date, end_date),
            )
            .order_by(SelectionResult.trade_date, SelectionResult.stock_code)
        ).all()


class StockQuoteSnapshotDAO(CRUDBase[StockQuoteSnapshot]):
    def __init__(self) -> None:
        super().__init__(StockQuoteSnapshot)

    def upsert(
        self, session: Session, *, values: dict[str, Any], commit: bool = True
    ) -> StockQuoteSnapshot:
        statement = sqlite_insert(StockQuoteSnapshot).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[StockQuoteSnapshot.stock_code],
            set_={
                "price": values["price"],
                "change_pct": values.get("change_pct"),
                "as_of": values["as_of"],
                "source": values["source"],
                "updated_at": func.current_timestamp(),
            },
            where=StockQuoteSnapshot.as_of <= values["as_of"],
        )
        session.execute(statement)
        if commit:
            session.commit()
        return session.get_one(StockQuoteSnapshot, values["stock_code"])

    def latest(self, session: Session, stock_code: str) -> StockQuoteSnapshot | None:
        return session.get(StockQuoteSnapshot, stock_code)


class MarketSnapshotDAO(CRUDBase[MarketSnapshot]):
    def __init__(self) -> None:
        super().__init__(MarketSnapshot)

    def upsert(
        self, session: Session, *, values: dict[str, Any], commit: bool = True
    ) -> MarketSnapshot:
        statement = sqlite_insert(MarketSnapshot).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[MarketSnapshot.code],
            set_={
                "name": values["name"],
                "level": values["level"],
                "change_pct": values.get("change_pct"),
                "as_of": values["as_of"],
                "source": values["source"],
                "updated_at": func.current_timestamp(),
            },
            where=MarketSnapshot.as_of <= values["as_of"],
        )
        session.execute(statement)
        if commit:
            session.commit()
        return session.get_one(MarketSnapshot, values["code"])

    def list_latest(
        self, session: Session, codes: Sequence[str] | None = None
    ) -> Sequence[MarketSnapshot]:
        statement = select(MarketSnapshot)
        if codes is not None:
            statement = statement.where(MarketSnapshot.code.in_(codes))
        return session.scalars(statement.order_by(MarketSnapshot.code)).all()

class TradeCalendarDAO(CRUDBase[TradeCalendar]):
    def __init__(self) -> None:
        super().__init__(TradeCalendar)

    def is_open(self, session: Session, trade_date: date) -> bool:
        calendar_day = session.get(TradeCalendar, trade_date)
        return bool(calendar_day and calendar_day.is_open)

    def upsert(self, session: Session, *, values: dict[str, Any], commit: bool = True) -> TradeCalendar:
        statement = sqlite_insert(TradeCalendar).values(**values).on_conflict_do_update(
            index_elements=[TradeCalendar.trade_date],
            set_={"is_open": values["is_open"], "updated_at": func.current_timestamp()},
        )
        session.execute(statement)
        if commit:
            session.commit()
        return session.get_one(TradeCalendar, values["trade_date"])


class JobRunDAO(CRUDBase[JobRun]):
    def __init__(self) -> None:
        super().__init__(JobRun)

    def latest(self, session: Session) -> JobRun | None:
        return session.scalar(select(JobRun).order_by(JobRun.id.desc()).limit(1))


stocks = StockDAO()
daily_quotes = DailyQuoteDAO()
intraday_quotes = IntradayQuoteDAO()
selection_results = SelectionResultDAO()
trade_calendar = TradeCalendarDAO()
job_runs = JobRunDAO()
stock_quote_snapshots = StockQuoteSnapshotDAO()
market_snapshots = MarketSnapshotDAO()
