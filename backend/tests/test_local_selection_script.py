from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "existing" / "selection_script.py"
SPEC = importlib.util.spec_from_file_location("local_selection_script", SCRIPT_PATH)
assert SPEC and SPEC.loader
selection_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection_script)


def _bars(periods: int = 90) -> list[dict]:
    dates = pd.bdate_range("2026-01-01", periods=periods)
    close = np.linspace(10, 30, periods) + np.sin(np.arange(periods) / 4) * 0.1
    return pd.DataFrame({
        "code": "600001", "name": "测试股份", "trade_date": dates,
        "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": np.linspace(1_000_000, 2_500_000, periods),
    }).to_dict(orient="records")


def test_run_selection_returns_import_compatible_items(monkeypatch):
    trade_date = pd.Timestamp(_bars()[-1]["trade_date"]).date().isoformat()
    monkeypatch.setattr(
        selection_script, "_load_market_bars",
        lambda target: ([{"code": "600001", "name": "测试股份", "industry": "测试行业"}], _bars()),
    )
    config = selection_script.engine._load_config()["builtin"]
    monkeypatch.setattr(selection_script.engine, "_load_config", lambda: {"builtin": {**config, "minimum_score": 0}})

    items = selection_script.run_selection(trade_date)

    assert items
    assert {"code", "name", "score", "trade_date", "strategy_name", "price", "change_pct", "industry", "reasons", "indicators"} <= items[0].keys()
    assert items[0]["trade_date"] == trade_date
    assert items[0]["industry"] == "测试行业"
    assert isinstance(items[0]["indicators"], dict)


def test_run_selection_raises_a_diagnostic_error_when_data_is_missing(monkeypatch):
    monkeypatch.setattr(selection_script, "_load_market_bars", lambda target: (_ for _ in ()).throw(selection_script.LocalSelectionDataError("腾讯不可用")))

    with pytest.raises(selection_script.LocalSelectionDataError, match="腾讯不可用"):
        selection_script.run_selection("2026-08-07")


def test_run_selection_rejects_invalid_dates():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        selection_script.run_selection("20260807")


def test_run_selection_normalises_weekend_to_latest_trading_date(monkeypatch):
    observed: list[str] = []
    friday_bars = _bars()
    friday_bars[-1]["trade_date"] = pd.Timestamp("2026-08-07")
    monkeypatch.setattr(
        selection_script, "_load_market_bars",
        lambda target: (observed.append(target) or [{"code": "600001", "name": "测试股份"}], friday_bars),
    )
    config = selection_script.engine._load_config()["builtin"]
    monkeypatch.setattr(selection_script.engine, "_load_config", lambda: {"builtin": {**config, "minimum_score": 0}})

    items = selection_script.run_selection("2026-08-08")

    assert observed == ["2026-08-07"]
    assert items and {item["trade_date"] for item in items} == {"2026-08-07"}
