import pytest
import httpx

from app.data import market_data


@pytest.fixture(autouse=True)
def reset_quote_source_health():
    market_data._quote_source_health.clear()
    yield
    market_data._quote_source_health.clear()


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
        lambda code, period, limit=640: [
            {"code": code, "period": period, "source": "tencent"}
        ],
    )

    rows = market_data.get_kline("SH600519", "daily")

    assert rows == [{"code": "600519", "period": "day", "source": "tencent"}]


def test_fill_missing_selection_prices_reads_only_selected_codes_and_preserves_fields():
    calls = []
    items = [
        {"code": "600519", "trade_date": "2026-08-07", "price": None, "score": 91.0,
         "industry": "白酒", "change_pct": 1.2, "turnover": 3.4, "board_count": 2},
        {"code": "300750", "trade_date": "2026-08-07", "price": None, "score": 88.0,
         "industry": "电池", "change_pct": 2.3, "turnover": 4.5, "board_count": 0},
    ]

    def loader(code, period):
        calls.append((code, period))
        return [
            {"datetime": "2026-08-06", "close": 10.0},
            {"datetime": "2026-08-07", "close": 11.23456 if code == "600519" else 22.0},
        ]

    enriched = market_data.fill_missing_selection_prices(items, kline_loader=loader)

    assert calls == [("600519", "day"), ("300750", "day")]
    assert [item["code"] for item in enriched] == ["600519", "300750"]
    assert [item["score"] for item in enriched] == [91.0, 88.0]
    assert enriched[0]["price"] == 11.2346
    assert enriched[1]["price"] == 22.0
    assert enriched[0]["industry"] == "白酒"
    assert enriched[1]["turnover"] == 4.5
    assert items[0]["price"] is None


def test_fill_missing_selection_prices_leaves_missing_session_close_as_none():
    items = [{"code": "600519", "trade_date": "2026-08-07", "price": None, "score": 91.0}]

    enriched = market_data.fill_missing_selection_prices(
        items,
        kline_loader=lambda code, period: [{"datetime": "2026-08-08", "close": 99.0}],
    )

    assert enriched[0]["price"] is None
    assert enriched[0]["score"] == 91.0


def test_quote_sources_respects_order_and_requires_tushare_token(monkeypatch):
    monkeypatch.setenv("QUOTE_SOURCES", "sina,baidu,tencent,tushare,baidu")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    assert market_data._quote_sources() == ("sina", "baidu", "tencent")

    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    assert market_data._quote_sources() == ("sina", "baidu", "tencent", "tushare")


def test_rotating_kline_falls_back_from_tencent_to_baidu(monkeypatch):
    calls = []
    monkeypatch.setenv("QUOTE_SOURCES", "tencent,baidu,sina")
    monkeypatch.setattr(
        market_data,
        "_get_tencent_kline",
        lambda code, period, limit=640: (_ for _ in ()).throw(
            market_data.MarketDataError("blocked")
        ),
    )

    def baidu(code, period, limit=640):
        calls.append((code, period, limit))
        return [{"datetime": "2026-08-07", "close": 10.0}]

    monkeypatch.setattr(market_data, "_get_baidu_kline", baidu)
    monkeypatch.setattr(
        market_data,
        "_get_sina_kline",
        lambda *args, **kwargs: pytest.fail("Sina must not run after Baidu succeeds"),
    )

    rows = market_data._get_rotating_kline("600000", "day", limit=20)

    assert calls == [("600000", "day", 20)]
    assert rows[0]["source"] == "baidu-qfq"


def test_rotating_kline_reaches_sina_after_prior_sources_fail(monkeypatch):
    monkeypatch.setenv("QUOTE_SOURCES", "tencent,baidu,sina")
    monkeypatch.setattr(
        market_data,
        "_get_tencent_kline",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad payload")),
    )
    monkeypatch.setattr(market_data, "_get_baidu_kline", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        market_data,
        "_get_sina_kline",
        lambda *args, **kwargs: [{"datetime": "2026-08-07", "close": 10.0}],
    )

    rows = market_data._get_rotating_kline("600000", "day")

    assert rows[0]["source"] == "sina-qfq"


def test_tencent_kline_only_accepts_and_normalises_qfq_block():
    symbol = "sh600000"
    payload = {
        "data": {
            symbol: {
                "qfqday": [["2026-08-07", "9.80", "10.20", "10.50", "9.70", "1234"]],
                "day": [["2026-08-07", "19.80", "20.20", "20.50", "19.70", "1234"]],
                "qt": {symbol: ["", "浦发银行"]},
            }
        }
    }

    row = market_data._parse_tencent_kline("600000", "day", payload)[0]

    assert (row["open"], row["high"], row["low"], row["close"]) == (
        9.8, 10.5, 9.7, 10.2,
    )
    assert row["volume"] == 123400
    assert row["source"] == "tencent-qfq"


def test_baidu_kline_normalises_qfq_fields(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_request_json",
        lambda *args, **kwargs: {
            "ResultCode": "0",
            "Result": {
                "newMarketData": {
                    "keys": [
                        "time", "open", "close", "volume", "high", "low",
                        "amount", "ratio", "turnoverratio", "preClose",
                    ],
                    "marketData": (
                        "2026-08-07,9.80,10.20,123400,10.50,9.70,1250000,"
                        "2.00,1.25,10.00;"
                    ),
                }
            },
        },
    )

    row = market_data._get_baidu_kline("600000", "day", limit=1)[0]

    assert (row["datetime"], row["open"], row["high"], row["low"], row["close"]) == (
        "2026-08-07", 9.8, 10.5, 9.7, 10.2,
    )
    assert row["volume"] == 123400
    assert row["source"] == "baidu-qfq"


def test_sina_kline_applies_qfq_factor_and_keeps_volume(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_request_json",
        lambda *args, **kwargs: {
            "result": {
                "data": [
                    {
                        "day": "2026-08-07 00:00:00",
                        "open": "20", "high": "22", "low": "18",
                        "close": "21", "volume": "123400",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        market_data,
        "_sina_qfq_factors",
        lambda symbol: ([market_data.date(2026, 1, 1)], [2.0]),
    )

    row = market_data._get_sina_kline("600000", "day", limit=1)[0]

    assert (row["open"], row["high"], row["low"], row["close"]) == (
        10.0, 11.0, 9.0, 10.5,
    )
    assert row["volume"] == 123400
    assert row["source"] == "sina-qfq"


def test_tushare_kline_applies_qfq_and_unit_conversion(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")

    def tushare_call(api_name, params, fields):
        if api_name == "adj_factor":
            return [
                {"trade_date": "20260806", "adj_factor": 1.0},
                {"trade_date": "20260807", "adj_factor": 2.0},
            ]
        return [
            {
                "trade_date": "20260806", "open": 20, "high": 22,
                "low": 18, "close": 21, "vol": 1234, "amount": 1250,
            },
            {
                "trade_date": "20260807", "open": 11, "high": 12,
                "low": 10, "close": 11.5, "vol": 2000, "amount": 2300,
            },
        ]

    monkeypatch.setattr(market_data, "_tushare_call", tushare_call)

    rows = market_data._get_tushare_kline("600000", "day", limit=2)

    assert rows[0]["datetime"] == "2026-08-06"
    assert rows[0]["close"] == 10.5
    assert rows[0]["volume"] == 123400
    assert rows[0]["amount"] == 1250000
    assert rows[0]["source"] == "tushare-qfq"


def test_sync_quote_history_continues_after_one_stock_fails(monkeypatch):
    universe = [
        {"code": "600000", "name": "失败样本"},
        {"code": "000001", "name": "平安银行"},
    ]

    def rotating(code, period, limit=640):
        if code == "600000":
            raise market_data.MarketDataError("all sources unavailable")
        return [
            {
                "datetime": "2026-08-07", "open": 10, "high": 11,
                "low": 9, "close": 10.5, "volume": 100, "amount": 1000,
                "source": "sina-qfq",
            }
        ]

    monkeypatch.setattr(market_data, "_get_rotating_kline", rotating)

    rows = market_data.sync_quote_history("2026-08-07", limit=20, universe=universe)

    assert [row["code"] for row in rows] == ["000001"]
    assert rows[0]["source"] == "sina-qfq"


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
