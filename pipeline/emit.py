"""
emit.py — Event schema definition and JSONL event writer.

Defines the canonical StoreEvent Pydantic model and helpers
to construct and persist structured events to disk.
"""

import uuid
import json
from datetime import datetime, timezone
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = 0


class StoreEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str  # ENTRY|EXIT|ZONE_ENTER|ZONE_EXIT|ZONE_DWELL|BILLING_QUEUE_JOIN|BILLING_QUEUE_ABANDON|REENTRY
    timestamp: str  # ISO-8601 UTC
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    # Demographic enrichment (null for face-blurred footage; emitted for schema compliance)
    gender_pred: Optional[str] = None     # M / F / null
    age_pred: Optional[int] = None
    age_bucket: Optional[str] = None      # e.g. "25-34"
    group_id: Optional[str] = None        # shared ID for group entries
    group_size: Optional[int] = None      # number of people in group

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        valid = {
            "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT",
            "ZONE_DWELL", "BILLING_QUEUE_JOIN",
            "BILLING_QUEUE_ABANDON", "REENTRY"
        }
        if v not in valid:
            raise ValueError(f"Invalid event_type: {v}. Must be one of {valid}")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        # Ensure it's valid ISO-8601
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    def to_dict(self) -> dict:
        return self.model_dump()



class EventEmitter:
    """Writes structured events to a JSONL file and optionally pushes to API."""

    def __init__(self, output_path: str, api_url: Optional[str] = None):
        self.output_path = output_path
        self.api_url = api_url
        self._buffer: list[dict] = []
        self._file = open(output_path, "a", encoding="utf-8")

    def emit(self, event: StoreEvent) -> None:
        """Write a single event to the JSONL file."""
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()
        self._buffer.append(event.to_dict())

    def close(self) -> None:
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def frame_to_timestamp(
    clip_start_iso: str,
    frame_number: int,
    fps: float,
) -> str:
    """Convert clip-relative frame number to absolute ISO-8601 UTC timestamp."""
    clip_start = datetime.fromisoformat(clip_start_iso.replace("Z", "+00:00"))
    offset_seconds = frame_number / fps
    ts = clip_start.timestamp() + offset_seconds
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_visitor_id(track_id: int, store_id: str) -> str:
    """Generate a stable, human-readable visitor ID from tracking ID."""
    hash_val = hash(f"{store_id}_{track_id}") & 0xFFFFFF
    return f"VIS_{hash_val:06x}"
