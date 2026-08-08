"""A-share market-data acquisition and cleaning.

The module deliberately does not know about the application's database.  Its
public functions return JSON-friendly ``list[dict]`` values that can be handed
to a persistence layer by the caller.

Data-source policy follows the Apache-2.0 ``a-stock-data`` project:

* Tencent HTTP quotes are the default security-master source and Tencent is
  preferred for daily/weekly/monthly single-stock K-lines.
* Eastmoney is a last-resort security-master source and the intraday K-line
  fallback.  Its requests remain serialized and throttled.
* Tushare's HTTP API is an optional fallback for an exact historical
  whole-market trading date.  Set ``TUSHARE_TOKEN`` to enable it.

Source/reference: https://github.com/simonlin1212/a-stock-data (Apache-2.0).

No API key is required for the default paths.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import os
from pathlib import Path
import random
import threading
import time
from typing import Any

import httpx


logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TUSHARE_URL = "https://api.tushare.pro"
STRATEGY_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "strategy.json"

_DEFAULT_ALLOWED_PREFIXES = ("600", "601", "603", "000", "001", "002", "300", "301")
_DEFAULT_EXCLUDED_PREFIXES = ("688", "8", "4", "43")
# A small, liquid, code-only emergency universe.  The active subset is selected
# from strategy.json's allowed/excluded prefixes at runtime; names are filled by
# Tencent K-line metadata when available.  Keeping this bounded prevents a
# Railway recovery job from issuing thousands of speculative K-line requests.
_BUILTIN_FALLBACK_STOCKS = {
    "600000": "浦发银行", "600036": "招商银行", "600519": "贵州茅台",
    "601318": "中国平安", "601398": "工商银行", "601857": "中国石油",
    "603259": "药明康德", "603501": "韦尔股份", "603986": "兆易创新",
    "000001": "平安银行", "000333": "美的集团", "000858": "五粮液",
    "001979": "招商蛇口", "001696": "宗申动力", "001872": "招商港口",
    "002230": "科大讯飞", "002475": "立讯精密", "002594": "比亚迪",
    "300014": "亿纬锂能", "300308": "中际旭创", "300750": "宁德时代",
    "301236": "软通动力", "301269": "华大九天", "301308": "江波龙",
}

# Main board, ChiNext, STAR Market and Beijing Stock Exchange A shares.
_A_SHARE_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
_QUOTE_FIELDS = (
    "f2,f3,f4,f5,f6,f7,f8,f12,f13,f14,f15,f16,f17,f18,f26,f100,f124"
)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_PERIODS = {
    "1m": ("1m", 1),
    "1min": ("1m", 1),
    "5m": ("5m", 5),
    "5min": ("5m", 5),
    "15m": ("15m", 15),
    "15min": ("15m", 15),
    "30m": ("30m", 30),
    "30min": ("30m", 30),
    "60m": ("60m", 60),
    "60min": ("60m", 60),
    "day": ("day", 101),
    "daily": ("day", 101),
    "d": ("day", 101),
    "week": ("week", 102),
    "weekly": ("week", 102),
    "w": ("week", 102),
    "month": ("month", 103),
    "monthly": ("month", 103),
    "mon": ("month", 103),
}

_http_client = httpx.Client(
    headers={"User-Agent": USER_AGENT},
    timeout=httpx.Timeout(15.0, connect=8.0),
    follow_redirects=True,
)
_eastmoney_lock = threading.Lock()
_eastmoney_last_call = 0.0
_eastmoney_min_interval = float(os.getenv("EASTMONEY_MIN_INTERVAL", "1.0"))


class MarketDataError(RuntimeError):
    """Raised for invalid input or a non-recoverable upstream response."""


def _sleep_before_retry(attempt: int, retry_after: str | None = None) -> None:
    """Sleep with exponential backoff and a small anti-herding jitter."""
    if retry_after:
        try:
            delay = min(float(retry_after), 30.0)
        except ValueError:
            delay = 0.0
    else:
        delay = 0.0
    time.sleep(max(delay, 0.6 * (2**attempt)) + random.uniform(0.1, 0.4))


def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    eastmoney: bool = False,
) -> dict[str, Any]:
    """Request a JSON object with connection/status/decoding retries."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            if eastmoney:
                response = _eastmoney_request(
                    method, url, params=params, json=json, headers=headers
                )
            else:
                response = _http_client.request(
                    method, url, params=params, json=json, headers=headers
                )

            if response.status_code in _RETRYABLE_STATUS:
                if attempt + 1 < retries:
                    _sleep_before_retry(attempt, response.headers.get("Retry-After"))
                    continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("upstream JSON root is not an object")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                _sleep_before_retry(attempt)

    raise MarketDataError(f"request failed after {retries} attempts: {url}") from last_error


def _request_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    encoding: str = "utf-8",
) -> str:
    """Request text with the same retry policy used by JSON endpoints."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = _http_client.get(url, headers=headers)
            if response.status_code in _RETRYABLE_STATUS and attempt + 1 < retries:
                _sleep_before_retry(attempt, response.headers.get("Retry-After"))
                continue
            response.raise_for_status()
            return response.content.decode(encoding, errors="replace")
        except (httpx.HTTPError, UnicodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                _sleep_before_retry(attempt)
    display_url = f"{TENCENT_QUOTE_URL}<batch>" if url.startswith(TENCENT_QUOTE_URL) else url
    raise MarketDataError(f"request failed after {retries} attempts: {display_url}") from last_error


def _eastmoney_request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None,
    json: dict[str, Any] | None,
    headers: dict[str, str] | None,
) -> httpx.Response:
    """Serialize and throttle Eastmoney calls to reduce IP-blocking risk."""
    global _eastmoney_last_call
    with _eastmoney_lock:
        remaining = _eastmoney_min_interval - (time.monotonic() - _eastmoney_last_call)
        if remaining > 0:
            time.sleep(remaining + random.uniform(0.1, 0.35))
        try:
            return _http_client.request(
                method,
                url,
                params=params,
                json=json,
                headers={"Referer": "https://quote.eastmoney.com/", **(headers or {})},
            )
        finally:
            _eastmoney_last_call = time.monotonic()


def _normalise_code(stock_code: str) -> str:
    value = str(stock_code).strip().upper()
    if value[:2] in {"SH", "SZ", "BJ"}:
        value = value[2:]
    if "." in value:
        left, right = value.split(".", 1)
        value = left if left.isdigit() else right
    if len(value) != 6 or not value.isdigit():
        raise ValueError(f"invalid A-share stock code: {stock_code!r}")
    return value


def _exchange(code: str, market_id: Any = None) -> str:
    if code.startswith(("4", "8")):
        return "BJ"
    if str(market_id) == "1" or code.startswith(("6", "9")):
        return "SH"
    return "SZ"


def _eastmoney_secid(code: str) -> str:
    return f"{1 if _exchange(code) == 'SH' else 0}.{code}"


def _tencent_symbol(code: str) -> str:
    return f"{_exchange(code).lower()}{code}"


def _is_st_name(name: Any) -> bool:
    compact = str(name or "").upper().replace(" ", "")
    return compact.startswith(("ST", "*ST", "S*ST", "SST"))


def _number(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _price(value: Any) -> float | None:
    number = _number(value)
    return round(number, 4) if number is not None else None


def _lots_to_shares(value: Any) -> float | None:
    lots = _number(value)
    return lots * 100 if lots is not None else None


def _limit_ratio(code: str, is_st: bool) -> Decimal:
    if is_st:
        return Decimal("0.05")
    if code.startswith(("4", "8")):
        return Decimal("0.30")
    if code.startswith(("300", "301", "688", "689")):
        return Decimal("0.20")
    return Decimal("0.10")


def _limit_prices(code: str, previous_close: Any, is_st: bool) -> tuple[float | None, float | None]:
    previous = _number(previous_close)
    if previous is None or previous <= 0:
        return None, None
    base = Decimal(str(previous))
    ratio = _limit_ratio(code, is_st)
    tick = Decimal("0.01")
    upper = (base * (Decimal("1") + ratio)).quantize(tick, rounding=ROUND_HALF_UP)
    lower = (base * (Decimal("1") - ratio)).quantize(tick, rounding=ROUND_HALF_UP)
    return float(upper), float(lower)


def _limit_flags(close: Any, limit_up: float | None, limit_down: float | None) -> tuple[bool, bool]:
    current = _number(close)
    if current is None:
        return False, False
    tolerance = 0.0051
    return (
        limit_up is not None and current >= limit_up - tolerance,
        limit_down is not None and current <= limit_down + tolerance,
    )


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("trade_date must use YYYY-MM-DD") from exc


def _is_obviously_non_trading_day(day: date) -> bool:
    # Holiday confirmation ultimately comes from an empty/mismatched upstream
    # response; weekends can be skipped without making a network request.
    return day.weekday() >= 5 or day > date.today()


def _items(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    data = payload.get("data") or {}
    diff = data.get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    rows = [row for row in diff if isinstance(row, dict)]
    return rows, int(data.get("total") or len(rows))


def _fetch_market_pages(fields: str = _QUOTE_FIELDS) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    page = 1
    page_size = 500
    while True:
        payload = _request_json(
            "GET",
            EASTMONEY_LIST_URL,
            params={
                "pn": page,
                "pz": page_size,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f12",
                "fs": _A_SHARE_FILTER,
                "fields": fields,
            },
            eastmoney=True,
        )
        rows, total = _items(payload)
        if not rows:
            break
        output.extend(rows)
        if len(output) >= total:
            break
        page += 1
    return output


def _universe_prefixes() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Load the data-layer universe from the strategy configuration."""
    try:
        payload = json.loads(STRATEGY_CONFIG_PATH.read_text(encoding="utf-8"))
        universe = payload["builtin"]["universe"]
        allowed = tuple(str(value) for value in universe["allowed_prefixes"] if str(value))
        excluded = tuple(str(value) for value in universe["excluded_prefixes"] if str(value))
        if allowed:
            return allowed, excluded
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.error("strategy universe config unavailable; using safe defaults: %s", exc)
    return _DEFAULT_ALLOWED_PREFIXES, _DEFAULT_EXCLUDED_PREFIXES


def _is_target_code(
    code: str,
    allowed_prefixes: tuple[str, ...] | None = None,
    excluded_prefixes: tuple[str, ...] | None = None,
) -> bool:
    allowed, excluded = (
        (allowed_prefixes, excluded_prefixes or ())
        if allowed_prefixes is not None
        else _universe_prefixes()
    )
    return code.startswith(allowed) and not code.startswith(excluded)


def _tencent_stock_candidates() -> list[str]:
    """Build the finite supported-code universe for Tencent quote discovery."""
    allowed, excluded = _universe_prefixes()
    candidates: set[str] = set()
    for prefix in allowed:
        if not prefix.isdigit() or len(prefix) != 3:
            logger.error("ignoring unsupported universe prefix %r; expected three digits", prefix)
            continue
        for suffix in range(1000):
            code = f"{prefix}{suffix:03d}"
            if _is_target_code(code, allowed, excluded):
                candidates.add(code)
    return sorted(candidates)


def _request_tencent_quote_batch(symbols: list[str]) -> str:
    """Request Tencent's GBK quote response with the normal retry policy."""
    return _request_text(
        f"{TENCENT_QUOTE_URL}{','.join(symbols)}",
        headers={"Referer": "https://gu.qq.com/"},
        encoding="gbk",
    )


def _parse_tencent_stock_list(text: str) -> list[dict[str, Any]]:
    """Parse Tencent's GBK ``~``-delimited batch quote response."""
    allowed, excluded = _universe_prefixes()
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in text.replace(";", "\n").splitlines():
        if '="' not in line:
            continue
        body = line.split('="', 1)[1].rsplit('"', 1)[0]
        values = body.split("~")
        if len(values) < 3:
            continue
        try:
            code = _normalise_code(values[2])
        except ValueError:
            continue
        name = values[1].strip()
        if not name or code in seen or not _is_target_code(code, allowed, excluded):
            continue
        seen.add(code)
        output.append(
            {
                "code": code,
                "name": name,
                "industry": None,
                "exchange": _exchange(code),
                "list_date": None,
                "is_st": _is_st_name(name),
                "source": "tencent",
            }
        )
    return output


def _tencent_stock_list() -> list[dict[str, Any]]:
    """Discover the configured A-share universe through Tencent HTTP quotes.

    Tencent does not expose a documented security-master endpoint.  We expand
    the eight configured three-digit ranges and validate candidates in batches;
    nonexistent codes are simply omitted from the quote response.

    Endpoint format and source priority reference:
    https://github.com/simonlin1212/a-stock-data (Apache-2.0).
    """
    candidates = _tencent_stock_candidates()
    batch_size = max(1, min(int(os.getenv("TENCENT_LIST_BATCH_SIZE", "80")), 80))
    output: list[dict[str, Any]] = []
    for start in range(0, len(candidates), batch_size):
        codes = candidates[start:start + batch_size]
        output.extend(_parse_tencent_stock_list(
            _request_tencent_quote_batch([_tencent_symbol(code) for code in codes])
        ))
    stocks = sorted({item["code"]: item for item in output}.values(), key=lambda item: item["code"])
    if not stocks:
        raise MarketDataError("Tencent stock-list response did not contain any target securities")
    return stocks


def sync_stock_list() -> list[dict[str, Any]]:
    """Fetch the configured A-share security master without blocking K-line sync.

    Each row contains at least ``code``, ``name`` and ``industry`` plus market,
    listing date and ST status.  Source order is Tencent, optional Tushare,
    No Eastmoney security-master fallback is used: the overseas deployment
    relies on Tencent HTTP and optionally Tushare when configured.
    """
    try:
        stocks = _tencent_stock_list()
        if stocks:
            return stocks
    except MarketDataError as exc:
        logger.warning("Tencent stock-list sync failed: %s", exc)
    else:
        logger.warning("Tencent stock-list sync returned no valid target stocks")

    if os.getenv("TUSHARE_TOKEN", "").strip():
        try:
            stocks = _tushare_stock_list()
            if stocks:
                allowed, excluded = _universe_prefixes()
                return [item for item in stocks if _is_target_code(item["code"], allowed, excluded)]
        except MarketDataError as exc:
            logger.warning("Tushare stock-list fallback failed: %s", exc)

    return []


def _tushare_stock_list() -> list[dict[str, Any]]:
    """Fetch the security master from Tushare when the public source is blocked."""
    rows: list[dict[str, Any]] = []
    for status in ("L", "D", "P"):
        rows.extend(
            _tushare_call(
                "stock_basic",
                {"exchange": "", "list_status": status},
                "ts_code,symbol,name,industry,exchange,list_date,list_status",
            )
        )
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        try:
            code = _normalise_code(str(row.get("symbol") or row.get("ts_code", "")))
        except ValueError:
            continue
        if code in seen:
            continue
        seen.add(code)
        name = str(row.get("name") or "").strip()
        raw_date = str(row.get("list_date") or "")
        output.append(
            {
                "code": code,
                "name": name,
                "industry": str(row.get("industry") or "").strip() or None,
                "exchange": _exchange(code),
                "list_date": (
                    f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                    if len(raw_date) == 8 and raw_date.isdigit()
                    else None
                ),
                "is_st": _is_st_name(name),
                "list_status": row.get("list_status") or None,
            }
        )
    return sorted(output, key=lambda item: item["code"])


def _quote_date(row: dict[str, Any]) -> str | None:
    stamp = _number(row.get("f124"))
    if stamp:
        return datetime.fromtimestamp(stamp).date().isoformat()
    return None


def _clean_snapshot_row(row: dict[str, Any], trade_date: str) -> dict[str, Any] | None:
    try:
        code = _normalise_code(str(row.get("f12", "")))
    except ValueError:
        return None
    name = str(row.get("f14") or "").strip()
    open_price = _price(row.get("f17"))
    close = _price(row.get("f2"))
    high = _price(row.get("f15"))
    low = _price(row.get("f16"))
    previous = _price(row.get("f18"))
    volume_lots = _number(row.get("f5"))
    volume = volume_lots * 100 if volume_lots is not None else None
    is_suspended = not volume or any(value is None for value in (open_price, close, high, low))
    is_st = _is_st_name(name)
    limit_up, limit_down = _limit_prices(code, previous, is_st)
    hit_up, hit_down = _limit_flags(close, limit_up, limit_down)
    return {
        "trade_date": trade_date,
        "code": code,
        "name": name,
        "industry": str(row.get("f100") or "").strip() or None,
        "exchange": _exchange(code, row.get("f13")),
        "open": open_price,
        "close": close,
        "high": high,
        "low": low,
        "previous_close": previous,
        "change": _number(row.get("f4")),
        "change_pct": _number(row.get("f3")),
        "volume": volume,
        "amount": _number(row.get("f6")),
        "turnover_rate": _number(row.get("f8")),
        "amplitude": _number(row.get("f7")),
        "is_suspended": is_suspended,
        "is_st": is_st,
        "limit_up_price": limit_up,
        "limit_down_price": limit_down,
        "is_limit_up": hit_up and not is_suspended,
        "is_limit_down": hit_down and not is_suspended,
        "source": "eastmoney",
    }


def _latest_market_snapshot(trade_date: str) -> list[dict[str, Any]]:
    raw_rows = _fetch_market_pages()
    source_dates = [value for row in raw_rows if (value := _quote_date(row))]
    # Eastmoney retains the previous session on weekends/holidays.  Never label
    # that snapshot as the date requested by the caller.
    if not source_dates or max(source_dates) != trade_date:
        return []
    return [
        cleaned
        for row in raw_rows
        if (cleaned := _clean_snapshot_row(row, trade_date)) is not None
    ]


def _tushare_call(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        return []
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            payload = _request_json(
                "POST",
                TUSHARE_URL,
                json={"api_name": api_name, "token": token, "params": params, "fields": fields},
                retries=1,
            )
            if int(payload.get("code", -1)) != 0:
                raise MarketDataError(str(payload.get("msg") or "Tushare API error"))
            data = payload.get("data") or {}
            names = data.get("fields") or []
            return [dict(zip(names, values)) for values in (data.get("items") or [])]
        except (MarketDataError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                _sleep_before_retry(attempt)
    raise MarketDataError(f"Tushare {api_name} failed") from last_error


def _tushare_daily(trade_date: str) -> list[dict[str, Any]]:
    compact_date = trade_date.replace("-", "")
    daily = _tushare_call(
        "daily",
        {"trade_date": compact_date},
        "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
    )
    if not daily:
        return []
    basics = _tushare_call(
        "stock_basic",
        {"exchange": "", "list_status": "L"},
        "ts_code,symbol,name,industry,exchange,list_date",
    )
    basic_by_code = {str(item.get("symbol")): item for item in basics}
    cleaned: list[dict[str, Any]] = []
    for row in daily:
        try:
            code = _normalise_code(str(row.get("ts_code", "")).split(".", 1)[0])
        except ValueError:
            continue
        basic = basic_by_code.get(code, {})
        name = str(basic.get("name") or "").strip()
        previous = _price(row.get("pre_close"))
        close = _price(row.get("close"))
        is_st = _is_st_name(name)
        limit_up, limit_down = _limit_prices(code, previous, is_st)
        hit_up, hit_down = _limit_flags(close, limit_up, limit_down)
        volume_lots = _number(row.get("vol"))
        amount_thousand = _number(row.get("amount"))
        is_suspended = not volume_lots
        cleaned.append(
            {
                "trade_date": trade_date,
                "code": code,
                "name": name,
                "industry": basic.get("industry") or None,
                "exchange": _exchange(code),
                "open": _price(row.get("open")),
                "close": close,
                "high": _price(row.get("high")),
                "low": _price(row.get("low")),
                "previous_close": previous,
                "change": _number(row.get("change")),
                "change_pct": _number(row.get("pct_chg")),
                "volume": volume_lots * 100 if volume_lots is not None else None,
                "amount": amount_thousand * 1000 if amount_thousand is not None else None,
                "turnover_rate": None,
                "amplitude": None,
                "is_suspended": is_suspended,
                "is_st": is_st,
                "limit_up_price": limit_up,
                "limit_down_price": limit_down,
                "is_limit_up": hit_up and not is_suspended,
                "is_limit_down": hit_down and not is_suspended,
                "source": "tushare",
            }
        )
    return sorted(cleaned, key=lambda item: item["code"])


def sync_daily_quotes(trade_date: str) -> list[dict[str, Any]]:
    """Fetch target-universe daily bars for one date from Tencent qfq K-lines.

    Tencent is deliberately the primary source here: unlike the former
    Eastmoney snapshot path, it is suitable for overseas scheduled workers and
    does not require a Tushare token.  The security master is metadata only;
    OHLCV always comes from Tencent's HTTP K-line endpoint.
    """
    day = _parse_date(trade_date)
    if _is_obviously_non_trading_day(day):
        return []
    return _tencent_history_for_universe(trade_date, limit=8, only_target=True)


def latest_trading_date(reference: date | None = None) -> str:
    """Best-effort latest session date without relying on an exchange calendar."""
    current = reference or date.today()
    if current.weekday() >= 5:
        current -= timedelta(days=current.weekday() - 4)
    return current.isoformat()


def sync_quote_history(
    trade_date: str | None = None, limit: int = 160, universe: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Fetch enough Tencent qfq daily history to prime the strategy indicators."""
    target = trade_date or latest_trading_date()
    day = _parse_date(target)
    if _is_obviously_non_trading_day(day):
        return []
    return _tencent_history_for_universe(
        target, limit=max(limit, 80), only_target=False, universe=universe
    )


def _tencent_history_for_universe(
    trade_date: str, *, limit: int, only_target: bool, universe: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Fetch Tencent qfq bars for every configured A-share universe code.

    The master list is cached by callers in the database after the first run;
    workers are bounded to avoid overloading the free upstream endpoint.
    """
    universe = universe or sync_stock_list()
    universe = [item for item in universe if _is_target_code(item["code"])]
    if not universe:
        return []

    def fetch(stock: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            bars = _get_tencent_kline(stock["code"], "day", limit=limit)
        except MarketDataError as exc:
            logger.warning("Tencent daily K-line failed for %s: %s", stock["code"], exc)
            return []
        rows: list[dict[str, Any]] = []
        for bar in bars:
            bar_day = str(bar["datetime"])[:10]
            if bar_day > trade_date or (only_target and bar_day != trade_date):
                continue
            if any(bar.get(key) is None for key in ("open", "high", "low", "close")):
                continue
            rows.append(
                {
                    "code": stock["code"],
                    "name": stock["name"] or stock["code"],
                    "industry": stock.get("industry"),
                    "is_st": stock.get("is_st", False),
                    "trade_date": bar_day,
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar.get("volume") or 0,
                    "amount": bar.get("amount"),
                    "source": "tencent-qfq",
                }
            )
        return rows

    workers = max(1, min(int(os.getenv("TENCENT_SYNC_WORKERS", "8")), 16))
    output: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tencent-kline") as pool:
        futures = [pool.submit(fetch, stock) for stock in universe]
        for future in as_completed(futures):
            output.extend(future.result())
    return sorted(output, key=lambda item: (item["trade_date"], item["code"]))


def _parse_tencent_kline(code: str, period: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = _tencent_symbol(code)
    block = (payload.get("data") or {}).get(symbol) or {}
    rows = block.get(f"qfq{period}") or block.get(period) or []
    quote = block.get("qt") or {}
    quote_values = quote.get(symbol) if isinstance(quote, dict) else None
    current_name = quote_values[1] if isinstance(quote_values, list) and len(quote_values) > 1 else ""
    is_st = _is_st_name(current_name)
    output: list[dict[str, Any]] = []
    previous: float | None = None
    for values in rows:
        if not isinstance(values, list) or len(values) < 6:
            continue
        close = _price(values[2])
        item = _clean_kline_row(
            code=code,
            period=period,
            moment=str(values[0]),
            open_price=values[1],
            close=values[2],
            high=values[3],
            low=values[4],
            volume=_lots_to_shares(values[5]),
            amount=values[6] if len(values) > 6 else None,
            turnover_rate=None,
            change_pct=None,
            change=None,
            previous_close=previous,
            is_st=is_st,
            source="tencent",
        )
        output.append(item)
        if close is not None:
            previous = close
    return output


def _clean_kline_row(
    *,
    code: str,
    period: str,
    moment: str,
    open_price: Any,
    close: Any,
    high: Any,
    low: Any,
    volume: Any,
    amount: Any,
    turnover_rate: Any,
    change_pct: Any,
    change: Any,
    previous_close: Any,
    is_st: bool,
    source: str,
) -> dict[str, Any]:
    open_value = _price(open_price)
    close_value = _price(close)
    high_value = _price(high)
    low_value = _price(low)
    volume_value = _number(volume)
    previous = _price(previous_close)
    is_suspended = not volume_value or any(
        value is None for value in (open_value, close_value, high_value, low_value)
    )
    if previous is None and close_value is not None and _number(change) is not None:
        previous = close_value - _number(change)
    if change is None and close_value is not None and previous is not None:
        change = close_value - previous
    if change_pct is None and _number(change) is not None and previous:
        change_pct = _number(change) / previous * 100
    limit_up, limit_down = _limit_prices(code, previous, is_st)
    hit_up, hit_down = _limit_flags(close_value, limit_up, limit_down)
    return {
        "code": code,
        "period": period,
        "datetime": moment,
        "open": open_value,
        "close": close_value,
        "high": high_value,
        "low": low_value,
        "previous_close": previous,
        "change": round(_number(change), 4) if _number(change) is not None else None,
        "change_pct": round(_number(change_pct), 4) if _number(change_pct) is not None else None,
        "volume": volume_value,
        "amount": _number(amount),
        "turnover_rate": _number(turnover_rate),
        "is_suspended": is_suspended,
        # This reflects the security name returned with the series.  Providers
        # do not expose historical name changes, so very old ST transitions are
        # necessarily best-effort.
        "is_st": is_st,
        "limit_up_price": limit_up,
        "limit_down_price": limit_down,
        "is_limit_up": hit_up and not is_suspended,
        "is_limit_down": hit_down and not is_suspended,
        "source": source,
    }


def _get_tencent_kline(code: str, period: str, limit: int = 640) -> list[dict[str, Any]]:
    symbol = _tencent_symbol(code)
    payload = _request_json(
        "GET",
        TENCENT_KLINE_URL,
        params={"param": f"{symbol},{period},,,{limit},qfq"},
        headers={"Referer": "https://gu.qq.com/"},
    )
    return _parse_tencent_kline(code, period, payload)


def _get_eastmoney_kline(code: str, period: str, klt: int, limit: int = 1000) -> list[dict[str, Any]]:
    payload = _request_json(
        "GET",
        EASTMONEY_KLINE_URL,
        params={
            "secid": _eastmoney_secid(code),
            "klt": klt,
            "fqt": 1,
            "beg": 0,
            "end": 20500101,
            "lmt": limit,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        },
        eastmoney=True,
    )
    data = payload.get("data") or {}
    lines = data.get("klines") or []
    is_st = _is_st_name(data.get("name"))
    output: list[dict[str, Any]] = []
    previous: float | None = None
    for line in lines:
        values = str(line).split(",")
        if len(values) < 7:
            continue
        item = _clean_kline_row(
            code=code,
            period=period,
            moment=values[0],
            open_price=values[1],
            close=values[2],
            high=values[3],
            low=values[4],
            volume=_lots_to_shares(values[5]),
            amount=values[6],
            turnover_rate=values[10] if len(values) > 10 else None,
            change_pct=values[8] if len(values) > 8 else None,
            change=values[9] if len(values) > 9 else None,
            previous_close=previous,
            is_st=is_st,
            source="eastmoney",
        )
        output.append(item)
        if item["close"] is not None:
            previous = item["close"]
    return output


def get_kline(stock_code: str, period: str) -> list[dict[str, Any]]:
    """Fetch a cleaned, forward-adjusted single-stock K-line series.

    Supported periods: ``1m``, ``5m``, ``15m``, ``30m``, ``60m``, ``day``,
    ``week`` and ``month`` (common aliases such as ``daily`` are accepted).
    Daily/weekly/monthly data prefer Tencent; intraday data use Eastmoney.
    Exhausted network/source errors return ``[]`` after retry and fallback.
    """
    code = _normalise_code(stock_code)
    key = str(period).strip().lower()
    if key not in _PERIODS:
        raise ValueError(f"unsupported K-line period: {period!r}")
    canonical, klt = _PERIODS[key]

    if canonical in {"day", "week", "month"}:
        try:
            rows = _get_tencent_kline(code, canonical)
            if rows:
                return rows
        except MarketDataError as exc:
            logger.warning("Tencent K-line failed for %s: %s", code, exc)

    try:
        return _get_eastmoney_kline(code, canonical, klt)
    except MarketDataError as exc:
        logger.warning("Eastmoney K-line failed for %s: %s", code, exc)
        return []


__all__ = [
    "MarketDataError", "get_kline", "latest_trading_date", "sync_daily_quotes",
    "sync_quote_history", "sync_stock_list",
]
