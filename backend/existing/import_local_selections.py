"""Run the domestic selector and import its results into the Railway API.

This program is deliberately a local-only operational entry point.  It reads
the token from the process environment (or an untracked env file), and never
prints, serialises, or logs it.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from math import isfinite
import os
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

# Keep this executable usable both as ``python existing/...`` and when loaded
# by an isolated test module.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from selection_script import LocalSelectionDataError, run_selection
from app.data import market_data


class SelectionImportError(RuntimeError):
    """A local selection run could not be safely imported."""


class SelectionImportRun:
    """Selection import result retained for the follow-up K-line upload."""

    def __init__(self, count: int, trade_date: str, items: list[dict]) -> None:
        self.count = count
        self.trade_date = trade_date
        self.items = items


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


def _normalise_selection_items(items: list[dict]) -> list[dict]:
    """Preserve authoritative report metrics under the public API field names."""
    normalised: list[dict] = []
    for item in items:
        row = dict(item)
        # The official HTML labels the metric ``turnover``; the import API and
        # persisted signals contract call the same metric ``turnover_rate``.
        if row.get("turnover_rate") is None and row.get("turnover") is not None:
            row["turnover_rate"] = row["turnover"]
        normalised.append(row)
    return normalised


def _api_config() -> tuple[str, str]:
    url = os.environ.get("SELECTION_IMPORT_URL", "").strip()
    token = os.environ.get("JOB_API_TOKEN", "").strip()
    if not url:
        raise SelectionImportError("SELECTION_IMPORT_URL 未配置")
    if not token:
        raise SelectionImportError("JOB_API_TOKEN 未配置")
    return url, token


def _sibling_api_url(selection_url: str, path: str) -> str:
    """Derive a same-origin API endpoint without adding another secret setting."""
    parsed = urlsplit(selection_url)
    if not parsed.scheme or not parsed.netloc or parsed.path.rstrip("/") != "/api/selections/import":
        raise SelectionImportError("SELECTION_IMPORT_URL 必须指向 /api/selections/import")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _quote_import_url(selection_url: str) -> str:
    return _sibling_api_url(selection_url, "/api/quotes/import")


def _intraday_quote_import_url(selection_url: str) -> str:
    return _sibling_api_url(selection_url, "/api/quotes/intraday/import")


def _import_selection_run(
    trade_date: str,
    *,
    replace_existing: bool = False,
    selector: Callable[[str], list[dict]] = run_selection,
    post: Callable[..., httpx.Response] = httpx.post,
) -> SelectionImportRun:
    """Select locally and submit one import request with its actual trade date."""
    url, token = _api_config()

    items = _normalise_selection_items(selector(trade_date))
    if not items:
        raise SelectionImportError("本地选股结果为空，已拒绝上传")
    result_date = _result_trade_date(items)

    try:
        request_body = {"trade_date": result_date, "items": items}
        if replace_existing:
            request_body["replace_existing"] = True
        response = post(
            url,
            headers={"X-Job-Token": token},
            json=request_body,
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
    return SelectionImportRun(count=count, trade_date=result_date, items=items)


def import_selections(
    trade_date: str,
    *,
    replace_existing: bool = False,
    selector: Callable[[str], list[dict]] = run_selection,
    post: Callable[..., httpx.Response] = httpx.post,
) -> int:
    """Compatibility wrapper returning only the imported item count."""
    return _import_selection_run(
        trade_date, replace_existing=replace_existing, selector=selector, post=post,
    ).count


def _normalise_quote_rows(
    rows: list[dict], selected: dict[str, str], target_date: str,
) -> tuple[list[dict], list[str]]:
    """Convert data-layer rows into the strict quote-import contract."""
    cleaned: dict[tuple[str, str], dict] = {}
    for row in rows:
        code = str(row.get("code") or row.get("stock_code") or "").zfill(6)
        if code not in selected:
            continue
        try:
            row_date = date.fromisoformat(str(row.get("trade_date", ""))[:10]).isoformat()
            if row_date > target_date:
                continue
            values = {field: float(row[field]) for field in ("open", "high", "low", "close", "volume")}
        except (KeyError, TypeError, ValueError):
            continue
        if not all(isfinite(value) and value >= 0 for value in values.values()) or values["high"] < values["low"]:
            continue
        cleaned[(code, row_date)] = {
            "stock_code": code,
            "stock_name": str(row.get("name") or row.get("stock_name") or selected[code]),
            "trade_date": row_date,
            **values,
        }
    missing = sorted(code for code in selected if not any(key[0] == code for key in cleaned))
    return sorted(cleaned.values(), key=lambda quote: (quote["stock_code"], quote["trade_date"])), missing


def _load_selected_quote_history(
    trade_date: str,
    items: list[dict],
    *,
    history_loader: Callable[..., list[dict]] = market_data.sync_quote_history,
) -> list[dict]:
    selected = {
        str(item.get("code") or item.get("stock_code") or "").zfill(6): str(item.get("name") or item.get("stock_name") or "未命名股票")
        for item in items
    }
    selected.pop("000000", None)
    if not selected:
        raise SelectionImportError("选股结果缺少可上传日K的股票代码")
    per_stock_limit = min(120, max(1, 5000 // len(selected)))
    universe = [{"code": code, "name": name} for code, name in selected.items()]
    try:
        raw_rows = history_loader(trade_date, limit=per_stock_limit, universe=universe)
    except market_data.MarketDataError as exc:
        raise SelectionImportError(f"日K行情读取失败: {exc}") from exc
    except Exception as exc:
        raise SelectionImportError(f"日K行情读取出现意外错误: {type(exc).__name__}: {exc}") from exc
    quotes, missing = _normalise_quote_rows(raw_rows, selected, trade_date)
    if missing:
        print(f"本地日K缺失，跳过: {','.join(missing)}", file=sys.stderr)
    if not quotes:
        raise SelectionImportError("所有入选股票均无可上传的真实日K")
    return quotes


def import_quote_history(
    trade_date: str,
    items: list[dict],
    *,
    history_loader: Callable[..., list[dict]] = market_data.sync_quote_history,
    post: Callable[..., httpx.Response] = httpx.post,
) -> int:
    """Upload up to 120 real daily bars per selected stock after selection succeeds."""
    selection_url, token = _api_config()
    quotes = _load_selected_quote_history(trade_date, items, history_loader=history_loader)
    try:
        response = post(
            _quote_import_url(selection_url),
            headers={"X-Job-Token": token},
            json={"quotes": quotes},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise SelectionImportError(f"日K导入接口返回 HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise SelectionImportError(f"请求日K导入接口失败: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise SelectionImportError("日K导入接口返回了无效 JSON") from exc
    count = payload.get("data", {}).get("count") if isinstance(payload, dict) else None
    if not isinstance(count, int) or count != len(quotes):
        raise SelectionImportError("日K导入接口响应数量与本地数据不一致")
    return count


def _normalise_intraday_quote_rows(rows: list[dict], selected: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Keep only valid real 30-minute bars for the official selected codes."""
    per_stock: dict[str, list[dict]] = {code: [] for code in selected}
    for row in rows:
        code = str(row.get("code") or row.get("stock_code") or "").zfill(6)
        if code not in per_stock or row.get("interval") != "30m":
            continue
        try:
            trade_datetime = datetime.fromisoformat(str(row.get("datetime") or row.get("trade_datetime") or ""))
            values = {field: float(row[field]) for field in ("open", "high", "low", "close", "volume")}
            amount = row.get("amount")
            if amount is not None:
                amount = float(amount)
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not all(isfinite(value) and value >= 0 for value in values.values())
            or (amount is not None and (not isfinite(amount) or amount < 0))
            or values["high"] < values["low"]
        ):
            continue
        per_stock[code].append({
            "stock_code": code,
            "stock_name": str(row.get("name") or row.get("stock_name") or selected[code]),
            "interval": "30m",
            "trade_datetime": trade_datetime.isoformat(),
            **values,
            "amount": amount,
            "amount_estimated": bool(row.get("amount_estimated", row.get("estimated", False))),
        })

    cleaned: list[dict] = []
    missing: list[str] = []
    for code, bars in per_stock.items():
        # The data-layer contract already limits Tencent rows, while this second
        # guard preserves the operational per-stock cap if that contract changes.
        unique = {str(bar["trade_datetime"]): bar for bar in bars}
        retained = [unique[key] for key in sorted(unique)[-480:]]
        if not retained:
            missing.append(code)
        cleaned.extend(retained)
    return cleaned, missing


def _load_selected_intraday_history(
    items: list[dict],
    *,
    payload_builder: Callable[..., dict] = market_data.build_selected_30m_sync_payload,
) -> list[dict]:
    selected = {
        str(item.get("code") or item.get("stock_code") or "").zfill(6): str(item.get("name") or item.get("stock_name") or "未命名股票")
        for item in items
    }
    selected.pop("000000", None)
    if not selected:
        raise SelectionImportError("选股结果缺少可上传30m K的股票代码")
    try:
        payload = payload_builder(items, limit=480)
    except market_data.MarketDataError as exc:
        raise SelectionImportError(f"30m K行情读取失败: {exc}") from exc
    except Exception as exc:
        raise SelectionImportError(f"30m K行情读取出现意外错误: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("interval") != "30m" or not isinstance(payload.get("bars"), list):
        raise SelectionImportError("30m K行情返回格式无效")
    quotes, missing = _normalise_intraday_quote_rows(payload["bars"], selected)
    if missing:
        print(f"本地30m K缺失，跳过: {','.join(missing)}", file=sys.stderr)
    if not quotes:
        raise SelectionImportError("所有入选股票均无可上传的真实30m K")
    return quotes


def import_intraday_quote_history(
    items: list[dict],
    *,
    payload_builder: Callable[..., dict] = market_data.build_selected_30m_sync_payload,
    post: Callable[..., httpx.Response] = httpx.post,
) -> int:
    """Upload real 30-minute bars in API-safe batches after daily K succeeds."""
    selection_url, token = _api_config()
    quotes = _load_selected_intraday_history(items, payload_builder=payload_builder)
    imported = 0
    try:
        for offset in range(0, len(quotes), 5000):
            batch = quotes[offset:offset + 5000]
            response = post(
                _intraday_quote_import_url(selection_url),
                headers={"X-Job-Token": token},
                json={"quotes": batch},
                timeout=60.0,
            )
            response.raise_for_status()
            payload = response.json()
            count = payload.get("data", {}).get("count") if isinstance(payload, dict) else None
            if not isinstance(count, int) or count != len(batch):
                raise SelectionImportError("30m K导入接口响应数量与本地数据不一致")
            imported += count
    except httpx.HTTPStatusError as exc:
        raise SelectionImportError(f"30m K导入接口返回 HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise SelectionImportError(f"请求30m K导入接口失败: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise SelectionImportError("30m K导入接口返回了无效 JSON") from exc
    return imported


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地选股并导入 Railway")
    parser.add_argument("--trade-date", default=date.today().isoformat(), help="交易日 YYYY-MM-DD（默认今天）")
    parser.add_argument(
        "--replace-existing", action="store_true",
        help="人工确认后替换同一实际交易日、同一策略的旧快照（默认关闭）",
    )
    parser.add_argument(
        "--env-file",
        default=str(Path(__file__).resolve().parents[2] / ".env"),
        help="可选的本地环境变量文件（默认项目根目录 .env）",
    )
    args = parser.parse_args(argv)
    _load_env_file(Path(args.env_file))
    try:
        requested_date = date.fromisoformat(args.trade_date)
        if requested_date.weekday() >= 5:
            print(f"非交易日，跳过本地选股与上传: {requested_date.isoformat()}")
            return 0
        selection_run = _import_selection_run(args.trade_date, replace_existing=args.replace_existing)
        quote_count = import_quote_history(selection_run.trade_date, selection_run.items)
        intraday_quote_count = import_intraday_quote_history(selection_run.items)
    except (SelectionImportError, LocalSelectionDataError, ValueError) as exc:
        print(f"本地选股导入失败: {exc}", file=sys.stderr)
        return 1
    print(
        "本地选股与K线导入成功: "
        f"trade_date={selection_run.trade_date}, selections={selection_run.count}, "
        f"daily_quotes={quote_count}, intraday_30m_quotes={intraday_quote_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
