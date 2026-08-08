import pytest
import httpx

from app.data import market_data


def test_sync_stock_list_normalises_and_marks_st(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_fetch_market_pages",
        lambda fields: [
            {"f12": "600000", "f13": 1, "f14": "浦发银行", "f26": 19991110, "f100": "银行"},
            {"f12": "300001", "f13": 0, "f14": "*ST测试", "f26": "20091030", "f100": "软件"},
        ],
    )

    rows = market_data.sync_stock_list()

    assert rows[0]["exchange"] == "SZ"
    assert rows[0]["is_st"] is True
    assert rows[0]["list_date"] == "2009-10-30"
    assert rows[1]["industry"] == "银行"


def test_clean_snapshot_handles_suspension_and_limit_rules():
    st = market_data._clean_snapshot_row(
        {
            "f12": "600001",
            "f13": 1,
            "f14": "ST测试",
            "f2": 10.5,
            "f3": 5,
            "f4": 0.5,
            "f5": 10,
            "f6": 10000,
            "f7": 5,
            "f8": 1,
            "f15": 10.5,
            "f16": 10,
            "f17": 10,
            "f18": 10,
        },
        "2026-08-07",
    )
    suspended = market_data._clean_snapshot_row(
        {"f12": "688001", "f14": "示例", "f2": "-", "f5": 0, "f18": 10},
        "2026-08-07",
    )

    assert st is not None
    assert st["limit_up_price"] == 10.5
    assert st["is_limit_up"] is True
    assert st["volume"] == 1000
    assert suspended is not None
    assert suspended["is_suspended"] is True
    assert suspended["is_limit_up"] is False


def test_sync_daily_quotes_skips_weekend_without_network(monkeypatch):
    called = False

    def fail_if_called(_trade_date):
        nonlocal called
        called = True
        raise AssertionError("network must not be called")

    monkeypatch.setattr(market_data, "_latest_market_snapshot", fail_if_called)
    assert market_data.sync_daily_quotes("2026-08-08") == []
    assert called is False


def test_sync_daily_quotes_rejects_bad_date():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        market_data.sync_daily_quotes("20260808")


def test_get_kline_prefers_tencent_and_accepts_prefixed_code(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_get_tencent_kline",
        lambda code, period: [{"code": code, "period": period, "source": "tencent"}],
    )

    rows = market_data.get_kline("SH600519", "daily")

    assert rows == [{"code": "600519", "period": "day", "source": "tencent"}]


def test_get_kline_rejects_unknown_period():
    with pytest.raises(ValueError, match="unsupported"):
        market_data.get_kline("600519", "quarter")


def test_request_json_retries_network_errors(monkeypatch):
    attempts = 0
    sleeps = 0

    def failing_request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("temporary failure")

    def record_sleep(*args, **kwargs):
        nonlocal sleeps
        sleeps += 1

    monkeypatch.setattr(market_data._http_client, "request", failing_request)
    monkeypatch.setattr(market_data, "_sleep_before_retry", record_sleep)

    with pytest.raises(market_data.MarketDataError, match="3 attempts"):
        market_data._request_json("GET", "https://example.invalid")

    assert attempts == 3
    assert sleeps == 2
