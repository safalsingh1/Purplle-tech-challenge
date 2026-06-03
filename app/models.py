"""
models.py — SQLAlchemy ORM models and Pydantic API schemas.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Any, List
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, Index
)
from sqlalchemy.sql import func

from app.database import Base


# ─── SQLAlchemy ORM Models ────────────────────────────────────────────────────

class Event(Base):
    """Stores all ingest events — indexed for fast metric queries."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(36), unique=True, nullable=False, index=True)
    store_id = Column(String(50), nullable=False, index=True)
    camera_id = Column(String(50), nullable=False)
    visitor_id = Column(String(50), nullable=False, index=True)
    event_type = Column(String(30), nullable=False, index=True)
    timestamp = Column(String(30), nullable=False, index=True)
    zone_id = Column(String(50), nullable=True)
    dwell_ms = Column(Integer, default=0)
    is_staff = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)
    queue_depth = Column(Integer, nullable=True)
    sku_zone = Column(String(50), nullable=True)
    session_seq = Column(Integer, default=0)
    ingested_at = Column(DateTime, default=func.now())
    # Enriched demographic fields (from updated resource schema)
    gender_pred = Column(String(10), nullable=True)   # M / F / null
    age_pred = Column(Integer, nullable=True)
    age_bucket = Column(String(20), nullable=True)    # e.g. "25-34"
    group_id = Column(String(50), nullable=True)
    group_size = Column(Integer, nullable=True)
    # Queue enrichment
    queue_join_ts = Column(String(30), nullable=True)
    queue_served_ts = Column(String(30), nullable=True)
    queue_exit_ts = Column(String(30), nullable=True)
    wait_seconds = Column(Integer, nullable=True)
    queue_position_at_join = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_events_store_type", "store_id", "event_type"),
        Index("ix_events_store_visitor", "store_id", "visitor_id"),
        Index("ix_events_store_ts", "store_id", "timestamp"),
    )


class POSTransaction(Base):
    """Stores POS transactions for conversion rate correlation."""
    __tablename__ = "pos_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(50), unique=True, nullable=False)
    store_id = Column(String(50), nullable=False, index=True)
    timestamp = Column(String(30), nullable=False)
    basket_value_inr = Column(Float, default=0.0)

    __table_args__ = (
        Index("ix_pos_store_ts", "store_id", "timestamp"),
    )


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

VALID_EVENT_TYPES = {
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT",
    "ZONE_DWELL", "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON", "REENTRY"
}

# Mapping from new resource schema event_type names → our canonical names
EVENT_TYPE_ALIASES = {
    "entry": "ENTRY",
    "exit": "EXIT",
    "zone_entered": "ZONE_ENTER",
    "zone_exited": "ZONE_EXIT",
    "zone_dwell": "ZONE_DWELL",
    "queue_join": "BILLING_QUEUE_JOIN",
    "queue_completed": "BILLING_QUEUE_JOIN",
    "queue_abandoned": "BILLING_QUEUE_ABANDON",
    "queue_abandon": "BILLING_QUEUE_ABANDON",
    "reentry": "REENTRY",
}


class EventMetadataIn(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = 0

    model_config = {"extra": "allow"}


class EventIn(BaseModel):
    """Pydantic schema for event ingestion — accepts both legacy and new resource schemas."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: Optional[str] = None      # canonical; also accept store_code below
    store_code: Optional[str] = None    # new schema alias for store_id
    camera_id: Optional[str] = None
    visitor_id: Optional[str] = None    # canonical; also accept id_token below
    id_token: Optional[str] = None      # new schema alias for visitor_id
    track_id: Optional[Any] = None      # new schema integer track id
    event_type: str
    timestamp: Optional[str] = None     # canonical; also accept event_timestamp / event_time
    event_timestamp: Optional[str] = None   # new schema entry/exit timestamp
    event_time: Optional[str] = None        # new schema zone event timestamp
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: EventMetadataIn = Field(default_factory=EventMetadataIn)
    # Demographic enrichment fields (new resource schema)
    gender_pred: Optional[str] = None
    gender: Optional[str] = None        # alias used in zone events
    age_pred: Optional[int] = None
    age: Optional[int] = None           # alias used in zone events
    age_bucket: Optional[str] = None
    group_id: Optional[str] = None
    group_size: Optional[int] = None
    # Queue enrichment fields
    queue_join_ts: Optional[str] = None
    queue_served_ts: Optional[str] = None
    queue_exit_ts: Optional[str] = None
    wait_seconds: Optional[int] = None
    queue_position_at_join: Optional[int] = None
    abandoned: Optional[bool] = None
    queue_event_id: Optional[str] = None

    model_config = {"extra": "allow"}

    @field_validator("event_type", mode="before")
    @classmethod
    def normalize_event_type(cls, v: str) -> str:
        """Accept both canonical (ENTRY) and new schema names (entry, zone_entered)."""
        normalized = EVENT_TYPE_ALIASES.get(str(v).lower(), v.upper() if isinstance(v, str) else v)
        if normalized not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type '{v}'. Must be one of: {sorted(VALID_EVENT_TYPES)}")
        return normalized

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid timestamp format: {v}. Expected ISO-8601.")
        return v

    @field_validator("store_id", mode="before")
    @classmethod
    def validate_store_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v or not (v.startswith("STORE_") or v.startswith("ST") or v.startswith("store_")):
            raise ValueError(f"Invalid store_id: '{v}'. Must start with 'STORE_', 'ST', or 'store_'.")
        return v


class IngestBatch(BaseModel):
    events: List[EventIn] = Field(max_length=500)


class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    duplicate: int
    errors: List[dict] = []


# ─── API Response Schemas ────────────────────────────────────────────────────

class ZoneDwellMetric(BaseModel):
    zone_id: str
    avg_dwell_seconds: float
    visit_count: int


class StoreMetrics(BaseModel):
    store_id: str
    unique_visitors: int
    active_visitors: int
    conversion_rate: float           # 0.0–1.0
    avg_dwell_per_zone: List[ZoneDwellMetric]
    queue_depth: int
    abandonment_rate: float          # 0.0–1.0
    computed_at: str


class FunnelStage(BaseModel):
    stage: str
    count: int
    drop_off_pct: float


class FunnelResponse(BaseModel):
    store_id: str
    stages: List[FunnelStage]
    computed_at: str


class HeatmapZone(BaseModel):
    zone_id: str
    normalised_score: float          # 0–100
    visit_count: int
    avg_dwell_seconds: float
    sku_zone: Optional[str]


class HeatmapResponse(BaseModel):
    store_id: str
    zones: List[HeatmapZone]
    data_confidence: bool            # False if < 20 sessions
    computed_at: str


class Anomaly(BaseModel):
    anomaly_id: str
    anomaly_type: str                # BILLING_QUEUE_SPIKE | CONVERSION_DROP | DEAD_ZONE | STALE_FEED
    severity: str                    # INFO | WARN | CRITICAL
    description: str
    suggested_action: str
    detected_at: str
    zone_id: Optional[str] = None
    value: Optional[float] = None    # e.g. current queue depth or conversion rate


class AnomaliesResponse(BaseModel):
    store_id: str
    anomalies: List[Anomaly]
    checked_at: str


class StoreHealth(BaseModel):
    store_id: str
    last_event_timestamp: Optional[str]
    lag_seconds: Optional[float]
    status: str                      # HEALTHY | STALE_FEED | NO_DATA


class HealthResponse(BaseModel):
    service_status: str              # UP | DEGRADED | DOWN
    database_status: str             # OK | ERROR
    stores: List[StoreHealth]
    checked_at: str
