from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "existing" / "selection_script.py"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "official_screener_report.html"
SPEC = importlib.util.spec_from_file_location("local_selection_script", SCRIPT_PATH)
assert SPEC and SPEC.loader
selection_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection_script)


def test_parse_official_report_preserves_authoritative_fields():
    items = selection_script.parse_official_report(FIXTURE_PATH)

    assert len(items) == 2
    first = items[0]
    assert first["code"] == "301080"
    assert first["name"] == "百普赛斯"
    assert first["industry"] == "生物制品"
    assert first["trade_date"] == "2026-08-09"
    assert first["strategy_name"] == "超短线技术共振"
    assert first["score"] == 87.0
    assert first["price"] is None
    assert first["change_pct"] == 20.0
    assert first["turnover"] == 11.7
    assert first["board_count"] == 1
    assert first["indicators"]["official_details"].startswith("MA5开口")


def test_parse_official_report_rejects_reports_without_rows(tmp_path):
    report = tmp_path / "选股结果2026年08月09日.html"
    report.write_text("<div>生成时间：2026-08-09 15:00:00</div>", encoding="utf-8")

    with pytest.raises(selection_script.LocalSelectionDataError, match="未包含可导入"):
        selection_script.parse_official_report(report)
