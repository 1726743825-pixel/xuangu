from __future__ import annotations

from datetime import date
from importlib import import_module


def _demo_results(trade_date: str) -> list[dict]:
    return [
        {"code": "600519", "name": "贵州茅台", "trade_date": trade_date, "price": 1512.30, "change_pct": 1.86, "score": 92, "strategy_name": "趋势强度", "industry": "白酒", "reasons": ["站上20日均线", "成交量温和放大"], "indicators": {"ma5": 1498.2, "ma20": 1474.5, "rsi": 63.2}},
        {"code": "300750", "name": "宁德时代", "trade_date": trade_date, "price": 238.16, "change_pct": 2.41, "score": 88, "strategy_name": "趋势强度", "industry": "电池", "reasons": ["MACD金叉", "近5日涨幅领先"], "indicators": {"ma5": 232.8, "ma20": 225.1, "rsi": 68.4}},
        {"code": "601318", "name": "中国平安", "trade_date": trade_date, "price": 48.76, "change_pct": -0.32, "score": 81, "strategy_name": "价值筛选", "industry": "保险", "reasons": ["估值处于历史低位", "股息率较稳定"], "indicators": {"pe": 9.8, "pb": 0.92, "dividend_yield": 4.1}},
        {"code": "002594", "name": "比亚迪", "trade_date": trade_date, "price": 276.50, "change_pct": 0.74, "score": 79, "strategy_name": "动量突破", "industry": "汽车整车", "reasons": ["突破60日压力位"], "indicators": {"ma20": 269.4, "rsi": 59.7}},
    ]


def run_selection(trade_date: str | None = None) -> list[dict]:
    trade_date = trade_date or date.today().isoformat()
    try:
        module = import_module("existing.selection_script")
        runner = getattr(module, "run_selection")
        raw = runner(trade_date)
        return [_normalise(item, trade_date) for item in raw]
    except ModuleNotFoundError:
        return _demo_results(trade_date)


def _normalise(item: dict, trade_date: str) -> dict:
    return {
        "code": str(item.get("code", "")).replace("SH", "").replace("SZ", "").upper(),
        "name": item.get("name") or item.get("stock_name") or "未命名股票",
        "trade_date": item.get("trade_date") or trade_date,
        "price": item.get("price"),
        "change_pct": item.get("change_pct") or item.get("change"),
        "score": item.get("score", 0),
        "strategy_name": item.get("strategy_name", "默认策略"),
        "industry": item.get("industry"),
        "reasons": item.get("reasons", []),
        "indicators": item.get("indicators", {}),
    }
