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
    assert captured["headers"]["X-Job-Token"] == "secret-not-to-print"


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
