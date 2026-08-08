from __future__ import annotations

from datetime import datetime, timedelta
import math


def get_quote(code: str) -> dict:
    return {"code": code, "name": "", "price": None, "change_pct": None, "updated_at": datetime.now().isoformat()}


def get_kline(code: str, days: int = 60) -> list[dict]:
    base = 100 + (sum(ord(ch) for ch in code) % 80)
    result = []
    closes = []
    for index in range(days):
        value = base + math.sin(index / 4) * 7 + index * 0.16
        closes.append(value)
        window5 = closes[max(0, index - 4):]
        window20 = closes[max(0, index - 19):]
        result.append({"date": (datetime.now() - timedelta(days=days - index)).strftime("%m-%d"), "open": round(value - 1.2, 2), "close": round(value, 2), "high": round(value + 2.1, 2), "low": round(value - 2.4, 2), "volume": round(3000000 + index * 32000), "ma5": round(sum(window5) / len(window5), 2), "ma20": round(sum(window20) / len(window20), 2)})
    return result


def get_messages(code: str) -> list[dict]:
    return [{"title": f"{code} 近期市场动态（演示数据）", "source": "数据适配器", "published_at": datetime.now().isoformat(), "summary": "将行情/消息 skill 放入项目后，这里会自动替换为真实消息。"}]
