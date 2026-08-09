from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any, Generic, Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


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
    turnover_rate: float | None = None
    board_count: int | None = None
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

    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=128)
    score: float
    price: float | None = None
    change_pct: float | None = Field(default=None, validation_alias=AliasChoices("change_pct", "changePercent"))
    strategy_name: str = Field(default="默认策略", min_length=1, max_length=128)
    industry: str | None = Field(default=None, max_length=128)
    turnover_rate: float | None = Field(default=None, validation_alias=AliasChoices("turnover_rate", "turnoverRate"))
    board_count: int | None = Field(default=None, validation_alias=AliasChoices("board_count", "continuousBoard"))
    reasons: list[str] = Field(default_factory=list)
    indicators: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score")
    @classmethod
    def score_must_be_finite_and_in_range(cls, value: float) -> float:
        if not isfinite(value) or not 0 <= value <= 100:
            raise ValueError("score must be a finite number between 0 and 100")
        return value

    @field_validator("price", "change_pct", "turnover_rate")
    @classmethod
    def optional_numbers_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("selection numeric fields must be finite")
        return value

    @field_validator("price", "turnover_rate")
    @classmethod
    def price_and_turnover_must_not_be_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("price and turnover_rate must not be negative")
        return value

    @field_validator("board_count")
    @classmethod
    def board_count_must_not_be_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("board_count must not be negative")
        return value


class SelectionImportRequest(BaseModel):
    trade_date: date
    items: list[SelectionImportItem] = Field(min_length=1)
    replace_existing: bool = False

    @model_validator(mode="after")
    def replacement_must_target_one_strategy(self) -> "SelectionImportRequest":
        if self.replace_existing and len({item.strategy_name for item in self.items}) != 1:
            raise ValueError("replace_existing requires all items to use one strategy_name")
        return self


class SelectionImportResult(BaseModel):
    date: date
    count: int


class HoldingPeriodReturn(BaseModel):
    label: str
    trading_days: int
    target_date: date | None = None
    close: float | None = None
    return_pct: float | None = None
    status: Literal["ok", "暂无数据"]


class SelectionPerformance(BaseModel):
    code: str
    name: str
    trade_date: date
    strategy_name: str
    base_close: float | None = None
    periods: list[HoldingPeriodReturn]


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


class IntradayQuoteImportItem(BaseModel):
    """A real 30-minute OHLCV bar, normalised to Asia/Shanghai."""

    model_config = ConfigDict(populate_by_name=True)

    stock_code: str = Field(pattern=r"^\d{6}$", validation_alias=AliasChoices("stock_code", "code"))
    stock_name: str | None = Field(default=None, min_length=1, max_length=128, validation_alias=AliasChoices("stock_name", "name"))
    interval: Literal["30m"]
    trade_datetime: datetime = Field(validation_alias=AliasChoices("trade_datetime", "datetime"))
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None
    amount_estimated: bool = Field(validation_alias=AliasChoices("amount_estimated", "estimated"))

    @field_validator("trade_datetime")
    @classmethod
    def normalise_datetime_to_shanghai(cls, value: datetime) -> datetime:
        shanghai = ZoneInfo("Asia/Shanghai")
        if value.tzinfo is None:
            return value.replace(tzinfo=shanghai)
        return value.astimezone(shanghai)

    @field_validator("open", "high", "low", "close", "volume", "amount")
    @classmethod
    def values_must_be_finite_and_non_negative(cls, value: float | None) -> float | None:
        if value is not None and (not isfinite(value) or value < 0):
            raise ValueError("OHLCV and amount values must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def high_must_not_be_less_than_low(self) -> "IntradayQuoteImportItem":
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        return self


class IntradayQuoteImportRequest(BaseModel):
    quotes: list[IntradayQuoteImportItem] = Field(min_length=1, max_length=5000)


class IntradayQuoteImportResult(BaseModel):
    count: int
    start_datetime: datetime
    end_datetime: datetime
