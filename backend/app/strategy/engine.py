from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List

import numpy as np
import pandas as pd

from .. import db as market_dao


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = BACKEND_ROOT / "config" / "strategy.json"
CUSTOM_STRATEGY_PATH = BACKEND_ROOT / "existing" / "selection_script.py"
REQUIRED_BAR_COLUMNS = {
    "stock_code", "stock_name", "trade_date", "open", "high", "low", "close", "volume"
}


def _load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict) or "builtin" not in config or "backtest" not in config:
        raise ValueError(f"策略配置格式无效: {path}")
    return config


def _validate_date(value: str, field: str = "trade_date") -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须为 YYYY-MM-DD 格式") from exc


def _as_frame(raw: Any) -> pd.DataFrame:
    frame = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
    if frame.empty and not len(frame.columns):
        return pd.DataFrame(columns=sorted(REQUIRED_BAR_COLUMNS))
    aliases = {
        "code": "stock_code", "name": "stock_name", "date": "trade_date",
        "vol": "volume", "turnover": "turnover_rate", "float_mv": "float_market_cap",
    }
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
    missing = REQUIRED_BAR_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"DAO 行情数据缺少字段: {', '.join(sorted(missing))}")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["stock_code"] = (
        frame["stock_code"].astype(str).str.upper().str.replace(r"^(SH|SZ)", "", regex=True).str.zfill(6)
    )
    frame["stock_name"] = frame["stock_name"].fillna("未命名股票").astype(str)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    numeric = ["open", "high", "low", "close", "volume", "turnover_rate", "float_market_cap"]
    for column in set(numeric).intersection(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values(["stock_code", "trade_date"]).drop_duplicates(
        ["stock_code", "trade_date"], keep="last"
    )


def _linear(value: pd.Series, low: float, high: float, maximum: float) -> pd.Series:
    if low < high:
        return ((value - low) / (high - low) * maximum).clip(0, maximum).fillna(0.0)
    return ((low - value) / (low - high) * maximum).clip(0, maximum).fillna(0.0)


def _indicators(bars: pd.DataFrame) -> pd.DataFrame:
    data = bars.copy()
    grouped = data.groupby("stock_code", sort=False, observed=True)
    volume = grouped["volume"]
    data["vol_ma5"] = volume.transform(lambda values: values.rolling(5, min_periods=5).mean())
    data["vol_ma10"] = volume.transform(lambda values: values.rolling(10, min_periods=10).mean())
    data["volume_ratio_5"] = data["volume"] / data["vol_ma5"]
    data["volume_ratio_10"] = data["volume"] / data["vol_ma10"]

    low9 = grouped["low"].transform(lambda values: values.rolling(9, min_periods=9).min())
    high9 = grouped["high"].transform(lambda values: values.rolling(9, min_periods=9).max())
    spread = (high9 - low9).replace(0, np.nan)
    rsv = ((data["close"] - low9) / spread * 100).fillna(50.0)
    data["kdj_k"] = rsv.groupby(data["stock_code"], sort=False).transform(
        lambda values: values.ewm(alpha=1 / 3, adjust=False).mean()
    )
    data["kdj_d"] = data.groupby("stock_code", sort=False, observed=True)["kdj_k"].transform(
        lambda values: values.ewm(alpha=1 / 3, adjust=False).mean()
    )
    data["kdj_j"] = 3 * data["kdj_k"] - 2 * data["kdj_d"]
    data["change_pct"] = grouped["close"].pct_change(fill_method=None) * 100
    data["history_count"] = grouped.cumcount() + 1
    return data


def _builtin_selection(bars: pd.DataFrame, trade_date: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    if bars.empty:
        return []
    data = _indicators(bars)
    grouped = data.groupby("stock_code", sort=False, observed=True)
    data["volume_prev"] = grouped["volume"].shift(1)
    data["close_prev"] = grouped["close"].shift(1)
    data["high_10_prev"] = grouped["high"].transform(
        lambda values: values.shift(1).rolling(10, min_periods=10).max()
    )

    current = data.loc[data["trade_date"].eq(pd.Timestamp(trade_date))].copy()
    if current.empty:
        return []

    allowed_prefixes = tuple(str(value) for value in config["universe"]["allowed_prefixes"])
    excluded_prefixes = tuple(str(value) for value in config["universe"]["excluded_prefixes"])
    universe = (
        current["stock_code"].str.startswith(allowed_prefixes)
        & ~current["stock_code"].str.startswith(excluded_prefixes)
        & ~current["stock_name"].str.upper().str.contains("ST", regex=False)
    )
    hard_filter = universe & current["history_count"].ge(
        int(config["filters"]["minimum_history_days"])
    )

    k_score = np.where(
        current["kdj_k"].gt(current["kdj_d"]),
        np.where(current["kdj_k"].gt(50), 3 + _linear(current["kdj_k"], 50, 70, 2), _linear(current["kdj_k"], 0, 50, 3)),
        0.0,
    )
    kdj_score = pd.Series(k_score, index=current.index) + _linear(current["kdj_j"], 150, 100, 5)
    volume_score = (
        _linear(current["volume"] / current["vol_ma5"], 1, 2.5, 7)
        + _linear(current["volume"] / current["vol_ma10"], 1, 2, 6)
        + _linear((current["volume"] / current["volume_prev"] - 1) * 100, 0, 50, 2)
    )
    breakout = (current["close"] / current["high_10_prev"] - 1) * 100
    body = (current["close"] - current["open"]) / current["open"] * 100
    close_position = (current["close"] - current["low"]) / (current["high"] - current["low"]).replace(0, np.nan)
    price_score = _linear(breakout, 0, 8, 5) + _linear(body, 0, 5, 4) + _linear(close_position, 0.5, 1, 3)

    # Legacy source scoring retains KDJ (10), volume (15), and K-line action
    # (12).  Normalise the remaining 37-point technical subtotal to 100.
    component_max = float(sum(config["weights"].values()))
    current["score"] = ((kdj_score + volume_score + price_score) / component_max * 100).clip(0, 100).round(2)
    selected = current.loc[hard_filter & current["score"].ge(float(config["minimum_score"]))].nlargest(
        int(config["top_n"]), "score"
    )
    if selected.empty:
        return []

    signal_columns = ["close", "change_pct", "volume", "volume_ratio_5", "volume_ratio_10", "kdj_k", "kdj_d", "kdj_j"]
    rounded = selected[signal_columns].round(4).replace({np.nan: None})
    signals = rounded.to_dict(orient="records")
    result = selected[["stock_code", "stock_name", "score"]].copy()
    result["strategy_name"] = str(config["name"])
    result["trade_date"] = trade_date
    result["signals"] = signals
    return result[["stock_code", "stock_name", "strategy_name", "trade_date", "signals", "score"]].to_dict(orient="records")


def _load_custom_module(path: Path) -> ModuleType | None:
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("xuangu_user_selection_strategy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载自定义策略: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalise_custom(raw: Any, trade_date: str) -> list[dict[str, Any]]:
    frame = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw or [])
    if frame.empty:
        return []
    frame = frame.rename(columns={"code": "stock_code", "name": "stock_name", "indicators": "signals"})
    missing = {"stock_code", "stock_name"}.difference(frame.columns)
    if missing:
        raise ValueError(f"自定义策略结果缺少字段: {', '.join(sorted(missing))}")
    frame["stock_code"] = frame["stock_code"].astype(str).str.upper().str.replace(r"^(SH|SZ)", "", regex=True).str.zfill(6)
    frame["stock_name"] = frame["stock_name"].fillna("未命名股票").astype(str)
    if "strategy_name" not in frame:
        frame["strategy_name"] = "用户自定义策略"
    else:
        frame["strategy_name"] = frame["strategy_name"].fillna("用户自定义策略")
    frame["trade_date"] = frame.get("trade_date", trade_date).fillna(trade_date) if "trade_date" in frame else trade_date
    if "score" not in frame:
        frame["score"] = 0.0
    else:
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce").fillna(0.0).clip(0, 100)
    if "signals" not in frame:
        frame["signals"] = [{} for _ in range(len(frame))]
    frame["signals"] = frame["signals"].map(lambda value: value if isinstance(value, dict) else {})
    return frame[["stock_code", "stock_name", "strategy_name", "trade_date", "signals", "score"]].to_dict(orient="records")


def run_selection(trade_date: str) -> List[Dict]:
    """Run configured built-in and optional user strategies for one trading day."""
    target = _validate_date(trade_date)
    config = _load_config()
    results: list[dict[str, Any]] = []

    builtin = config["builtin"]
    if builtin.get("enabled", True):
        lookback_days = int(builtin["filters"]["minimum_history_days"]) * 2
        start_date = (datetime.strptime(target, "%Y-%m-%d").date() - timedelta(days=lookback_days)).isoformat()
        bars = _as_frame(market_dao.read_daily_bars(start_date=start_date, end_date=target))
        results.extend(_builtin_selection(bars, target, builtin))

    custom = config.get("custom", {})
    if custom.get("enabled", True):
        module = _load_custom_module(CUSTOM_STRATEGY_PATH)
        if module is not None:
            runner: Callable[..., Any] | None = getattr(module, "run_selection", None)
            if not callable(runner):
                raise AttributeError(f"{CUSTOM_STRATEGY_PATH} 必须定义可调用的 run_selection(trade_date)")
            results.extend(_normalise_custom(runner(target), target))

    return sorted(results, key=lambda item: float(item["score"]), reverse=True)


def calculate_win_rate(strategy_name: str, start_date: str, end_date: str) -> dict[str, Any]:
    """Calculate forward-return win rate for persisted selections of a strategy."""
    start = _validate_date(start_date, "start_date")
    end = _validate_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date 不能晚于 end_date")
    config = _load_config()["backtest"]
    holding_days = int(config["holding_days"])
    selections = pd.DataFrame(market_dao.read_strategy_selections(strategy_name, start, end))
    if selections.empty:
        return {"strategy_name": strategy_name, "start_date": start, "end_date": end, "sample_count": 0, "win_count": 0, "win_rate": 0.0, "average_return": 0.0}
    selections = selections.rename(columns={"code": "stock_code", "date": "trade_date"})
    required = {"stock_code", "trade_date"}
    if not required.issubset(selections.columns):
        raise ValueError("DAO 历史选股结果必须包含 stock_code 和 trade_date")
    future_end = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=holding_days * 3)).isoformat()
    bars = _as_frame(market_dao.read_daily_bars(start_date=start, end_date=future_end))
    bars["exit_close"] = bars.groupby("stock_code", sort=False, observed=True)["close"].shift(-holding_days)
    bars["forward_return"] = bars["exit_close"] / bars["close"] - 1
    selections["trade_date"] = pd.to_datetime(selections["trade_date"]).dt.normalize()
    joined = selections.merge(bars[["stock_code", "trade_date", "forward_return"]], on=["stock_code", "trade_date"], how="left").dropna(subset=["forward_return"])
    threshold = float(config["win_return_threshold"])
    sample_count = int(len(joined))
    win_count = int(joined["forward_return"].gt(threshold).sum())
    return {
        "strategy_name": strategy_name, "start_date": start, "end_date": end,
        "holding_days": holding_days, "sample_count": sample_count, "win_count": win_count,
        "win_rate": round(win_count / sample_count, 4) if sample_count else 0.0,
        "average_return": round(float(joined["forward_return"].mean()), 6) if sample_count else 0.0,
    }
