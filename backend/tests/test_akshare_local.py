from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.data import akshare_local, market_data


def _daily_fixture() -> pd.DataFrame:
    # Same named-column shape observed from AKShare 1.18.83/Sina for 301080.
    return pd.DataFrame([
        {"date": "2026-08-06", "open": 53.72, "high": 56.18, "low": 53.30,
         "close": 53.96, "volume": 6148012, "amount": 336361462,
         "outstanding_share": 126837356, "turnover": 0.048472},
        {"date": "2026-08-07", "open": 53.96, "high": 64.75, "low": 53.35,
         "close": 64.75, "volume": 14887398, "amount": 915450283,
         "outstanding_share": 126837356, "turnover": 0.117374},
    ])


def _minute_fixture() -> pd.DataFrame:
    # Same named-column shape observed for 600721; columns are deliberately
    # shuffled to prove the adapter never depends on dataframe position.
    return pd.DataFrame([
        {"amount": 3085058.0071, "close": 10.54, "day": "2026-08-07 14:00:00",
         "low": 10.54, "volume": 292700, "high": 10.54, "open": 10.54},
        {"amount": 7073394.0009, "close": 10.54, "day": "2026-08-07 15:00:00",
         "low": 10.54, "volume": 671100, "high": 10.54, "open": 10.54},
    ])


def test_daily_and_30m_use_named_akshare_fields_and_real_amount():
    calls = []
    ak = SimpleNamespace(
        stock_zh_a_daily=lambda **kwargs: calls.append(("daily", kwargs)) or _daily_fixture(),
        stock_zh_a_minute=lambda **kwargs: calls.append(("minute", kwargs)) or _minute_fixture(),
    )

    daily = akshare_local.fetch_daily_bars(
        "301080", start_date="2026-08-01", end_date="2026-08-09", akshare_module=ak,
    )
    minute = akshare_local.fetch_30m_bars("600721", limit=1, akshare_module=ak)

    assert calls == [
        ("daily", {"symbol": "sz301080", "start_date": "20260801", "end_date": "20260809", "adjust": ""}),
        ("minute", {"symbol": "sh600721", "period": "30", "adjust": ""}),
    ]
    assert daily[-1] == {
        "code": "301080", "trade_date": "2026-08-07", "datetime": "2026-08-07",
        "open": 53.96, "high": 64.75, "low": 53.35, "close": 64.75,
        "volume": 14887398.0, "amount": 915450283.0, "interval": "day",
        "adjustment": "none", "source": "akshare-sina",
    }
    assert minute == [{
        "code": "600721", "interval": "30m", "datetime": "2026-08-07T15:00:00+08:00",
        "open": 10.54, "high": 10.54, "low": 10.54, "close": 10.54,
        "volume": 671100.0, "amount": 7073394.0009, "amount_estimated": False,
        "adjustment": "none", "source": "akshare-sina",
    }]


def test_impossible_301080_ohlc_is_rejected():
    bad = pd.DataFrame([{
        "date": "2026-08-07", "open": 125, "close": 40, "low": 40.13,
        "high": 37.91, "volume": 1000, "amount": 40000,
    }])
    ak = SimpleNamespace(stock_zh_a_daily=lambda **kwargs: bad)

    with pytest.raises(akshare_local.AkshareDataError, match="OHLC 不变量失败"):
        akshare_local.fetch_daily_bars(
            "301080", start_date="2026-08-01", end_date="2026-08-09", akshare_module=ak,
        )


def test_existing_tencent_parser_rejects_the_observed_301080_corrupt_shape():
    payload = {"data": {"sz301080": {"qfqday": [[
        "2026-08-07", "125", "40", "37.91", "40.13", "1000",
    ]]}}}

    with pytest.raises(market_data.MarketDataError, match="OHLC invariant failed"):
        market_data._parse_tencent_kline("301080", "day", payload)


def test_market_index_mapping_and_weekend_observation_semantics():
    frame = pd.DataFrame([
        {"代码": "sz399006", "名称": "创业板指", "最新价": 3563.116, "涨跌额": 47.556, "涨跌幅": 1.353},
        {"代码": "sh000688", "名称": "科创50", "最新价": 1744.0236, "涨跌额": 42.732, "涨跌幅": 2.512},
        {"代码": "sh000001", "名称": "上证指数", "最新价": 3940.0371, "涨跌额": 39.685, "涨跌幅": 1.017},
        {"代码": "sz399001", "名称": "深证成指", "最新价": 14311.008, "涨跌额": 200.887, "涨跌幅": 1.424},
    ])
    ak = SimpleNamespace(stock_zh_index_spot_sina=lambda: frame)

    rows = akshare_local.fetch_market_indices(
        akshare_module=ak,
        observed_at=datetime(2026, 8, 9, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert [row["symbol"] for row in rows] == [
        "000001.SH", "399001.SZ", "399006.SZ", "000688.SH",
    ]
    assert all(row["source"] == "akshare-sina" for row in rows)
    assert all(row["price_date"] is None for row in rows)
    assert rows[0]["observed_at"] == "2026-08-09T18:00:00+08:00"
    assert len(rows) == 4
    assert not any(row["name"] == "沪深300" for row in rows)

    compatibility_rows = akshare_local.fetch_five_indices(
        akshare_module=ak,
        observed_at=datetime(2026, 8, 9, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert compatibility_rows == rows
    assert len(compatibility_rows) == 4


def test_selected_spot_filters_codes_but_does_not_invent_price_date():
    frame = pd.DataFrame([
        {"代码": "sz301080", "名称": "百普赛斯", "最新价": 64.75, "涨跌额": 10.79,
         "涨跌幅": 20.0, "时间戳": "15:35:15"},
        {"代码": "sh600721", "名称": "百花医药", "最新价": 10.54, "涨跌额": 0.96,
         "涨跌幅": 10.02, "时间戳": "15:35:00"},
        {"代码": "sh600000", "名称": "非入选", "最新价": 9.0, "涨跌额": -0.1,
         "涨跌幅": -1.1, "时间戳": "15:35:00"},
    ])
    ak = SimpleNamespace(stock_zh_a_spot=lambda: frame)

    rows = akshare_local.fetch_selected_spot(["301080", "600721"], akshare_module=ak)

    assert [row["code"] for row in rows] == ["600721", "301080"]
    assert all(row["price_date"] is None for row in rows)
    assert all(row["source"] == "akshare-sina" for row in rows)


def test_weekend_price_falls_back_to_latest_real_close_without_reordering():
    calls = []
    items = [
        {"code": "301080", "trade_date": "2026-08-09", "price": None, "score": 87},
        {"code": "600721", "trade_date": "2026-08-09", "price": None, "score": 76},
    ]

    def loader(code, *, start_date, end_date):
        calls.append((code, start_date, end_date))
        close = 64.75 if code == "301080" else 10.54
        return [{"code": code, "trade_date": "2026-08-07", "close": close, "source": "akshare-sina"}]

    result = akshare_local.fill_selection_prices(items, daily_loader=loader)

    assert [(row["code"], row["score"]) for row in result] == [("301080", 87), ("600721", 76)]
    assert [row["price"] for row in result] == [64.75, 10.54]
    assert {row["price_date"] for row in result} == {"2026-08-07"}
    assert {row["price_source"] for row in result} == {"akshare-sina"}
    assert all(call[2] == "2026-08-09" for call in calls)
    assert items[0]["price"] is None


def test_report_price_wins_and_missing_history_stays_null():
    items = [
        {"code": "301080", "trade_date": "2026-08-09", "price": 64.75,
         "price_date": "2026-08-07"},
        {"code": "600721", "trade_date": "2026-08-09", "price": None},
    ]
    calls = []

    def loader(code, **kwargs):
        calls.append(code)
        return []

    result = akshare_local.fill_selection_prices(items, daily_loader=loader)

    assert result[0]["price"] == 64.75
    assert result[0]["price_date"] == "2026-08-07"
    assert result[0]["price_source"] == "official-report"
    assert result[1]["price"] is None
    assert result[1]["price_date"] is None
    assert calls == ["600721"]


def test_price_fetch_failure_stays_null_instead_of_fabricating_a_quote():
    item = {"code": "301080", "trade_date": "2026-08-09", "price": None}

    def unavailable(*args, **kwargs):
        raise akshare_local.AkshareDataError("network unavailable")

    result = akshare_local.fill_selection_prices([item], daily_loader=unavailable)

    assert result == [{
        "code": "301080", "trade_date": "2026-08-09", "price": None,
        "price_date": None, "price_source": None,
    }]
