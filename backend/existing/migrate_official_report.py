"""One-time, confirmed migration of an explicit official HTML report.

This is intentionally separate from the daily scheduled importer.  It parses a
named report before deleting anything, then imports only its authoritative
selection rows.  It never runs Node.js and never synthesises K-line data.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys
from typing import Callable

import httpx

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import import_local_selections as importer
from selection_script import LocalSelectionDataError, run_selection_from_report


class OfficialReportMigrationError(RuntimeError):
    """A confirmed one-time report migration could not complete safely."""


def _cleanup_url(selection_url: str) -> str:
    return importer._sibling_api_url(selection_url, "/api/data/trade-date")


def _parse_report(report_path: str | Path, target_trade_date: str) -> list[dict]:
    """Strictly parse the report before any destructive network operation."""
    try:
        target = date.fromisoformat(target_trade_date).isoformat()
    except ValueError as exc:
        raise OfficialReportMigrationError("目标交易日格式必须为 YYYY-MM-DD") from exc
    items = run_selection_from_report(report_path, target)
    actual_date = importer._result_trade_date(items)
    if actual_date != target:
        raise OfficialReportMigrationError("官方报告日期与目标交易日不一致")
    if len(items) != 10:
        raise OfficialReportMigrationError(f"官方报告必须恰好包含 10 条可导入结果，当前为 {len(items)} 条")
    return items


def _purge_trade_date(
    delete_trade_date: str,
    *,
    delete: Callable[..., httpx.Response] = httpx.delete,
) -> dict:
    """Delete one fully-confirmed date after the report has parsed successfully."""
    try:
        target = date.fromisoformat(delete_trade_date).isoformat()
    except ValueError as exc:
        raise OfficialReportMigrationError("清理日期格式必须为 YYYY-MM-DD") from exc
    selection_url, token = importer._api_config()
    request_body = {
        "date": target,
        "delete_selections": True,
        "delete_daily_quotes": True,
        "delete_intraday_quotes": True,
        "confirm": True,
    }
    try:
        response = delete(
            _cleanup_url(selection_url),
            headers={"X-Job-Token": token},
            json=request_body,
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise OfficialReportMigrationError(f"清理接口返回 HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise OfficialReportMigrationError(f"请求清理接口失败: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise OfficialReportMigrationError("清理接口返回了无效 JSON") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or str(data.get("date")) != target:
        raise OfficialReportMigrationError("清理接口响应与请求日期不一致")
    return data


def migrate_official_report(
    delete_trade_date: str,
    report_path: str | Path,
    target_trade_date: str,
    *,
    delete: Callable[..., httpx.Response] = httpx.delete,
    post: Callable[..., httpx.Response] = httpx.post,
) -> importer.SelectionImportRun:
    """Parse → purge → import, preserving that order even on a weekend report."""
    if delete_trade_date == target_trade_date:
        raise OfficialReportMigrationError("清理日期不能与目标交易日相同")
    items = _parse_report(report_path, target_trade_date)
    _purge_trade_date(delete_trade_date, delete=delete)
    try:
        return importer._import_selection_run(
            target_trade_date,
            selector=lambda _trade_date: items,
            post=post,
        )
    except importer.SelectionImportError as exc:
        raise OfficialReportMigrationError(f"选股导入失败: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="一次性清理旧日期并导入指定官方 HTML 报告")
    parser.add_argument("--delete-trade-date", required=True, help="明确清理的 YYYY-MM-DD")
    parser.add_argument("--report-path", required=True, help="指定官方 HTML 报告路径（仅读取，不运行 Node.js）")
    parser.add_argument("--target-trade-date", required=True, help="报告对应的 YYYY-MM-DD")
    parser.add_argument("--confirm-purge", action="store_true", help="确认删除该日期的选股、日K与30分钟K")
    parser.add_argument(
        "--env-file",
        default=str(Path(__file__).resolve().parents[2] / ".env"),
        help="可选的本地环境变量文件（默认项目根目录 .env）",
    )
    args = parser.parse_args(argv)
    if not args.confirm_purge:
        print("拒绝执行：必须显式传入 --confirm-purge", file=sys.stderr)
        return 2
    importer._load_env_file(Path(args.env_file))
    try:
        run = migrate_official_report(args.delete_trade_date, args.report_path, args.target_trade_date)
    except (OfficialReportMigrationError, LocalSelectionDataError, ValueError) as exc:
        print(f"一次性报告迁移失败: {exc}", file=sys.stderr)
        return 1
    print(
        "一次性报告迁移成功: "
        f"purged_trade_date={args.delete_trade_date}, target_trade_date={run.trade_date}, selections={run.count}; "
        "本工具不上传日K或30m K"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
