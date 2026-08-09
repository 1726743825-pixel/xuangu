from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

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
    assert not {"ma5", "ma10", "ma20", "ma60", "dif", "dea", "macd"}.intersection(result[0]["signals"])


def test_builtin_selection_ignores_ma_and_macd_input_values():
    plain = _bars()
    decorated = [{**row, "ma5": -999, "ma10": 999, "ma20": 999, "ma60": 999, "dif": -999, "dea": 999, "macd": -999} for row in plain]
    config = {**engine._load_config()["builtin"], "minimum_score": 0}
    target = pd.Timestamp(plain[-1]["trade_date"]).date().isoformat()

    plain_result = engine._builtin_selection(engine._as_frame(plain), target, config)
    decorated_result = engine._builtin_selection(engine._as_frame(decorated), target, config)

    assert plain_result == decorated_result


@pytest.mark.parametrize("code", ["300001", "301001"])
def test_chinext_codes_are_accepted_and_scored(code: str):
    bars = engine._as_frame(_bars(code=code))
    config = {**engine._load_config()["builtin"], "minimum_score": 0}
    target = bars["trade_date"].max().date().isoformat()

    result = engine._builtin_selection(bars, target, config)

    assert result
    assert result[0]["stock_code"] == code
    assert result[0]["score"] >= 0


def test_public_strategy_runner_is_disabled_without_reading_market_data(monkeypatch):
    monkeypatch.setattr(
        engine.market_dao,
        "read_daily_bars",
        lambda **kwargs: pytest.fail("disabled internal strategy must not read market data"),
    )

    assert engine.run_selection("2026-08-07") == []


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
