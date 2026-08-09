from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app import db


def test_snapshot_helpers_return_only_persisted_latest_values():
    db.init_db()
    code = "605599"
    assert db.read_latest_stock_snapshot(code) is None

    db.save_stock_quote_snapshots([{
        "code": code, "name": "快照契约", "price": 12.34, "change_pct": 1.2,
        "as_of": "2026-08-08T15:01:00+08:00", "source": "akshare",
    }])
    db.save_stock_quote_snapshots([{
        "code": code, "name": "快照契约", "price": 9.99, "change_pct": -2,
        "as_of": "2026-08-08T14:59:00+08:00", "source": "stale",
    }])
    snapshot = db.read_latest_stock_snapshot(code)
    assert snapshot is not None
    assert snapshot["price"] == Decimal("12.3400")
    assert snapshot["source"] == "akshare"

    db.save_market_snapshots([{
        "code": "000001.SH", "name": "上证指数", "level": 3600.1,
        "change_pct": 0.5, "as_of": "2026-08-08T15:01:00+08:00", "source": "akshare",
    }])
    rows = db.read_market_snapshots(["000001.SH"])
    assert len(rows) == 1
    assert rows[0]["level"] == Decimal("3600.1000")


@pytest.mark.parametrize(
    "row",
    [
        {"open": 10, "high": 9, "low": 8, "close": 8.5, "volume": 1},
        {"open": 10, "high": 11, "low": 9, "close": 10, "volume": -1},
        {"open": "nan", "high": 11, "low": 9, "close": 10, "volume": 1},
    ],
)
def test_daily_persistence_rejects_invalid_ohlcv(row):
    with pytest.raises(ValueError):
        db.save_daily_quotes([{
            "code": "605598", "name": "无效日线", "trade_date": "2026-08-08", **row,
        }])


def test_intraday_persistence_requires_real_30m_alignment():
    with pytest.raises(ValueError, match="half-hour"):
        db.save_intraday_quotes([{
            "code": "605597", "name": "无效分钟线", "interval": "30m",
            "trade_datetime": datetime(2026, 8, 8, 9, 45),
            "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100,
            "amount": 1000, "amount_estimated": False,
        }])
