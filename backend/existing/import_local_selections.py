"""Run the domestic selector and import its results into the Railway API.

This program is deliberately a local-only operational entry point.  It reads
the token from the process environment (or an untracked env file), and never
prints, serialises, or logs it.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from math import isfinite
import os
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

# Keep this executable usable both as ``python existing/...`` and when loaded
# by an isolated test module.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import selection_script
from selection_script import LocalSelectionDataError
from app.data import akshare_local, market_data


SHANGHAI = ZoneInfo("Asia/Shanghai")


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
        if row.get("selection_price") is None and row.get("price") is not None:
            row["selection_price"] = row["price"]
        if row.get("selection_price_date") is None and row.get("price_date") is not None:
            row["selection_price_date"] = row["price_date"]
        normalised.append(row)
    return normalised


def _run_official_selection_with_akshare(
    trade_date: str,
    *,
    official_selector: Callable[[str], list[dict]] | None = None,
    price_filler: Callable[..., list[dict]] = akshare_local.fill_selection_prices,
) -> list[dict]:
    """Run the official selector, then attach only AKShare-backed fixed prices."""
    if official_selector is not None:
        items = official_selector(trade_date)
    else:
        # selection_script historically enriched missing prices through the old
        # multi-source layer.  Disable only that runtime hook so the official
        # candidates remain untouched and AKShare becomes the price authority.
        old_filler = selection_script.fill_missing_selection_prices
        selection_script.fill_missing_selection_prices = lambda rows: rows
        try:
            items = selection_script.run_selection(trade_date)
        finally:
            selection_script.fill_missing_selection_prices = old_filler
    return price_filler(items)


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


def _market_snapshot_import_url(selection_url: str) -> str:
    return _sibling_api_url(selection_url, "/api/market/snapshots/import")


def _import_selection_run(
    trade_date: str,
    *,
    replace_existing: bool = False,
    selector: Callable[[str], list[dict]] = _run_official_selection_with_akshare,
    post: Callable[..., httpx.Response] = httpx.post,
) -> SelectionImportRun:
    """Select locally and submit one import request with its actual trade date."""
    url, token = _api_config()

    items = _normalise_selection_items(selector(trade_date))
    if not items:
        raise SelectionImportError("本地选股结果为空，已拒绝上传")
    result_date = _result_trade_date(items)

    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(str(item.get("strategy_name") or "默认策略"), []).append(item)

    imported_count = 0
    for strategy_name, strategy_items in grouped.items():
        try:
            request_body = {"trade_date": result_date, "items": strategy_items}
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
            raise SelectionImportError(f"{strategy_name}导入接口返回 HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise SelectionImportError(f"{strategy_name}请求导入接口失败: {type(exc).__name__}") from exc
        except ValueError as exc:
            raise SelectionImportError(f"{strategy_name}导入接口返回了无效 JSON") from exc

        count = payload.get("data", {}).get("count") if isinstance(payload, dict) else None
        if not isinstance(count, int) or count != len(strategy_items):
            raise SelectionImportError(f"{strategy_name}导入接口响应数量与本地结果不一致")
        imported_count += count
    return SelectionImportRun(count=imported_count, trade_date=result_date, items=items)


def import_selections(
    trade_date: str,
    *,
    replace_existing: bool = False,
    selector: Callable[[str], list[dict]] = _run_official_selection_with_akshare,
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
            amount = row.get("amount")
            if amount is not None:
                amount = float(amount)
        except (KeyError, TypeError, ValueError):
            continue
        prices = [values[field] for field in ("open", "high", "low", "close")]
        if (
            not all(isfinite(value) and value >= 0 for value in values.values())
            or not all(value > 0 for value in prices)
            or (amount is not None and (not isfinite(amount) or amount < 0))
            or values["high"] < max(prices)
            or values["low"] > min(prices)
        ):
            continue
        cleaned[(code, row_date)] = {
            "stock_code": code,
            "stock_name": str(row.get("name") or row.get("stock_name") or selected[code]),
            "trade_date": row_date,
            **values,
            "amount": amount,
            "source": row.get("source"),
        }
    missing = sorted(code for code in selected if not any(key[0] == code for key in cleaned))
    return sorted(cleaned.values(), key=lambda quote: (quote["stock_code"], quote["trade_date"])), missing


def _akshare_daily_history(
    trade_date: str,
    *,
    limit: int,
    universe: list[dict],
    daily_loader: Callable[..., list[dict]] = akshare_local.fetch_daily_bars,
) -> list[dict]:
    """Load bounded real AKShare/Sina daily history for selected codes only."""
    target = date.fromisoformat(trade_date)
    start = (target - timedelta(days=max(90, limit * 2 + 30))).isoformat()
    output: list[dict] = []
    for stock in universe:
        code = str(stock["code"]).zfill(6)
        try:
            bars = daily_loader(code, start_date=start, end_date=target.isoformat())
        except akshare_local.AkshareDataError as exc:
            print(f"AKShare 日K读取失败，跳过 {code}: {exc}", file=sys.stderr)
            continue
        for bar in bars[-limit:]:
            output.append({**bar, "name": stock["name"]})
    return output


def _load_selected_quote_history(
    trade_date: str,
    items: list[dict],
    *,
    history_loader: Callable[..., list[dict]] = _akshare_daily_history,
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
    except (akshare_local.AkshareDataError, market_data.MarketDataError) as exc:
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
    history_loader: Callable[..., list[dict]] = _akshare_daily_history,
    post: Callable[..., httpx.Response] = httpx.post,
) -> int:
    """Upload up to 120 real daily bars per selected stock after selection succeeds."""
    quotes = _load_selected_quote_history(trade_date, items, history_loader=history_loader)
    return _upload_quote_rows(quotes, post=post)


def _upload_quote_rows(
    quotes: list[dict], *, post: Callable[..., httpx.Response] = httpx.post,
) -> int:
    selection_url, token = _api_config()
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
        prices = [values[field] for field in ("open", "high", "low", "close")]
        if (
            not all(isfinite(value) and value >= 0 for value in values.values())
            or not all(value > 0 for value in prices)
            or (amount is not None and (not isfinite(amount) or amount < 0))
            or values["high"] < max(prices)
            or values["low"] > min(prices)
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
            "source": row.get("source"),
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


def _build_akshare_intraday_payload(
    items: list[dict],
    *,
    limit: int = 480,
    minute_loader: Callable[..., list[dict]] = akshare_local.fetch_30m_bars,
) -> dict:
    """Build selected-stock 30m payload from AKShare/Sina only."""
    bars: list[dict] = []
    seen: set[str] = set()
    for item in items:
        code = str(item.get("code") or item.get("stock_code") or "").zfill(6)
        if code == "000000" or code in seen:
            continue
        seen.add(code)
        try:
            rows = minute_loader(code, limit=limit)
        except akshare_local.AkshareDataError as exc:
            print(f"AKShare 30m K读取失败，跳过 {code}: {exc}", file=sys.stderr)
            continue
        name = str(item.get("name") or item.get("stock_name") or "未命名股票")
        bars.extend({**row, "name": name} for row in rows)
    return {"interval": "30m", "bars": bars}


def _load_selected_intraday_history(
    items: list[dict],
    *,
    payload_builder: Callable[..., dict] = _build_akshare_intraday_payload,
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
    except (akshare_local.AkshareDataError, market_data.MarketDataError) as exc:
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
    payload_builder: Callable[..., dict] = _build_akshare_intraday_payload,
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


def _stock_snapshots_from_daily_quotes(
    items: list[dict], quotes: list[dict],
) -> tuple[list[dict], list[str]]:
    """Build current snapshots from the latest real daily bar, never wall time."""
    names = {
        str(item.get("code") or item.get("stock_code") or "").zfill(6):
        str(item.get("name") or item.get("stock_name") or "未命名股票")
        for item in items
    }
    grouped: dict[str, list[dict]] = {code: [] for code in names if code != "000000"}
    for quote in quotes:
        code = str(quote.get("stock_code") or quote.get("code") or "").zfill(6)
        if code in grouped:
            grouped[code].append(quote)
    snapshots: list[dict] = []
    missing: list[str] = []
    for code, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: str(row.get("trade_date", "")))
        if len(ordered) < 2:
            missing.append(code)
            continue
        latest, previous = ordered[-1], ordered[-2]
        source = str(latest.get("source") or "")
        try:
            latest_date = date.fromisoformat(str(latest["trade_date"])[:10])
            close = float(latest["close"])
            previous_close = float(previous["close"])
        except (KeyError, TypeError, ValueError):
            missing.append(code)
            continue
        if not source.startswith("akshare-") or close <= 0 or previous_close <= 0:
            missing.append(code)
            continue
        observed_at = datetime.combine(latest_date, time(15, 0), tzinfo=SHANGHAI).isoformat()
        snapshots.append({
            "code": code,
            "name": names[code],
            "price": close,
            "change_pct": round((close / previous_close - 1) * 100, 6),
            "observed_at": observed_at,
            "source": source,
        })
    return snapshots, sorted(missing)


def import_market_snapshots(
    items: list[dict],
    daily_quotes: list[dict],
    *,
    index_loader: Callable[..., list[dict]] = akshare_local.fetch_market_indices,
    post: Callable[..., httpx.Response] = httpx.post,
) -> tuple[int, int]:
    """Atomically submit all four indices plus available selected-stock closes."""
    selection_url, token = _api_config()
    try:
        raw_indices = index_loader()
    except akshare_local.AkshareDataError as exc:
        raise SelectionImportError(f"四指数读取失败: {exc}") from exc
    expected = {"000001.SH", "399001.SZ", "399006.SZ", "000688.SH"}
    indices = []
    for row in raw_indices:
        code = str(row.get("symbol") or row.get("code") or "")
        available = bool(row.get("available"))
        indices.append({
            "name": row.get("name"), "code": code, "available": available,
            "price": row.get("price") if available else None,
            "change_pct": row.get("change_pct") if available else None,
            "observed_at": row.get("observed_at") if available else None,
            "source": row.get("source"),
        })
    if len(indices) != 4 or {row["code"] for row in indices} != expected:
        raise SelectionImportError("四指数返回不完整，已拒绝上传整个集合")

    stocks, missing = _stock_snapshots_from_daily_quotes(items, daily_quotes)
    if missing:
        print(f"本地最新真实收盘快照缺失，跳过: {','.join(missing)}", file=sys.stderr)
    try:
        response = post(
            _market_snapshot_import_url(selection_url),
            headers={"X-Job-Token": token},
            json={"indices": indices, "stocks": stocks},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise SelectionImportError(f"市场快照导入接口返回 HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise SelectionImportError(f"请求市场快照导入接口失败: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise SelectionImportError("市场快照导入接口返回了无效 JSON") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    available_indices = sum(1 for row in indices if row["available"])
    if not isinstance(data, dict) or data.get("indices") != available_indices or data.get("stocks") != len(stocks):
        raise SelectionImportError("市场快照导入接口响应数量与本地数据不一致")
    if not stocks:
        raise SelectionImportError("所有入选股票均无可上传的最近真实收盘快照")
    return available_indices, len(stocks)


def _load_existing_selection_items(
    trade_date: str, *, get: Callable[..., httpx.Response] = httpx.get,
) -> list[dict]:
    selection_url, _token = _api_config()
    url = _sibling_api_url(selection_url, "/api/selections")
    try:
        response = get(url, params={"date": trade_date}, timeout=60.0)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise SelectionImportError(f"读取已有选股返回 HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise SelectionImportError(f"读取已有选股失败: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise SelectionImportError("已有选股接口返回了无效 JSON") from exc
    items = payload.get("data", {}).get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise SelectionImportError(f"{trade_date} 没有可刷新的已有选股结果")
    return items


def _backfill_existing_selection_prices(
    trade_date: str,
    items: list[dict],
    *,
    price_filler: Callable[..., list[dict]] = akshare_local.fill_selection_prices,
    post: Callable[..., httpx.Response] = httpx.post,
) -> tuple[list[dict], int]:
    """Atomically fill only missing fixed prices, then upsert the full unchanged set."""
    target_date = date.fromisoformat(trade_date).isoformat()
    prepared = [dict(item) for item in items]
    missing: list[dict] = []
    missing_indexes: list[int] = []
    for index, item in enumerate(prepared):
        fixed_price = item.get("selection_price")
        fixed_date = item.get("selection_price_date")
        if (fixed_price is None) != (fixed_date is None):
            raise SelectionImportError(f"{item.get('code', 'unknown')} 的固定选入价与日期不完整")
        if fixed_price is None:
            candidate = dict(item)
            candidate["trade_date"] = target_date
            candidate["price"] = None
            candidate["price_date"] = None
            missing.append(candidate)
            missing_indexes.append(index)

    if not missing:
        return prepared, 0

    try:
        priced = price_filler(missing)
    except akshare_local.AkshareDataError as exc:
        raise SelectionImportError(f"已有选股固定价补齐失败: {exc}") from exc
    if len(priced) != len(missing):
        raise SelectionImportError("已有选股固定价补齐结果数量不一致，已拒绝回写")

    completed = [dict(item) for item in prepared]
    for original, filled, index in zip(missing, priced, missing_indexes):
        original_key = (str(original.get("code")), str(original.get("strategy_name") or "默认策略"))
        filled_key = (str(filled.get("code")), str(filled.get("strategy_name") or "默认策略"))
        try:
            price = float(filled["price"])
            price_date = date.fromisoformat(str(filled["price_date"])[:10]).isoformat()
        except (KeyError, TypeError, ValueError) as exc:
            raise SelectionImportError(
                f"{original.get('code', 'unknown')} 未取得有效固定选入价，已拒绝回写"
            ) from exc
        if original_key != filled_key or not isfinite(price) or price <= 0 or price_date > target_date:
            raise SelectionImportError(
                f"{original.get('code', 'unknown')} 的固定选入价结果无效，已拒绝回写"
            )
        completed[index].update(
            price=price,
            selection_price=price,
            price_date=price_date,
            selection_price_date=price_date,
            price_source=filled.get("price_source"),
        )

    # One request only after every missing price has passed validation. The API
    # persists this request in one transaction; replace_existing remains false.
    run = _import_selection_run(target_date, selector=lambda _date: completed, post=post)
    return run.items, len(missing)


def _sync_selected_market_data(trade_date: str, items: list[dict]) -> tuple[int, int, int, int]:
    errors: list[str] = []
    daily_quotes: list[dict] = []
    daily_count = intraday_count = index_count = stock_count = 0
    try:
        daily_quotes = _load_selected_quote_history(trade_date, items)
        daily_count = _upload_quote_rows(daily_quotes)
    except SelectionImportError as exc:
        errors.append(f"日K: {exc}")
    try:
        intraday_count = import_intraday_quote_history(items)
    except SelectionImportError as exc:
        errors.append(f"30m K: {exc}")
    try:
        index_count, stock_count = import_market_snapshots(items, daily_quotes)
    except SelectionImportError as exc:
        errors.append(f"指数/当前价: {exc}")
    if errors:
        raise SelectionImportError("；".join(errors))
    return daily_count, intraday_count, index_count, stock_count


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
    parser.add_argument(
        "--refresh-existing-date",
        help="仅刷新指定日期已有选股的指数、当前价、日K与30m K；不运行官方脚本、不重选或删除",
    )
    args = parser.parse_args(argv)
    _load_env_file(Path(args.env_file))
    try:
        if args.refresh_existing_date:
            refresh_date = date.fromisoformat(args.refresh_existing_date).isoformat()
            items = _load_existing_selection_items(refresh_date)
            items, fixed_price_count = _backfill_existing_selection_prices(refresh_date, items)
            daily_count, intraday_count, index_count, stock_count = _sync_selected_market_data(
                refresh_date, items
            )
            print(
                "已有选股行情刷新成功: "
                f"trade_date={refresh_date}, fixed_prices={fixed_price_count}, daily_quotes={daily_count}, "
                f"intraday_30m_quotes={intraday_count}, indices={index_count}, stocks={stock_count}"
            )
            return 0
        requested_date = date.fromisoformat(args.trade_date)
        if requested_date.weekday() >= 5:
            print(f"非交易日，跳过本地选股与上传: {requested_date.isoformat()}")
            return 0
        selection_run = _import_selection_run(args.trade_date, replace_existing=args.replace_existing)
        quote_count, intraday_quote_count, index_count, stock_count = _sync_selected_market_data(
            selection_run.trade_date, selection_run.items
        )
    except (SelectionImportError, LocalSelectionDataError, ValueError) as exc:
        print(f"本地选股导入失败: {exc}", file=sys.stderr)
        return 1
    print(
        "本地选股与K线导入成功: "
        f"trade_date={selection_run.trade_date}, selections={selection_run.count}, "
        f"daily_quotes={quote_count}, intraday_30m_quotes={intraday_quote_count}, "
        f"indices={index_count}, stocks={stock_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
