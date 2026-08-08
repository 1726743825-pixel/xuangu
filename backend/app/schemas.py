from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SelectionResult(BaseModel):
    code: str
    name: str
    trade_date: str
    price: float | None = None
    change_pct: float | None = None
    score: float | None = None
    strategy_name: str = "默认策略"
    industry: str | None = None
    reasons: list[str] = Field(default_factory=list)
    indicators: dict[str, Any] = Field(default_factory=dict)


class Quote(BaseModel):
    code: str
    name: str
    price: float | None = None
    change_pct: float | None = None
    updated_at: str


class KlinePoint(BaseModel):
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    ma5: float | None = None
    ma20: float | None = None


class Message(BaseModel):
    title: str
    source: str
    published_at: str
    url: str | None = None
    summary: str | None = None


class JobRun(BaseModel):
    id: int
    status: str
    trade_date: str
    started_at: str
    finished_at: str | None = None
    result_count: int = 0
    error: str | None = None


class RunSelectionRequest(BaseModel):
    trade_date: str | None = None
