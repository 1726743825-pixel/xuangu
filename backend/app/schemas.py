from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any, Generic, Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


DataT = TypeVar("DataT")


MARKET_INDEX_DEFINITIONS = (
    ("上证指数", "000001.SH"),
    ("深证成指", "399001.SZ"),
    ("创业板指", "399006.SZ"),
    ("科创50", "000688.SH"),
)
_MARKET_INDEX_ALIASES = {
    "000001.SH": "000001.SH", "000001": "000001.SH", "sh000001": "000001.SH",
    "399001.SZ": "399001.SZ", "399001": "399001.SZ", "sz399001": "399001.SZ",
    "399006.SZ": "399006.SZ", "399006": "399006.SZ", "sz399006": "399006.SZ",
    "000688.SH": "000688.SH", "000688": "000688.SH", "sh000688": "000688.SH",
}
_MARKET_INDEX_NAMES = {code: name for name, code in MARKET_INDEX_DEFINITIONS}


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
    selection_price: float | None = None
    selection_price_date: date | None = None
    current_price: float | None = None
    current_price_as_of: datetime | None = None
    change_pct: float | None = None
    score: float | None = None
    display_score: float | None = None
    display_score_max: float | None = None
    rating_level: str | None = None
    rating: str | None = None
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
    selection_price: float | None = None
    selection_price_date: date | None = Field(
        default=None, validation_alias=AliasChoices("selection_price_date", "price_date")
    )
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

    @field_validator("price", "selection_price", "change_pct", "turnover_rate")
    @classmethod
    def optional_numbers_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("selection numeric fields must be finite")
        return value

    @field_validator("price", "selection_price", "turnover_rate")
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

    @model_validator(mode="after")
    def keep_legacy_and_fixed_selection_price_aligned(self) -> "SelectionImportItem":
        if self.selection_price is None and self.price is not None:
            self.selection_price = self.price
        elif self.price is None and self.selection_price is not None:
            self.price = self.selection_price
        if self.selection_price is None and self.selection_price_date is not None:
            raise ValueError("selection_price_date requires selection_price")
        return self


class SelectionImportRequest(BaseModel):
    trade_date: date
    items: list[SelectionImportItem] = Field(min_length=1)
    replace_existing: bool = False

    @model_validator(mode="after")
    def replacement_must_target_one_strategy(self) -> "SelectionImportRequest":
        if self.replace_existing and len({item.strategy_name for item in self.items}) != 1:
            raise ValueError("replace_existing requires all items to use one strategy_name")
        for item in self.items:
            if item.selection_price_date is not None and item.selection_price_date > self.trade_date:
                raise ValueError("selection_price_date must not be after trade_date")
        return self


class SelectionImportResult(BaseModel):
    date: date
    count: int


class MarketIndexItem(BaseModel):
    name: str
    code: str
    price: float | None = None
    change_pct: float | None = None
    as_of: datetime | None = None


class MarketIndices(BaseModel):
    items: list[MarketIndexItem]


class MarketIndexSnapshotImportItem(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str
    available: bool
    price: float | None = None
    change_pct: float | None = None
    as_of: datetime | None = Field(
        default=None, validation_alias=AliasChoices("as_of", "observed_at")
    )
    source: str = Field(pattern=r"^akshare-[A-Za-z0-9._-]+$")

    @field_validator("code")
    @classmethod
    def normalise_index_code(cls, value: str) -> str:
        canonical = _MARKET_INDEX_ALIASES.get(value)
        if canonical is None:
            raise ValueError("unsupported market index code")
        return canonical

    @field_validator("price")
    @classmethod
    def price_must_be_finite_and_positive(cls, value: float | None) -> float | None:
        if value is not None and (not isfinite(value) or value <= 0):
            raise ValueError("snapshot price must be finite and positive")
        return value

    @field_validator("change_pct")
    @classmethod
    def change_pct_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("snapshot change_pct must be finite")
        return value

    @field_validator("as_of")
    @classmethod
    def normalise_as_of(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        shanghai = ZoneInfo("Asia/Shanghai")
        return value.replace(tzinfo=shanghai) if value.tzinfo is None else value.astimezone(shanghai)

    @model_validator(mode="after")
    def name_must_match_fixed_index(self) -> "MarketIndexSnapshotImportItem":
        if self.name != _MARKET_INDEX_NAMES[self.code]:
            raise ValueError("market index name does not match code")
        if self.available and any(
            value is None for value in (self.price, self.change_pct, self.as_of)
        ):
            raise ValueError("available market index requires price, change_pct and as_of")
        return self


class StockSnapshotImportItem(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=1, max_length=128)
    price: float
    change_pct: float
    as_of: datetime = Field(validation_alias=AliasChoices("as_of", "observed_at"))
    source: str = Field(pattern=r"^akshare-[A-Za-z0-9._-]+$")

    @field_validator("price")
    @classmethod
    def price_must_be_finite_and_positive(cls, value: float) -> float:
        if not isfinite(value) or value <= 0:
            raise ValueError("snapshot price must be finite and positive")
        return value

    @field_validator("change_pct")
    @classmethod
    def change_pct_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("snapshot change_pct must be finite")
        return value

    @field_validator("as_of")
    @classmethod
    def normalise_as_of(cls, value: datetime) -> datetime:
        shanghai = ZoneInfo("Asia/Shanghai")
        return value.replace(tzinfo=shanghai) if value.tzinfo is None else value.astimezone(shanghai)


class MarketSnapshotImportRequest(BaseModel):
    indices: list[MarketIndexSnapshotImportItem] = Field(min_length=4, max_length=4)
    stocks: list[StockSnapshotImportItem] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def require_all_four_indices_once(self) -> "MarketSnapshotImportRequest":
        codes = [item.code for item in self.indices]
        expected = {code for _, code in MARKET_INDEX_DEFINITIONS}
        if len(set(codes)) != 4 or set(codes) != expected:
            raise ValueError("indices must contain each fixed market index exactly once")
        return self


class MarketSnapshotImportResult(BaseModel):
    indices: int
    stocks: int


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
    amount: float | None = None
    source: str | None = Field(default=None, pattern=r"^akshare-[A-Za-z0-9._-]+$")

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def values_must_be_finite_and_non_negative(cls, value: float) -> float:
        if not isfinite(value) or value < 0:
            raise ValueError("OHLCV values must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def enforce_ohlc_invariant(self) -> "QuoteImportItem":
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("OHLC invariant requires low <= open/close <= high")
        return self

    @field_validator("amount")
    @classmethod
    def amount_must_be_finite_and_non_negative(cls, value: float | None) -> float | None:
        if value is not None and (not isfinite(value) or value < 0):
            raise ValueError("amount must be finite and non-negative")
        return value


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
    source: str | None = Field(default=None, pattern=r"^akshare-[A-Za-z0-9._-]+$")

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
    def enforce_ohlc_invariant(self) -> "IntradayQuoteImportItem":
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("OHLC invariant requires low <= open/close <= high")
        return self


class IntradayQuoteImportRequest(BaseModel):
    quotes: list[IntradayQuoteImportItem] = Field(min_length=1, max_length=5000)


class IntradayQuoteImportResult(BaseModel):
    count: int
    start_datetime: datetime
    end_datetime: datetime


class TradeDateCleanupRequest(BaseModel):
    """A deliberately narrow, fully confirmed one-day cleanup command."""

    date: date
    delete_selections: Literal[True]
    delete_daily_quotes: Literal[True]
    delete_intraday_quotes: Literal[True]
    confirm: Literal[True]


class TradeDateCleanupResult(BaseModel):
    date: date
    selection_results_deleted: int
    daily_quotes_deleted: int
    intraday_quotes_deleted: int
