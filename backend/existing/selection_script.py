"""Local, domestic-network entry point for producing importable selections.

Run this module on a machine that can reach the configured A-share quote
sources.  It intentionally has no database or HTTP-import responsibilities:
the caller owns uploading its JSON result to ``/api/selections/import``.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from typing import Any

from app.data import market_data
from app.strategy import engine


class LocalSelectionDataError(RuntimeError):
    """The local quote source did not provide usable data for a selection run."""


def _normalise_trade_date(trade_date: str | None) -> str:
    """Return the latest usable trading date instead of emitting weekend rows."""
    if trade_date is None:
        return market_data.latest_trading_date()
    try:
        requested = datetime.strptime(trade_date, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("trade_date 必须为 YYYY-MM-DD 格式") from exc
    return market_data.latest_trading_date(requested)


def _load_market_bars(trade_date: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Download local market data without touching the Railway database."""
    try:
        universe = market_data.sync_stock_list()
        if not universe:
            raise LocalSelectionDataError("股票列表为空")
        # The built-in strategy requires at least 65 sessions.  160 gives the
        # indicators enough warm-up room while reusing the configured rotation.
        bars = market_data.sync_quote_history(trade_date, limit=160, universe=universe)
    except market_data.MarketDataError as exc:
        raise LocalSelectionDataError(f"行情获取失败: {exc}") from exc
    except LocalSelectionDataError:
        raise
    except Exception as exc:
        raise LocalSelectionDataError(f"行情获取出现意外错误: {type(exc).__name__}: {exc}") from exc

    target_bars = [row for row in bars if str(row.get("trade_date", ""))[:10] == trade_date]
    if not bars:
        raise LocalSelectionDataError(f"行情获取失败: 未返回任何历史日线（{trade_date}）")
    if not target_bars:
        raise LocalSelectionDataError(f"行情获取失败: 未返回 {trade_date} 的日线")
    return universe, bars


def _reasons(signals: dict[str, Any]) -> list[str]:
    """Expose already-calculated strategy signals as concise display reasons."""
    reasons: list[str] = []
    if signals.get("ma5") is not None and signals.get("ma10") is not None and signals["ma5"] > signals["ma10"]:
        reasons.append("短期均线多头")
    if signals.get("dif") is not None and signals.get("dea") is not None and signals["dif"] > signals["dea"]:
        reasons.append("MACD 多头")
    vol_ma5 = signals.get("vol_ma5")
    if vol_ma5 and signals.get("volume") and signals["volume"] > vol_ma5:
        reasons.append("成交量高于5日均量")
    return reasons or ["满足内置技术共振策略"]


def _to_import_item(result: dict[str, Any], industries: dict[str, str | None]) -> dict[str, Any]:
    signals = result.get("signals") or {}
    score = float(result["score"])
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError(f"策略返回了无效 score: {result.get('score')!r}")
    code = str(result["stock_code"])
    return {
        "code": code,
        "name": str(result["stock_name"]),
        "trade_date": str(result["trade_date"]),
        "strategy_name": str(result["strategy_name"]),
        "score": round(score, 2),
        "price": signals.get("close"),
        "change_pct": signals.get("change_pct"),
        "industry": industries.get(code),
        "reasons": _reasons(signals),
        "indicators": signals,
    }


def run_selection(trade_date: str | None = None) -> list[dict[str, Any]]:
    """Run the existing built-in strategy using locally fetched quote data.

    The returned records are directly accepted as ``items`` by
    ``POST /api/selections/import``.  An empty list means real market data was
    processed but no stock met the configured threshold; source failures raise
    :class:`LocalSelectionDataError` instead of claiming an empty success.
    """
    target = _normalise_trade_date(trade_date)
    universe, raw_bars = _load_market_bars(target)
    config = engine._load_config()["builtin"]
    bars = engine._as_frame(raw_bars)
    selected = engine._builtin_selection(bars, target, config)
    industries = {str(item["code"]): item.get("industry") for item in universe}
    return [_to_import_item(item, industries) for item in selected]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行本地 A 股选股并输出可导入的 JSON items")
    parser.add_argument("trade_date", nargs="?", help="交易日（可选）；周末会自动回退至最近交易日")
    args = parser.parse_args()
    print(json.dumps(run_selection(args.trade_date), ensure_ascii=False, indent=2))
