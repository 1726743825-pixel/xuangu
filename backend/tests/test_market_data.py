import pytest
import httpx

from app.data import market_data


def _tencent_quote_line(symbol: str, code: str, name: str) -> str:
    values = ["1", name, code] + [""] * 50
    return f'v_{symbol}="{"~".join(values)}";'


def test_tencent_stock_list_normalises_and_marks_st(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_universe_prefixes",
        lambda: (("600", "300"), ("688", "8", "4", "43")),
    )
    text = "\n".join(
        [
            _tencent_quote_line("sh600000", "600000", "浦发银行"),
            _tencent_quote_line("sz300001", "300001", "*ST测试"),
        ]
    )

    rows = market_data._parse_tencent_stock_list(text)

    assert rows[0]["code"] == "600000"
    assert rows[0]["exchange"] == "SH"
    assert rows[1]["code"] == "300001"
    assert rows[1]["is_st"] is True
    assert all(row["source"] == "tencent" for row in rows)


def test_tencent_stock_list_applies_allowed_and_excluded_prefixes(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_universe_prefixes",
        lambda: (("600", "601", "603", "000", "001", "002", "300", "301"),
                 ("688", "8", "4", "43")),
    )
    text = "\n".join(
        _tencent_quote_line(f"sh{code}" if code.startswith("6") else f"sz{code}", code, f"股票{code}")
        for code in ("600000", "601318", "603259", "000001", "001979", "002594",
                     "300750", "301269", "688001", "830001", "430001")
    )

    rows = market_data._parse_tencent_stock_list(text)
    codes = {row["code"] for row in rows}

    assert codes == {"600000", "601318", "603259", "000001", "001979", "002594",
                     "300750", "301269"}
    assert not any(code.startswith(("688", "8", "4", "43")) for code in codes)


def test_tencent_stock_list_keeps_only_supported_universe(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_tencent_stock_candidates",
        lambda: ["600000", "000001", "300001", "688001", "830001", "430001"],
    )
    monkeypatch.setattr(
        market_data,
        "_request_tencent_quote_batch",
        lambda symbols: "\n".join(
            [
                'v_sh600000="1~浦发银行~600000~9.21";',
                'v_sz000001="51~平安银行~000001~11.19";',
                'v_sz300001="51~特锐德~300001~20.00";',
                'v_sh688001="1~华兴源创~688001~20.00";',
                'v_bj830001="1~示例北交所~830001~1.00";',
                'v_bj430001="1~示例三板~430001~1.00";',
            ]
        ),
    )

    rows = market_data._tencent_stock_list()

    assert [row["code"] for row in rows] == ["000001", "300001", "600000"]


def test_sync_stock_list_prefers_tencent(monkeypatch):
    expected = [{"code": "600000", "name": "浦发银行", "source": "tencent"}]
    monkeypatch.setattr(market_data, "_tencent_stock_list", lambda: expected)

    assert market_data.sync_stock_list() == expected


def test_sync_stock_list_uses_tushare_only_after_tencent_failure(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_tencent_stock_list",
        lambda: (_ for _ in ()).throw(market_data.MarketDataError("offline")),
    )
    monkeypatch.setattr(
        market_data.os,
        "getenv",
        lambda name, default="": "token" if name == "TUSHARE_TOKEN" else default,
    )
    monkeypatch.setattr(market_data, "_tushare_stock_list", lambda: [{"code": "600000"}])

    assert market_data.sync_stock_list() == [{"code": "600000"}]


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

    monkeypatch.setattr(market_data, "sync_stock_list", fail_if_called)
    assert market_data.sync_daily_quotes("2026-08-08") == []
    assert called is False


def test_sync_daily_quotes_uses_tencent_qfq_and_target_universe(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "sync_stock_list",
        lambda: [
            {"code": "600000", "name": "浦发银行", "industry": "银行", "is_st": False},
            {"code": "688001", "name": "科创样本", "industry": None, "is_st": False},
        ],
    )
    monkeypatch.setattr(
        market_data,
        "_get_tencent_kline",
        lambda code, period, limit=640: [
            {"datetime": "2026-08-06", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "amount": 1000},
            {"datetime": "2026-08-07", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 200, "amount": 2200},
        ],
    )

    rows = market_data.sync_daily_quotes("2026-08-07")

    assert rows == [{"code": "600000", "name": "浦发银行", "industry": "银行", "is_st": False,
                     "trade_date": "2026-08-07", "open": 10.5, "high": 12, "low": 10,
                     "close": 11, "volume": 200, "amount": 2200, "source": "tencent-qfq"}]


def test_sync_quote_history_keeps_prior_bars(monkeypatch):
    monkeypatch.setattr(market_data, "sync_stock_list", lambda: [{"code": "000001", "name": "平安银行"}])
    monkeypatch.setattr(
        market_data, "_get_tencent_kline",
        lambda code, period, limit=640: [
            {"datetime": "2026-08-06", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "amount": 1000},
            {"datetime": "2026-08-07", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 200, "amount": 2200},
        ],
    )

    rows = market_data.sync_quote_history("2026-08-07", limit=80)

    assert [row["trade_date"] for row in rows] == ["2026-08-06", "2026-08-07"]


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
