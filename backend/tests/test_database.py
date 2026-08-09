from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dao import (
    DailyQuoteDAO,
    IntradayQuoteDAO,
    MarketSnapshotDAO,
    SelectionResultDAO,
    StockDAO,
    StockQuoteSnapshotDAO,
    TradeCalendarDAO,
)
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

    for table_name in (
        "stocks", "daily_quotes", "intraday_quotes", "selection_results", "trade_calendar",
        "stock_quote_snapshots", "market_snapshots",
    ):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert {"created_at", "updated_at"} <= columns

    assert "ix_daily_quotes_stock_code_trade_date" in {
        index["name"] for index in inspector.get_indexes("daily_quotes")
    }
    assert "ix_selection_results_stock_code_trade_date" in {
        index["name"] for index in inspector.get_indexes("selection_results")
    }
    assert "ix_intraday_quotes_stock_interval_datetime" in {
        index["name"] for index in inspector.get_indexes("intraday_quotes")
    }


def test_table_daos_create_upsert_and_query():
    engine = _engine()
    stock_dao = StockDAO()
    quote_dao = DailyQuoteDAO()
    intraday_dao = IntradayQuoteDAO()
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
        bar_time = datetime(2026, 8, 7, 10, 0)
        intraday_dao.upsert(
            session,
            values={
                "stock_code": "600000",
                "interval": "30m",
                "trade_datetime": bar_time,
                "open": Decimal("10.10"),
                "high": Decimal("10.60"),
                "low": Decimal("10.00"),
                "close": Decimal("10.50"),
                "volume": Decimal("500"),
                "amount": Decimal("5250"),
                "amount_estimated": False,
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
        intraday_dao.upsert(
            session,
            values={
                "stock_code": "600000", "interval": "30m", "trade_datetime": bar_time,
                "open": Decimal("10.10"), "high": Decimal("10.70"), "low": Decimal("10.00"),
                "close": Decimal("10.60"), "volume": Decimal("600"), "amount": Decimal("6360"),
                "amount_estimated": True,
            },
        )
        bars = intraday_dao.list_between(
            session, "600000", "30m", datetime(2026, 8, 7, 9, 30), datetime(2026, 8, 7, 15, 0)
        )
        assert len(bars) == 1
        assert bars[0].close == Decimal("10.6000")
        assert bars[0].amount_estimated is True
        selection = selection_dao.latest_for_stock(session, "600000", trade_date)
        assert selection.score == 88.5
        assert selection.signals["turnover_rate"] == 8.5
        assert selection.signals["board_count"] == 2
        assert calendar_dao.is_open(session, trade_date)


def test_fixed_selection_price_and_latest_snapshots_are_idempotent():
    engine = _engine()
    stock_dao = StockDAO()
    selection_dao = SelectionResultDAO()
    stock_snapshot_dao = StockQuoteSnapshotDAO()
    market_snapshot_dao = MarketSnapshotDAO()
    trade_date = date(2026, 8, 9)
    price_date = date(2026, 8, 7)
    newest = datetime(2026, 8, 8, 15, 1)

    with Session(engine) as session:
        stock_dao.upsert(session, values={"code": "600000", "name": "浦发银行"})
        base_selection = {
            "stock_code": "600000", "trade_date": trade_date, "strategy_name": "固定价测试",
            "signals": {"price": 10.2}, "score": 80,
            "selection_price": Decimal("10.20"), "selection_price_date": price_date,
        }
        selection_dao.upsert(session, values=base_selection)
        selection_dao.upsert(
            session,
            values={**base_selection, "score": 82, "selection_price": Decimal("10.30")},
        )
        selection = selection_dao.latest_for_stock(session, "600000", trade_date)
        assert selection is not None
        assert selection.selection_price == Decimal("10.3000")
        assert selection.selection_price_date == price_date

        with pytest.raises(ValueError, match="must not be after"):
            selection_dao.upsert(
                session,
                values={
                    **base_selection,
                    "selection_price_date": date(2026, 8, 10),
                },
            )

        stock_snapshot_dao.upsert(session, values={
            "stock_code": "600000", "price": Decimal("11.00"),
            "change_pct": Decimal("1.50"), "as_of": newest, "source": "akshare",
        })
        stock_snapshot_dao.upsert(session, values={
            "stock_code": "600000", "price": Decimal("9.00"),
            "change_pct": Decimal("-1.00"), "as_of": datetime(2026, 8, 8, 14, 59),
            "source": "stale",
        })
        latest_stock = stock_snapshot_dao.latest(session, "600000")
        assert latest_stock is not None
        assert latest_stock.price == Decimal("11.0000")
        assert latest_stock.source == "akshare"

        market_snapshot_dao.upsert(session, values={
            "code": "000001.SH", "name": "上证指数", "level": Decimal("3600.10"),
            "change_pct": Decimal("0.50"), "as_of": newest, "source": "akshare",
        })
        market_snapshot_dao.upsert(session, values={
            "code": "000001.SH", "name": "上证指数", "level": Decimal("3500.00"),
            "change_pct": Decimal("-1.00"), "as_of": datetime(2026, 8, 8, 14, 59),
            "source": "stale",
        })
        latest_market = market_snapshot_dao.list_latest(session, ["000001.SH"])
        assert len(latest_market) == 1
        assert latest_market[0].level == Decimal("3600.1000")
        assert latest_market[0].source == "akshare"
