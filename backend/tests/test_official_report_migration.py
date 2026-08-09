from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "existing" / "migrate_official_report.py"
SPEC = importlib.util.spec_from_file_location("official_report_migration", SCRIPT_PATH)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class _Response:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._data}


def _report_items() -> list[dict]:
    return [
        {
            "code": f"{600100 + index:06d}", "name": f"官方股票{index}", "score": 90 - index,
            "trade_date": "2026-08-09", "strategy_name": "超短线技术共振",
        }
        for index in range(10)
    ]


def test_migration_parses_then_purges_then_imports_exact_report(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    events: list[str] = []
    captured = {}

    def parse(path, target):
        events.append("parse")
        assert str(path) == r"D:\Program Files\xuangu\result\选股结果2026年08月09日.html"
        assert target == "2026-08-09"
        return _report_items()

    def delete(url, **kwargs):
        events.append("delete")
        captured["delete_url"] = url
        captured["delete_json"] = kwargs["json"]
        return _Response({
            "date": "2026-08-07", "selection_results_deleted": 10,
            "daily_quotes_deleted": 100, "intraday_quotes_deleted": 400,
        })

    def post(url, **kwargs):
        events.append("post")
        captured["post_url"] = url
        captured["post_json"] = kwargs["json"]
        return _Response({"count": 10})

    monkeypatch.setattr(migration, "run_selection_from_report", parse)
    run = migration.migrate_official_report(
        "2026-08-07", r"D:\Program Files\xuangu\result\选股结果2026年08月09日.html", "2026-08-09",
        delete=delete, post=post,
    )

    assert events == ["parse", "delete", "post"]
    assert captured["delete_url"] == "https://example.test/api/data/trade-date"
    assert captured["delete_json"] == {
        "date": "2026-08-07", "delete_selections": True, "delete_daily_quotes": True,
        "delete_intraday_quotes": True, "confirm": True,
    }
    assert captured["post_url"] == "https://example.test/api/selections/import"
    assert captured["post_json"]["trade_date"] == "2026-08-09"
    assert len(captured["post_json"]["items"]) == 10
    assert run.count == 10 and run.trade_date == "2026-08-09"
    assert "secret-not-to-print" not in str(captured)


def test_migration_parse_or_date_failure_never_purges_or_imports(monkeypatch):
    calls: list[str] = []

    def parse(*_args):
        calls.append("parse")
        raise migration.LocalSelectionDataError("报告日期不一致")

    monkeypatch.setattr(migration, "run_selection_from_report", parse)
    with pytest.raises(migration.LocalSelectionDataError, match="日期不一致"):
        migration.migrate_official_report(
            "2026-08-07", "missing-or-invalid.html", "2026-08-09",
            delete=lambda *_args, **_kwargs: calls.append("delete"),
            post=lambda *_args, **_kwargs: calls.append("post"),
        )
    assert calls == ["parse"]


def test_migration_cleanup_failure_never_imports_or_leaks_token(monkeypatch):
    monkeypatch.setenv("SELECTION_IMPORT_URL", "https://example.test/api/selections/import")
    monkeypatch.setenv("JOB_API_TOKEN", "secret-not-to-print")
    monkeypatch.setattr(migration, "run_selection_from_report", lambda *_args: _report_items())
    request = httpx.Request("DELETE", "https://example.test/api/data/trade-date")
    response = httpx.Response(503, request=request)
    imported = False

    def delete(*_args, **_kwargs):
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)

    def post(*_args, **_kwargs):
        nonlocal imported
        imported = True
        return _Response({"count": 10})

    with pytest.raises(migration.OfficialReportMigrationError, match="清理接口返回 HTTP 503") as error:
        migration.migrate_official_report("2026-08-07", "report.html", "2026-08-09", delete=delete, post=post)
    assert imported is False
    assert "secret-not-to-print" not in str(error.value)


def test_migration_main_requires_explicit_purge_confirmation(monkeypatch, capsys):
    monkeypatch.setattr(migration.importer, "_load_env_file", lambda *_: pytest.fail("must not load env"))
    assert migration.main([
        "--delete-trade-date", "2026-08-07", "--report-path", "report.html", "--target-trade-date", "2026-08-09",
    ]) == 2
    assert "--confirm-purge" in capsys.readouterr().err
