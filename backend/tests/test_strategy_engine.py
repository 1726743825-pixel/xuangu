from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategy import engine


def _bars(code: str = "600001", periods: int = 90) -> list[dict]:
    dates = pd.bdate_range("2026-01-01", periods=periods)
    close = np.linspace(10, 30, periods) + np.sin(np.arange(periods) / 4) * 0.1
    return pd.DataFrame(
        {
            "stock_code": code,
            "stock_name": "测试股份",
            "trade_date": dates,
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.linspace(1_000_000, 2_500_000, periods),
        }
    ).to_dict(orient="records")


def test_builtin_selection_returns_unified_shape():
    bars = engine._as_frame(_bars())
    config = engine._load_config()["builtin"]
    config = {**config, "minimum_score": 0}
    target = bars["trade_date"].max().date().isoformat()

    result = engine._builtin_selection(bars, target, config)

    assert result
    assert set(result[0]) == {
        "stock_code", "stock_name", "strategy_name", "trade_date", "signals", "score"
    }
    assert isinstance(result[0]["signals"], dict)


def test_custom_result_normalisation():
    result = engine._normalise_custom(
        [{"code": "SH600519", "name": "贵州茅台", "score": 88, "indicators": {"ma20": 1}}],
        "2026-08-08",
    )

    assert result[0]["stock_code"] == "600519"
    assert result[0]["signals"] == {"ma20": 1}
    assert result[0]["strategy_name"] == "用户自定义策略"


def test_calculate_win_rate_uses_dao(monkeypatch):
    bars = _bars(periods=20)
    first_date = pd.Timestamp(bars[0]["trade_date"]).date().isoformat()
    last_date = pd.Timestamp(bars[-1]["trade_date"]).date().isoformat()
    monkeypatch.setattr(
        engine.market_dao,
        "read_strategy_selections",
        lambda strategy_name, start_date, end_date: [
            {"stock_code": "600001", "trade_date": first_date}
        ],
    )
    monkeypatch.setattr(engine.market_dao, "read_daily_bars", lambda start_date, end_date: bars)

    result = engine.calculate_win_rate("测试策略", first_date, last_date)

    assert result["sample_count"] == 1
    assert result["win_count"] == 1
    assert result["win_rate"] == 1.0
