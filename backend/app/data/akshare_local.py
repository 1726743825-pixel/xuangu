"""Local-only AKShare adapters for verified A-share display data.

These helpers are intentionally not called by the Railway application.  The
domestic selector host may install AKShare in its own virtual environment and
use these functions to build import payloads.  AKShare is imported lazily so a
server which never invokes this module has no runtime dependency on it.

The normalisers use dataframe column names, never positional indexes.  That is
important because AKShare providers expose different column orders.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from math import isfinite
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo


AKSHARE_SOURCE = "akshare-sina"
SHANGHAI = ZoneInfo("Asia/Shanghai")
INDEX_SYMBOLS = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    # Sina's all-index snapshot does not currently contain this symbol.  It is
    # retained in the fixed dashboard contract and returned as unavailable,
    # never substituted with another index.
    "bj899050": "北证50",
    "sh000688": "科创50",
}


def _index_contract_symbol(provider_symbol: str) -> str:
    exchange = {"sh": "SH", "sz": "SZ", "bj": "BJ"}[provider_symbol[:2]]
    return f"{provider_symbol[2:]}.{exchange}"


class AkshareDataError(RuntimeError):
    """AKShare is unavailable or returned data that violates our contract."""


def _load_akshare() -> Any:
    try:
        import akshare  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AkshareDataError(
            "本机未安装 AKShare；请在本机行情同步专用虚拟环境中安装"
        ) from exc
    return akshare


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []
    try:
        return list(frame.to_dict(orient="records"))
    except (AttributeError, TypeError) as exc:
        raise AkshareDataError("AKShare 返回值不是可解析的 DataFrame") from exc


def _call(source_function: str, call: Callable[[], Any]) -> Any:
    try:
        return call()
    except AkshareDataError:
        raise
    except Exception as exc:
        raise AkshareDataError(
            f"AKShare {source_function} 请求失败: {type(exc).__name__}: {exc}"
        ) from exc


def _number(value: Any, field: str, *, optional: bool = False) -> float | None:
    if value is None or value == "":
        if optional:
            return None
        raise AkshareDataError(f"AKShare 行情缺少 {field}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AkshareDataError(f"AKShare {field} 不是数字: {value!r}") from exc
    if not isfinite(result) or result < 0:
        raise AkshareDataError(f"AKShare {field} 非法: {value!r}")
    return result


def _signed_number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AkshareDataError(f"AKShare {field} 不是数字: {value!r}") from exc
    if not isfinite(result):
        raise AkshareDataError(f"AKShare {field} 非法: {value!r}")
    return result


def validate_ohlc(open_: float, high: float, low: float, close: float) -> None:
    """Reject impossible OHLC instead of passing a corrupt row downstream."""
    if high < max(open_, close, low) or low > min(open_, close, high):
        raise AkshareDataError(
            f"OHLC 不变量失败: open={open_}, high={high}, low={low}, close={close}"
        )


def _stock_symbol(code: str) -> str:
    normalised = str(code).strip().lower().removeprefix("sh").removeprefix("sz")
    if len(normalised) != 6 or not normalised.isdigit():
        raise AkshareDataError(f"无效 A 股代码: {code!r}")
    return ("sh" if normalised.startswith("6") else "sz") + normalised


def _normalise_bars(
    rows: Iterable[dict[str, Any]],
    *,
    code: str,
    datetime_field: str,
    interval: str,
) -> list[dict[str, Any]]:
    normalised_code = _stock_symbol(code)[2:]
    result: list[dict[str, Any]] = []
    for row in rows:
        raw_datetime = row.get(datetime_field)
        try:
            parsed = datetime.fromisoformat(str(raw_datetime))
        except (TypeError, ValueError) as exc:
            raise AkshareDataError(f"AKShare 日期时间非法: {raw_datetime!r}") from exc
        open_ = _number(row.get("open"), "open")
        high = _number(row.get("high"), "high")
        low = _number(row.get("low"), "low")
        close = _number(row.get("close"), "close")
        volume = _number(row.get("volume"), "volume")
        amount = _number(row.get("amount"), "amount", optional=True)
        assert open_ is not None and high is not None and low is not None
        assert close is not None and volume is not None
        validate_ohlc(open_, high, low, close)
        if interval == "day":
            result.append({
                "code": normalised_code,
                "trade_date": parsed.date().isoformat(),
                "datetime": parsed.date().isoformat(),
                "open": open_, "high": high, "low": low, "close": close,
                "volume": volume, "amount": amount,
                "interval": "day", "adjustment": "none", "source": AKSHARE_SOURCE,
            })
        else:
            aware = parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)
            result.append({
                "code": normalised_code,
                "interval": "30m", "datetime": aware.isoformat(),
                "open": open_, "high": high, "low": low, "close": close,
                "volume": volume, "amount": amount, "amount_estimated": False,
                "adjustment": "none", "source": AKSHARE_SOURCE,
            })
    key = "trade_date" if interval == "day" else "datetime"
    return sorted(result, key=lambda item: str(item[key]))


def fetch_daily_bars(
    code: str,
    *,
    start_date: str,
    end_date: str,
    akshare_module: Any | None = None,
) -> list[dict[str, Any]]:
    """Fetch unadjusted daily OHLCV/amount from AKShare's Sina adapter."""
    ak = akshare_module or _load_akshare()
    frame = _call(
        "stock_zh_a_daily",
        lambda: ak.stock_zh_a_daily(
            symbol=_stock_symbol(code),
            start_date=date.fromisoformat(start_date).strftime("%Y%m%d"),
            end_date=date.fromisoformat(end_date).strftime("%Y%m%d"),
            adjust="",
        ),
    )
    return _normalise_bars(
        _records(frame), code=code, datetime_field="date", interval="day"
    )


def fetch_30m_bars(
    code: str,
    *,
    limit: int = 480,
    akshare_module: Any | None = None,
) -> list[dict[str, Any]]:
    """Fetch the latest real, unadjusted 30-minute bars from AKShare/Sina."""
    if not 1 <= limit <= 480:
        raise AkshareDataError("30m limit 必须在 1..480")
    ak = akshare_module or _load_akshare()
    frame = _call(
        "stock_zh_a_minute",
        lambda: ak.stock_zh_a_minute(symbol=_stock_symbol(code), period="30", adjust=""),
    )
    bars = _normalise_bars(
        _records(frame), code=code, datetime_field="day", interval="30m"
    )
    return bars[-limit:]


def fetch_five_indices(
    *, akshare_module: Any | None = None, observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch the five dashboard indices through AKShare's Sina adapter."""
    ak = akshare_module or _load_akshare()
    frame = _call("stock_zh_index_spot_sina", ak.stock_zh_index_spot_sina)
    rows = {str(row.get("代码", "")).lower(): row for row in _records(frame)}
    timestamp = (observed_at or datetime.now(SHANGHAI)).astimezone(SHANGHAI).isoformat()
    result = []
    for symbol, expected_name in INDEX_SYMBOLS.items():
        row = rows.get(symbol)
        if row is None:
            result.append({
                "symbol": _index_contract_symbol(symbol), "provider_symbol": symbol,
                "code": symbol[2:], "name": expected_name,
                "price": None, "change": None, "change_pct": None,
                "observed_at": timestamp, "price_date": None,
                "available": False, "source": AKSHARE_SOURCE,
            })
            continue
        result.append({
            "symbol": _index_contract_symbol(symbol),
            "provider_symbol": symbol,
            "code": symbol[2:],
            "name": str(row.get("名称") or expected_name),
            "price": _number(row.get("最新价"), "最新价"),
            "change": _signed_number(row.get("涨跌额"), "涨跌额"),
            "change_pct": _signed_number(row.get("涨跌幅"), "涨跌幅"),
            "observed_at": timestamp,
            # Sina's index spot response has no market-date column.  Do not
            # claim that a weekend observation is a weekend trade.
            "price_date": None,
            "available": True,
            "source": AKSHARE_SOURCE,
        })
    return result


def fetch_selected_spot(
    codes: Iterable[str],
    *,
    akshare_module: Any | None = None,
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Filter AKShare/Sina's market snapshot to selected codes only."""
    requested = {_stock_symbol(code) for code in codes}
    ak = akshare_module or _load_akshare()
    frame = _call("stock_zh_a_spot", ak.stock_zh_a_spot)
    rows = {str(row.get("代码", "")).lower(): row for row in _records(frame)}
    timestamp = (observed_at or datetime.now(SHANGHAI)).astimezone(SHANGHAI).isoformat()
    result = []
    for symbol in sorted(requested):
        row = rows.get(symbol)
        if row is None:
            continue
        result.append({
            "code": symbol[2:], "name": str(row.get("名称") or ""),
            "price": _number(row.get("最新价"), "最新价"),
            "change": _signed_number(row.get("涨跌额"), "涨跌额"),
            "change_pct": _signed_number(row.get("涨跌幅"), "涨跌幅"),
            "quote_time": str(row.get("时间戳") or "") or None,
            "observed_at": timestamp, "price_date": None,
            "source": AKSHARE_SOURCE,
        })
    return result


def fill_selection_prices(
    items: list[dict[str, Any]],
    *,
    daily_loader: Callable[..., list[dict[str, Any]]] = fetch_daily_bars,
) -> list[dict[str, Any]]:
    """Keep report prices; otherwise use the latest actual close on/before its date."""
    enriched: list[dict[str, Any]] = []
    for item in items:
        copied = dict(item)
        report_date = date.fromisoformat(str(copied["trade_date"])[:10]).isoformat()
        report_price = _number(copied.get("price"), "报告价格", optional=True)
        if report_price is not None:
            copied.update(
                price=report_price,
                # The report date may be a weekend.  Keep only an explicitly
                # supplied market date; never relabel a cached quote as Sunday.
                price_date=copied.get("price_date"),
                price_source=str(copied.get("price_source") or "official-report"),
            )
            enriched.append(copied)
            continue
        start_date = (date.fromisoformat(report_date) - timedelta(days=45)).isoformat()
        try:
            bars = daily_loader(copied["code"], start_date=start_date, end_date=report_date)
        except AkshareDataError:
            copied.update(price=None, price_date=None, price_source=None)
            enriched.append(copied)
            continue
        eligible = [bar for bar in bars if str(bar.get("trade_date", "")) <= report_date]
        if eligible:
            latest = max(eligible, key=lambda bar: str(bar["trade_date"]))
            copied.update(
                price=_number(latest.get("close"), "close"),
                price_date=str(latest["trade_date"]),
                price_source=str(latest.get("source") or AKSHARE_SOURCE),
            )
        else:
            copied.update(price=None, price_date=None, price_source=None)
        enriched.append(copied)
    return enriched


__all__ = [
    "AKSHARE_SOURCE", "INDEX_SYMBOLS", "AkshareDataError", "fetch_30m_bars",
    "fetch_daily_bars", "fetch_five_indices", "fetch_selected_spot",
    "fill_selection_prices", "validate_ohlc",
]
