from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DataT = TypeVar("DataT")


class APIResponse(BaseModel, Generic[DataT]):
    """The envelope returned by every public REST endpoint."""

    code: int = 0
    data: DataT
    message: str = ""


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
    model_config = ConfigDict(populate_by_name=True)

    trade_date: date | None = Field(default=None, alias="date")


class HealthData(BaseModel):
    status: str
    service: str


class StockSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    industry: str | None = None
    list_date: date | None = None
    is_st: bool


class StockPage(BaseModel):
    items: list[StockSummary]
    page: int
    size: int
    total: int


class StockDetail(StockSummary):
    latest_quote: Quote | None = None


class SelectionPage(BaseModel):
    date: date
    strategy: str | None = None
    items: list[SelectionResult]
    count: int


class RunSelectionAccepted(BaseModel):
    status: str
    date: date
    message: str


class SelectionImportItem(BaseModel):
    """One locally generated selection result accepted by the import endpoint."""

    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=128)
    score: float
    price: float | None = None
    change_pct: float | None = None
    strategy_name: str = Field(default="默认策略", min_length=1, max_length=128)
    industry: str | None = Field(default=None, max_length=128)
    reasons: list[str] = Field(default_factory=list)
    indicators: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score")
    @classmethod
    def score_must_be_finite_and_in_range(cls, value: float) -> float:
        if not isfinite(value) or not 0 <= value <= 100:
            raise ValueError("score must be a finite number between 0 and 100")
        return value


class SelectionImportRequest(BaseModel):
    trade_date: date
    items: list[SelectionImportItem] = Field(min_length=1)


class SelectionImportResult(BaseModel):
    date: date
    count: int


class QuoteImportItem(BaseModel):
    """One verified daily OHLCV bar uploaded by the local selector host."""

    stock_code: str = Field(pattern=r"^\d{6}$")
    stock_name: str = Field(min_length=1, max_length=128)
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def values_must_be_finite_and_non_negative(cls, value: float) -> float:
        if not isfinite(value) or value < 0:
            raise ValueError("OHLCV values must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def high_must_not_be_less_than_low(self) -> "QuoteImportItem":
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        return self


class QuoteImportRequest(BaseModel):
    quotes: list[QuoteImportItem] = Field(min_length=1, max_length=5000)


class QuoteImportResult(BaseModel):
    count: int
    start_date: date
    end_date: date
