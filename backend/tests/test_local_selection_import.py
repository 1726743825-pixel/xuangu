from __future__ import annotations

import importlib.util
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
    monkeypatch.setattr(local_import, "import_quote_history", lambda *_: 120)

    assert local_import.main(["--trade-date", "2026-08-07", "--env-file", "unused.env"]) == 0
    assert "trade_date=2026-08-07, selections=10, quotes=120" in capsys.readouterr().out


def test_main_passes_replace_flag_only_when_requested(monkeypatch):
    monkeypatch.setattr(local_import, "_load_env_file", lambda _: None)
    captured = {}

    def selection_run(*_args, **kwargs):
        captured.update(kwargs)
        return local_import.SelectionImportRun(1, "2026-08-07", _items(""))

    monkeypatch.setattr(local_import, "_import_selection_run", selection_run)
    monkeypatch.setattr(local_import, "import_quote_history", lambda *_: 1)
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
        {"code": "600519", "name": "贵州茅台", "trade_date": "2026-08-06", "open": 1500, "high": 1520, "low": 1490, "close": 1510, "volume": 1000},
        {"code": "600519", "name": "贵州茅台", "trade_date": "2026-08-07", "open": 1510, "high": 1530, "low": 1500, "close": 1525, "volume": 1200},
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
        {"stock_code": "600519", "stock_name": "贵州茅台", "trade_date": "2026-08-06", "open": 1500.0, "high": 1520.0, "low": 1490.0, "close": 1510.0, "volume": 1000.0},
        {"stock_code": "600519", "stock_name": "贵州茅台", "trade_date": "2026-08-07", "open": 1510.0, "high": 1530.0, "low": 1500.0, "close": 1525.0, "volume": 1200.0},
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
