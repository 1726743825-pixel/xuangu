from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dao import DailyQuoteDAO, SelectionResultDAO, StockDAO, TradeCalendarDAO
from app.models import Base


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_core_tables_have_timestamps_and_joint_indexes():
    engine = _engine()
    inspector = inspect(engine)

    for table_name in ("stocks", "daily_quotes", "selection_results", "trade_calendar"):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert {"created_at", "updated_at"} <= columns

    assert "ix_daily_quotes_stock_code_trade_date" in {
        index["name"] for index in inspector.get_indexes("daily_quotes")
    }
    assert "ix_selection_results_stock_code_trade_date" in {
        index["name"] for index in inspector.get_indexes("selection_results")
    }


def test_table_daos_create_upsert_and_query():
    engine = _engine()
    stock_dao = StockDAO()
    quote_dao = DailyQuoteDAO()
    selection_dao = SelectionResultDAO()
    calendar_dao = TradeCalendarDAO()
    trade_date = date(2026, 8, 8)

    with Session(engine) as session:
        stock_dao.upsert(
            session,
            values={"code": "600000", "name": "浦发银行", "industry": "银行", "is_st": False},
        )
        quote_dao.upsert(
            session,
            values={
                "stock_code": "600000",
                "trade_date": trade_date,
                "open": Decimal("10.00"),
                "high": Decimal("10.80"),
                "low": Decimal("9.90"),
                "close": Decimal("10.50"),
                "volume": Decimal("1000"),
                "amount": Decimal("10300"),
            },
        )
        selection_dao.upsert(
            session,
            values={
                "stock_code": "600000",
                "trade_date": trade_date,
                "strategy_name": "测试策略",
                "signals": {"reasons": ["放量"], "turnover_rate": 8.5, "board_count": 2},
                "score": 88.5,
            },
        )
        calendar_dao.upsert(session, values={"trade_date": trade_date, "is_open": True})

        assert quote_dao.get_by_stock_date(session, "600000", trade_date).close == Decimal("10.5000")
        selection = selection_dao.latest_for_stock(session, "600000", trade_date)
        assert selection.score == 88.5
        assert selection.signals["turnover_rate"] == 8.5
        assert selection.signals["board_count"] == 2
        assert calendar_dao.is_open(session, trade_date)
