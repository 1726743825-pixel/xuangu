from __future__ import annotations

import importlib.util
from pathlib import Path
import re

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "existing" / "selection_script.py"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "official_screener_report.html"
CHAODIE_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "chaodie_report.html"
OFFICIAL_REPORT_PATH = Path(r"D:\Program Files\xuangu\zhuizhang\result\选股结果2026年08月09日.html")
SPEC = importlib.util.spec_from_file_location("local_selection_script", SCRIPT_PATH)
assert SPEC and SPEC.loader
selection_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection_script)


def test_parse_official_report_preserves_authoritative_fields(monkeypatch):
    monkeypatch.setattr(selection_script, "fill_missing_selection_prices", lambda items: items)
    items = selection_script.run_selection_from_report(FIXTURE_PATH, "2026-08-09")

    assert len(items) == 2
    first = items[0]
    assert first["code"] == "301080"
    assert first["name"] == "百普赛斯"
    assert first["industry"] == "生物制品 | 独家药品 | 医疗器械概念"
    assert first["trade_date"] == "2026-08-09"
    assert first["strategy_name"] == "追涨"
    assert first["score"] == 87.0
    assert first["price"] is None
    assert first["change_pct"] == 20.0
    assert first["turnover"] == 11.7
    assert first["board_count"] == 1
    assert first["indicators"]["official_details"].startswith("MA5开口")


def test_parse_official_report_only_applies_price_enricher(monkeypatch):
    seen = []

    def enrich(items):
        seen.extend(items)
        return [{**item, "price": 123.45} for item in items]

    monkeypatch.setattr(selection_script, "fill_missing_selection_prices", enrich)

    items = selection_script.parse_official_report(FIXTURE_PATH)

    assert [item["code"] for item in items] == ["301080", "600267"]
    assert [item["score"] for item in items] == [87.0, 85.0]
    assert [item["price"] for item in items] == [123.45, 123.45]
    assert [item["price"] for item in seen] == [None, None]


def _expanded_report(tmp_path: Path, fixture: Path, prefix: str, count: int) -> Path:
    html = fixture.read_text(encoding="utf-8")
    rows = re.findall(r"<tr>.*?</tr>", html, flags=re.S)
    assert len(rows) >= 2
    template = rows[1]
    generated = []
    for index in range(count):
        code = f"{int(prefix) + index:06d}"
        row = re.sub(r"<td>1</td>", f"<td>{index + 1}</td>", template, count=1)
        row = re.sub(r">\d{6}<", f">{code}<", row, count=1)
        generated.append(row)
    expanded = re.sub(
        r"(<tr>.*?</tr>)(?:\s*<tr>.*?</tr>)+",
        lambda match: match.group(1) + "\n" + "\n".join(generated),
        html,
        count=1,
        flags=re.S,
    )
    path = tmp_path / fixture.name
    path.write_text(expanded, encoding="utf-8")
    return path


def test_parse_official_report_imports_only_top_ten(monkeypatch, tmp_path):
    monkeypatch.setattr(selection_script, "fill_missing_selection_prices", lambda items: items)
    report = _expanded_report(tmp_path, FIXTURE_PATH, "300100", 12)

    items = selection_script.parse_official_report(report)

    assert len(items) == 10
    assert items[0]["code"] == "300100"
    assert items[-1]["code"] == "300109"


def test_parse_chaodie_report_normalises_130_point_score():
    items = selection_script.parse_chaodie_report(CHAODIE_FIXTURE_PATH, "2026-08-11")

    assert len(items) == 2
    first = items[0]
    assert first["code"] == "301489"
    assert first["name"] == "思泉新材"
    assert first["industry"] == "电子化学品Ⅱ"
    assert first["trade_date"] == "2026-08-11"
    assert first["strategy_name"] == "超跌"
    assert first["score"] == round(71.7 / 130 * 100, 6)
    assert first["price"] == 99.02
    assert first["change_pct"] == -3.4
    assert first["indicators"]["raw_score"] == 71.7
    assert first["indicators"]["raw_score_max"] == 130
    assert first["indicators"]["official_details"].startswith("财务")


def test_parse_chaodie_report_imports_only_top_ten(tmp_path):
    report = _expanded_report(tmp_path, CHAODIE_FIXTURE_PATH, "301400", 12)

    items = selection_script.parse_chaodie_report(report, "2026-08-11")

    assert len(items) == 10
    assert all(item["strategy_name"] == "超跌" for item in items)


def test_parse_official_report_rejects_reports_without_rows(tmp_path):
    report = tmp_path / "选股结果2026年08月09日.html"
    report.write_text("<div>生成时间：2026-08-09 15:00:00</div>", encoding="utf-8")

    with pytest.raises(selection_script.LocalSelectionDataError, match="未包含可导入"):
        selection_script.parse_official_report(report)


def test_specified_report_rejects_missing_file_and_date_mismatch(monkeypatch):
    monkeypatch.setattr(selection_script, "fill_missing_selection_prices", lambda items: items)
    with pytest.raises(selection_script.LocalSelectionDataError, match="不存在"):
        selection_script.run_selection_from_report("missing.html", "2026-08-09")
    with pytest.raises(selection_script.LocalSelectionDataError, match="不一致"):
        selection_script.run_selection_from_report(FIXTURE_PATH, "2026-08-08")


def test_weekend_without_explicit_report_never_starts_node(monkeypatch):
    monkeypatch.setattr(selection_script.subprocess, "run", lambda *args, **kwargs: pytest.fail("weekend must skip node"))
    with pytest.raises(selection_script.LocalSelectionDataError, match="非交易日"):
        selection_script.run_selection("2026-08-09")


@pytest.mark.skipif(not OFFICIAL_REPORT_PATH.is_file(), reason="D 盘官方报告仅存在于本地执行主机")
def test_current_d_drive_report_has_ten_importable_items(monkeypatch):
    monkeypatch.setattr(selection_script, "fill_missing_selection_prices", lambda items: items)

    items = selection_script.run_selection_from_report(OFFICIAL_REPORT_PATH, "2026-08-09")

    assert len(items) == 10
    assert {item["trade_date"] for item in items} == {"2026-08-09"}
