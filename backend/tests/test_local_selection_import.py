from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "existing" / "import_local_selections.py"
SPEC = importlib.util.spec_from_file_location("local_selection_import", SCRIPT_PATH)
assert SPEC and SPEC.loader
local_import = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local_import)


class _Response:
    def __init__(self, count: int):
        self._count = count

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": {"count": self._count}}


class _PayloadResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._data}


def _items(_: str):
    return [{"code": "600519", "name": "贵州茅台", "score": 88.0, "trade_date": "2026-08-07"}]


def test_import_local_selection_posts_contract_with_token(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response(1)

    assert local_import.import_selections("2026-08-07", selector=_items, post=post) == 1
    assert captured["json"]["trade_date"] == "2026-08-07"
    assert captured["json"]["items"] == _items("")
    assert "replace_existing" not in captured["json"]
    assert captured["headers"]["X-Job-Token"] == "secret-not-to-print"


def test_import_selection_maps_authoritative_turnover_and_board_metrics(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    captured = {}

    def post(_url, **kwargs):
        captured.update(kwargs)
        return _Response(1)

    official_item = [{**_items("")[0], "turnover": 11.7, "board_count": 2}]
    assert local_import.import_selections("2026-08-07", selector=lambda _: official_item, post=post) == 1
    imported = captured["json"]["items"][0]
    assert imported["turnover_rate"] == 11.7
    assert imported["board_count"] == 2


def test_import_selection_maps_akshare_fixed_price_date(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")
    captured = {}
    priced = [{**_items("")[0], "price": 1525.0, "price_date": "2026-08-07", "price_source": "akshare-sina"}]

    def post(_url, **kwargs):
        captured.update(kwargs)
        return _Response(1)

    assert local_import.import_selections("2026-08-07", selector=lambda _: priced, post=post) == 1
    row = captured["json"]["items"][0]
    assert row["selection_price"] == 1525.0
    assert row["selection_price_date"] == "2026-08-07"


def test_import_local_selection_rejects_empty_results(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")
    with pytest.raises(local_import.SelectionImportError, match="结果为空"):
        local_import.import_selections("2026-08-07", selector=lambda _: [])


def test_import_uses_actual_trade_date_emitted_by_weekend_selector(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")
    captured = {}

    def post(url, **kwargs):
        captured.update(kwargs)
        return _Response(1)

    assert local_import.import_selections("2026-08-08", selector=_items, post=post) == 1
    assert captured["json"]["trade_date"] == "2026-08-07"


def test_import_selection_sends_replace_flag_only_when_explicit(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    captured = {}

    def post(_url, **kwargs):
        captured.update(kwargs)
        return _Response(1)

    assert local_import.import_selections("2026-08-07", replace_existing=True, selector=_items, post=post) == 1
    assert captured["json"]["replace_existing"] is True
    assert "secret-not-to-print" not in str(captured["json"])


def test_main_success_log_uses_actual_trade_date(monkeypatch, capsys):
    monkeypatch.setattr(local_import, "_load_env_file", lambda _: None)
    monkeypatch.setattr(local_import, "_import_selection_run", lambda *_args, **_kwargs: local_import.SelectionImportRun(10, "2026-08-07", _items("")))
    monkeypatch.setattr(local_import, "_sync_selected_market_data", lambda *_: (120, 240, 4, 10))

    assert local_import.main(["--trade-date", "2026-08-07", "--env-file", "unused.env"]) == 0
    assert "trade_date=2026-08-07, selections=10, daily_quotes=120, intraday_30m_quotes=240, indices=4, stocks=10" in capsys.readouterr().out


def test_main_passes_replace_flag_only_when_requested(monkeypatch):
    monkeypatch.setattr(local_import, "_load_env_file", lambda _: None)
    captured = {}

    def selection_run(*_args, **kwargs):
        captured.update(kwargs)
        return local_import.SelectionImportRun(1, "2026-08-07", _items(""))

    monkeypatch.setattr(local_import, "_import_selection_run", selection_run)
    monkeypatch.setattr(local_import, "_sync_selected_market_data", lambda *_: (1, 1, 4, 1))
    assert local_import.main(["--trade-date", "2026-08-07", "--replace-existing", "--env-file", "unused.env"]) == 0
    assert captured["replace_existing"] is True


def test_main_skips_weekends_without_running_or_uploading(monkeypatch, capsys):
    monkeypatch.setattr(local_import, "_load_env_file", lambda _: None)
    monkeypatch.setattr(local_import, "_import_selection_run", lambda *_args, **_kwargs: pytest.fail("weekend must not select"))

    assert local_import.main(["--trade-date", "2026-08-09", "--env-file", "unused.env"]) == 0
    assert "非交易日，跳过" in capsys.readouterr().out


def test_authoritative_screener_failure_does_not_upload(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    uploaded = False

    def selector(_):
        raise local_import.LocalSelectionDataError("官方报告未生成")

    def post(*_args, **_kwargs):
        nonlocal uploaded
        uploaded = True
        return _Response(1)

    with pytest.raises(local_import.LocalSelectionDataError, match="官方报告未生成"):
        local_import.import_selections("2026-08-07", selector=selector, post=post)
    assert uploaded is False


def test_import_local_selection_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.delenv("JOB_API_TOKEN", raising=False)
    with pytest.raises(local_import.SelectionImportError, match="JOB_API_TOKEN"):
        local_import.import_selections("2026-08-07", selector=_items)


def test_import_local_selection_reports_http_failure(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")

    request = httpx.Request("POST", "https://example.test/api/selections/import")
    response = httpx.Response(503, request=request)
    def post(*args, **kwargs):
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)

    with pytest.raises(local_import.SelectionImportError, match="HTTP 503"):
        local_import.import_selections("2026-08-07", selector=_items, post=post)


def _quote_rows(*_, **__):
    return [
        {"code": "600519", "name": "贵州茅台", "trade_date": "2026-08-06", "open": 1500, "high": 1520, "low": 1490, "close": 1510, "volume": 1000, "amount": 100000, "source": "akshare-sina"},
        {"code": "600519", "name": "贵州茅台", "trade_date": "2026-08-07", "open": 1510, "high": 1530, "low": 1500, "close": 1525, "volume": 1200, "amount": 120000, "source": "akshare-sina"},
    ]


def test_import_quote_history_normalises_and_posts_real_rows(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response(2)

    count = local_import.import_quote_history("2026-08-07", _items(""), history_loader=_quote_rows, post=post)

    assert count == 2
    assert captured["url"] == "https://example.test/api/quotes/import"
    assert captured["json"] == {"quotes": [
        {"stock_code": "600519", "stock_name": "贵州茅台", "trade_date": "2026-08-06", "open": 1500.0, "high": 1520.0, "low": 1490.0, "close": 1510.0, "volume": 1000.0, "amount": 100000.0, "source": "akshare-sina"},
        {"stock_code": "600519", "stock_name": "贵州茅台", "trade_date": "2026-08-07", "open": 1510.0, "high": 1530.0, "low": 1500.0, "close": 1525.0, "volume": 1200.0, "amount": 120000.0, "source": "akshare-sina"},
    ]}


def test_import_quote_history_all_missing_fails_and_partial_missing_continues(monkeypatch, capsys):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")
    items = _items("") + [{"code": "300001", "name": "特锐德", "score": 80, "trade_date": "2026-08-07"}]

    assert local_import.import_quote_history("2026-08-07", items, history_loader=_quote_rows, post=lambda *_args, **_kwargs: _Response(2)) == 2
    assert "300001" in capsys.readouterr().err
    with pytest.raises(local_import.SelectionImportError, match="所有入选股票"):
        local_import.import_quote_history("2026-08-07", _items(""), history_loader=lambda *_args, **_kwargs: [])


def test_quote_import_failure_does_not_leak_token(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    request = httpx.Request("POST", "https://example.test/api/quotes/import")
    response = httpx.Response(503, request=request)

    def post(*_args, **_kwargs):
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)

    with pytest.raises(local_import.SelectionImportError, match="日K导入接口返回 HTTP 503") as error:
        local_import.import_quote_history("2026-08-07", _items(""), history_loader=_quote_rows, post=post)
    assert "secret-not-to-print" not in str(error.value)


def _intraday_payload(*_, **__):
    return {"interval": "30m", "bars": [
        {
            "code": "600519", "name": "贵州茅台", "interval": "30m",
            "datetime": "2026-08-07T10:00:00+08:00", "open": 1500,
            "high": 1520, "low": 1490, "close": 1510, "volume": 1000,
            "amount": 100000, "amount_estimated": False, "source": "akshare-sina",
        },
        {
            "code": "600519", "name": "贵州茅台", "interval": "30m",
            "datetime": "2026-08-07T10:30:00+08:00", "open": 1510,
            "high": 1530, "low": 1500, "close": 1525, "volume": 1200,
            "amount": 120000, "amount_estimated": False, "source": "akshare-sina",
        },
    ]}


def test_import_intraday_quote_history_posts_real_30m_payload(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response(2)

    assert local_import.import_intraday_quote_history(_items(""), payload_builder=_intraday_payload, post=post) == 2
    assert captured["url"] == "https://example.test/api/quotes/intraday/import"
    assert captured["json"] == {"quotes": [
        {
            "stock_code": "600519", "stock_name": "贵州茅台", "interval": "30m",
            "trade_datetime": "2026-08-07T10:00:00+08:00", "open": 1500.0,
            "high": 1520.0, "low": 1490.0, "close": 1510.0, "volume": 1000.0,
            "amount": 100000.0, "amount_estimated": False, "source": "akshare-sina",
        },
        {
            "stock_code": "600519", "stock_name": "贵州茅台", "interval": "30m",
            "trade_datetime": "2026-08-07T10:30:00+08:00", "open": 1510.0,
            "high": 1530.0, "low": 1500.0, "close": 1525.0, "volume": 1200.0,
            "amount": 120000.0, "amount_estimated": False, "source": "akshare-sina",
        },
    ]}
    assert "secret-not-to-print" not in str(captured["json"])


def test_import_intraday_quote_history_rejects_empty_real_bars(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")
    with pytest.raises(local_import.SelectionImportError, match="所有入选股票.*真实30m K"):
        local_import.import_intraday_quote_history(
            _items(""), payload_builder=lambda *_args, **_kwargs: {"interval": "30m", "bars": []},
        )


def test_intraday_import_failure_does_not_leak_token(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    request = httpx.Request("POST", "https://example.test/api/quotes/intraday/import")
    response = httpx.Response(503, request=request)

    def post(*_args, **_kwargs):
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)

    with pytest.raises(local_import.SelectionImportError, match="30m K导入接口返回 HTTP 503") as error:
        local_import.import_intraday_quote_history(_items(""), payload_builder=_intraday_payload, post=post)
    assert "secret-not-to-print" not in str(error.value)


def test_intraday_import_splits_requests_at_api_limit(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")
    items = [
        {"code": f"{600100 + index:06d}", "name": f"股票{index}", "trade_date": "2026-08-07"}
        for index in range(11)
    ]
    base = datetime(2026, 7, 1, 9, 30, tzinfo=timezone(timedelta(hours=8)))
    bars = [
        {
            "code": item["code"], "interval": "30m",
            "datetime": (base + timedelta(minutes=30 * offset)).isoformat(),
            "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100,
            "amount": None, "amount_estimated": True,
        }
        for item in items for offset in range(480)
    ]
    batch_sizes = []

    def post(_url, **kwargs):
        batch_sizes.append(len(kwargs["json"]["quotes"]))
        return _Response(batch_sizes[-1])

    assert local_import.import_intraday_quote_history(
        items, payload_builder=lambda *_args, **_kwargs: {"interval": "30m", "bars": bars}, post=post,
    ) == 5280
    assert batch_sizes == [5000, 280]


def _four_indices():
    rows = []
    for name, symbol, price in (
        ("上证指数", "000001.SH", 3600), ("深证成指", "399001.SZ", 11000),
        ("创业板指", "399006.SZ", 2300), ("科创50", "000688.SH", 1050),
    ):
        available = price is not None
        rows.append({
            "name": name, "symbol": symbol, "available": available,
            "price": price, "change_pct": 1.2 if available else None,
            "observed_at": "2026-08-09T15:05:00+08:00", "source": "akshare-sina",
        })
    return rows


def test_market_snapshot_posts_all_four_and_uses_latest_real_bar_time(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _PayloadResponse({"indices": 4, "stocks": 1})

    assert local_import.import_market_snapshots(
        _items(""), _quote_rows(), index_loader=_four_indices, post=post,
    ) == (4, 1)
    assert captured["url"] == "https://example.test/api/market/snapshots/import"
    assert len(captured["json"]["indices"]) == 4
    assert {row["code"] for row in captured["json"]["indices"]} == {
        "000001.SH", "399001.SZ", "399006.SZ", "000688.SH",
    }
    stock = captured["json"]["stocks"][0]
    assert stock["price"] == 1525.0
    assert stock["observed_at"] == "2026-08-07T15:00:00+08:00"
    assert stock["source"] == "akshare-sina"
    assert "secret-not-to-print" not in str(captured["json"])


def test_market_snapshot_rejects_partial_indices_without_upload(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret")
    with pytest.raises(local_import.SelectionImportError, match="四指数返回不完整"):
        local_import.import_market_snapshots(
            _items(""), _quote_rows(), index_loader=lambda: _four_indices()[:-1],
            post=lambda *_args, **_kwargs: pytest.fail("partial indices must not upload"),
        )


def test_market_snapshot_api_failure_does_not_leak_token(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    request = httpx.Request("POST", "https://example.test/api/market/snapshots/import")
    response = httpx.Response(503, request=request)

    def post(*_args, **_kwargs):
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)

    with pytest.raises(local_import.SelectionImportError, match="市场快照导入接口返回 HTTP 503") as error:
        local_import.import_market_snapshots(_items(""), _quote_rows(), index_loader=_four_indices, post=post)
    assert "secret-not-to-print" not in str(error.value)


def test_official_selector_prices_only_after_old_price_hook_is_disabled(monkeypatch):
    old_filler = local_import.selection_script.fill_missing_selection_prices

    def official_selector(_trade_date):
        return local_import.selection_script.fill_missing_selection_prices(_items(""))

    monkeypatch.setattr(local_import.selection_script, "run_selection", official_selector)
    result = local_import._run_official_selection_with_akshare(
        "2026-08-07",
        price_filler=lambda items: [{**items[0], "price": 1525.0, "price_date": "2026-08-07"}],
    )
    assert result[0]["price"] == 1525.0 and result[0]["price_date"] == "2026-08-07"
    assert local_import.selection_script.fill_missing_selection_prices is old_filler


def test_refresh_existing_weekend_never_selects_or_reimports(monkeypatch, capsys):
    monkeypatch.setattr(local_import, "_load_env_file", lambda _: None)
    monkeypatch.setattr(local_import, "_load_existing_selection_items", lambda date_value: _items(date_value))
    monkeypatch.setattr(local_import, "_sync_selected_market_data", lambda *_: (120, 480, 4, 1))
    monkeypatch.setattr(local_import, "_import_selection_run", lambda *_args, **_kwargs: pytest.fail("refresh must not select"))

    assert local_import.main([
        "--refresh-existing-date", "2026-08-09", "--env-file", "unused.env",
    ]) == 0
    output = capsys.readouterr().out
    assert "trade_date=2026-08-09" in output and "daily_quotes=120" in output


def test_market_sync_reports_components_independently(monkeypatch):
    calls = []
    monkeypatch.setattr(
        local_import, "_load_selected_quote_history",
        lambda *_: (_ for _ in ()).throw(local_import.SelectionImportError("daily unavailable")),
    )

    def intraday(*_args):
        calls.append("intraday")
        raise local_import.SelectionImportError("minute unavailable")

    def snapshots(_items, quotes):
        calls.append(("snapshots", quotes))
        raise local_import.SelectionImportError("indices unavailable")

    monkeypatch.setattr(local_import, "import_intraday_quote_history", intraday)
    monkeypatch.setattr(local_import, "import_market_snapshots", snapshots)
    with pytest.raises(local_import.SelectionImportError) as error:
        local_import._sync_selected_market_data("2026-08-07", _items(""))
    assert calls == ["intraday", ("snapshots", [])]
    assert all(label in str(error.value) for label in ("日K:", "30m K:", "指数/当前价:"))


def test_refresh_powershell_does_not_embed_token_or_modify_daily_task():
    project_root = Path(__file__).resolve().parents[2]
    refresh = (project_root / "scripts" / "refresh-existing-selection-market-data.ps1").read_text(encoding="utf-8")
    installer = (project_root / "scripts" / "install-local-selection-task.ps1").read_text(encoding="utf-8")
    assert "JOB_API_TOKEN" not in refresh
    assert "--refresh-existing-date" in refresh
    assert "refresh-existing-selection-market-data" not in installer
    assert "3:05PM" in installer
