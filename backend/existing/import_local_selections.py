"""Run the domestic selector and import its results into the Railway API.

This program is deliberately a local-only operational entry point.  It reads
the token from the process environment (or an untracked env file), and never
prints, serialises, or logs it.
"""

from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import sys
from typing import Callable

import httpx

# Keep this executable usable both as ``python existing/...`` and when loaded
# by an isolated test module.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from selection_script import LocalSelectionDataError, run_selection


class SelectionImportError(RuntimeError):
    """A local selection run could not be safely imported."""


def _load_env_file(path: Path) -> None:
    """Load only missing environment values from a simple KEY=VALUE file."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _result_trade_date(items: list[dict]) -> str:
    """Use the actual trading date emitted by the selector for the API row."""
    try:
        result_date = str(items[0]["trade_date"])
        date.fromisoformat(result_date)
    except (KeyError, TypeError, ValueError) as exc:
        raise SelectionImportError("选股结果缺少有效 trade_date") from exc
    if any(str(item.get("trade_date")) != result_date for item in items):
        raise SelectionImportError("选股结果包含不一致的 trade_date")
    return result_date


def _import_selection_run(
    trade_date: str,
    *,
    selector: Callable[[str], list[dict]] = run_selection,
    post: Callable[..., httpx.Response] = httpx.post,
) -> tuple[int, str]:
    """Select locally and submit one import request with its actual trade date."""
    url = os.environ.get("SELECTION_IMPORT_URL", "").strip()
    token = os.environ.get("JOB_API_TOKEN", "").strip()
    if not url:
        raise SelectionImportError("SELECTION_IMPORT_URL 未配置")
    if not token:
        raise SelectionImportError("JOB_API_TOKEN 未配置")

    items = selector(trade_date)
    if not items:
        raise SelectionImportError("本地选股结果为空，已拒绝上传")
    result_date = _result_trade_date(items)

    try:
        response = post(
            url,
            headers={"X-Job-Token": token},
            json={"trade_date": result_date, "items": items},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise SelectionImportError(f"导入接口返回 HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise SelectionImportError(f"请求导入接口失败: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise SelectionImportError("导入接口返回了无效 JSON") from exc

    count = payload.get("data", {}).get("count") if isinstance(payload, dict) else None
    if not isinstance(count, int) or count != len(items):
        raise SelectionImportError("导入接口响应数量与本地结果不一致")
    return count, result_date


def import_selections(
    trade_date: str,
    *,
    selector: Callable[[str], list[dict]] = run_selection,
    post: Callable[..., httpx.Response] = httpx.post,
) -> int:
    """Compatibility wrapper returning only the imported item count."""
    return _import_selection_run(trade_date, selector=selector, post=post)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地选股并导入 Railway")
    parser.add_argument("--trade-date", default=date.today().isoformat(), help="交易日 YYYY-MM-DD（默认今天）")
    parser.add_argument(
        "--env-file",
        default=str(Path(__file__).resolve().parents[2] / ".env"),
        help="可选的本地环境变量文件（默认项目根目录 .env）",
    )
    args = parser.parse_args(argv)
    _load_env_file(Path(args.env_file))
    try:
        count, result_date = _import_selection_run(args.trade_date)
    except (SelectionImportError, LocalSelectionDataError, ValueError) as exc:
        print(f"本地选股导入失败: {exc}", file=sys.stderr)
        return 1
    print(f"本地选股导入成功: trade_date={result_date}, count={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
