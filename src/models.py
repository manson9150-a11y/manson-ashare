from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Quote(Record):
    code: str = Field(pattern=r"^\d{6}$")
    name: str
    price: float = Field(gt=0)
    previous_close: float = Field(gt=0)
    open: float = Field(ge=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    volume: float = Field(ge=0)
    amount: float = Field(ge=0)
    change_pct: float
    turnover: float | None = None
    volume_ratio: float | None = None
    float_cap: float | None = None
    timestamp: datetime
    fetched_at: datetime
    source: str
    reliability: float = 0.8
    fallback: bool = False
    cached: bool = False
    suspended: bool = False
    industry: str | None = None
    limit_up_price: float | None = None
    limit_down_price: float | None = None
    @field_validator("timestamp", "fetched_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("timezone required")
        return value

class Event(Record):
    event_id: str
    stock_code: str = Field(pattern=r"^\d{6}$")
    event_type: str
    title: str
    event_time: datetime
    publish_time: datetime
    publish_time_precision: Literal['second', 'date'] = 'second'
    first_seen_at: datetime | None = None
    source: str
    url: str
    reliability: float = Field(ge=0, le=1)
    freshness: float = Field(default=0, ge=0, le=1)
    directness: float = Field(default=0, ge=0, le=1)
    priced_in_score: float | None = None
    impact_score: float | None = Field(default=None, ge=0, le=100)
    verified: bool = False
    canonical_id: str | None = None
    document_url: str | None = None
    verification: dict | None = None
    @field_validator("publish_time", "event_time", "first_seen_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone required")
        return value

class SourceLog(Record):
    source_name: str
    operation: str
    success: bool
    fetched_at: str
    timestamp: str | None = None
    reliability_level: float
    fallback_priority: int
    is_fallback: bool
    count: int = 0
    error: str | None = None
    http_status: int | None = None
