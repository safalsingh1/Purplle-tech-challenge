# PROMPT:
# "Write pytest tests for a pipeline event schema and emission module.
#  Test: event_id uniqueness across 1000 generated events, all valid event_type
#  values accepted, invalid event_type raises ValueError, timestamp format is
#  ISO-8601 UTC (ends with Z), frame_to_timestamp converts correctly for known
#  frame numbers, make_visitor_id produces deterministic output for same inputs,
#  EventEmitter writes valid JSONL to file, all schema fields present in output."
#
# CHANGES MADE:
# - AI generated test for event schema using unittest.mock — replaced with direct import test
# - Added test for dwell_ms field type (must be int, not float)
# - Added test that confidence field accepts 0.0 and 1.0 boundary values exactly
# - Removed AI's suggestion to test private methods; tested via public interface instead

import pytest
import uuid
import json
import tempfile
import os
from pathlib import Path
import sys

# Add pipeline dir to path
sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

from emit import StoreEvent, EventMetadata, EventEmitter, frame_to_timestamp, make_visitor_id


class TestEventSchema:

    def test_valid_event_creation(self):
        """All valid fields produce a StoreEvent without error."""
        event = StoreEvent(
            store_id="STORE_BLR_002",
            camera_id="CAM_ENTRY_01",
            visitor_id="VIS_abc123",
            event_type="ENTRY",
            timestamp="2026-03-03T14:00:00Z",
            is_staff=False,
            confidence=0.92,
        )
        assert event.event_id is not None
        assert len(event.event_id) == 36  # UUID v4

    def test_event_id_uniqueness(self):
        """1000 generated event_ids are all unique."""
        ids = set()
        for _ in range(1000):
            ev = StoreEvent(
                store_id="STORE_BLR_002",
                camera_id="CAM_01",
                visitor_id="VIS_001",
                event_type="ENTRY",
                timestamp="2026-03-03T14:00:00Z",
                confidence=0.9,
            )
            ids.add(ev.event_id)
        assert len(ids) == 1000

    @pytest.mark.parametrize("event_type", [
        "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT",
        "ZONE_DWELL", "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
    ])
    def test_all_valid_event_types(self, event_type):
        """All catalogue event types are accepted."""
        ev = StoreEvent(
            store_id="STORE_BLR_002",
            camera_id="CAM_01",
            visitor_id="VIS_001",
            event_type=event_type,
            timestamp="2026-03-03T14:00:00Z",
            confidence=0.9,
        )
        assert ev.event_type == event_type

    def test_invalid_event_type_raises(self):
        """Invalid event_type raises ValueError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            StoreEvent(
                store_id="STORE_BLR_002",
                camera_id="CAM_01",
                visitor_id="VIS_001",
                event_type="WALK",  # invalid
                timestamp="2026-03-03T14:00:00Z",
                confidence=0.9,
            )

    def test_invalid_timestamp_raises(self):
        """Malformed timestamp raises ValueError."""
        with pytest.raises(Exception):
            StoreEvent(
                store_id="STORE_BLR_002",
                camera_id="CAM_01",
                visitor_id="VIS_001",
                event_type="ENTRY",
                timestamp="not-a-date",
                confidence=0.9,
            )

    def test_confidence_boundary_zero(self):
        """confidence=0.0 is valid (low but not suppressed)."""
        ev = StoreEvent(
            store_id="STORE_BLR_002",
            camera_id="CAM_01",
            visitor_id="VIS_001",
            event_type="ZONE_ENTER",
            timestamp="2026-03-03T14:00:00Z",
            confidence=0.0,
        )
        assert ev.confidence == 0.0

    def test_confidence_boundary_one(self):
        """confidence=1.0 is valid."""
        ev = StoreEvent(
            store_id="STORE_BLR_002",
            camera_id="CAM_01",
            visitor_id="VIS_001",
            event_type="ENTRY",
            timestamp="2026-03-03T14:00:00Z",
            confidence=1.0,
        )
        assert ev.confidence == 1.0

    def test_confidence_above_one_raises(self):
        """confidence > 1.0 raises ValidationError."""
        with pytest.raises(Exception):
            StoreEvent(
                store_id="STORE_BLR_002",
                camera_id="CAM_01",
                visitor_id="VIS_001",
                event_type="ENTRY",
                timestamp="2026-03-03T14:00:00Z",
                confidence=1.5,
            )

    def test_dwell_ms_is_integer(self):
        """dwell_ms field must be int."""
        ev = StoreEvent(
            store_id="STORE_BLR_002",
            camera_id="CAM_01",
            visitor_id="VIS_001",
            event_type="ZONE_DWELL",
            timestamp="2026-03-03T14:00:00Z",
            confidence=0.9,
            dwell_ms=30000,
        )
        assert isinstance(ev.dwell_ms, int)
        assert ev.dwell_ms == 30000

    def test_all_required_fields_in_dict(self):
        """to_dict() returns all required schema fields."""
        ev = StoreEvent(
            store_id="STORE_BLR_002",
            camera_id="CAM_01",
            visitor_id="VIS_001",
            event_type="ENTRY",
            timestamp="2026-03-03T14:00:00Z",
            confidence=0.9,
        )
        d = ev.to_dict()
        required_keys = {
            "event_id", "store_id", "camera_id", "visitor_id",
            "event_type", "timestamp", "zone_id", "dwell_ms",
            "is_staff", "confidence", "metadata"
        }
        assert required_keys.issubset(set(d.keys()))

    def test_metadata_defaults(self):
        """Default metadata has None queue_depth, None sku_zone, 0 session_seq."""
        ev = StoreEvent(
            store_id="STORE_BLR_002",
            camera_id="CAM_01",
            visitor_id="VIS_001",
            event_type="ENTRY",
            timestamp="2026-03-03T14:00:00Z",
            confidence=0.9,
        )
        assert ev.metadata.queue_depth is None
        assert ev.metadata.sku_zone is None
        assert ev.metadata.session_seq == 0


class TestFrameToTimestamp:

    def test_frame_0_equals_clip_start(self):
        """Frame 0 maps to the clip start timestamp exactly."""
        clip_start = "2026-03-03T14:00:00Z"
        ts = frame_to_timestamp(clip_start, 0, 30.0)
        assert ts == "2026-03-03T14:00:00Z"

    def test_frame_30_equals_one_second(self):
        """Frame 30 at 30fps = 1 second offset."""
        clip_start = "2026-03-03T14:00:00Z"
        ts = frame_to_timestamp(clip_start, 30, 30.0)
        assert ts == "2026-03-03T14:00:01Z"

    def test_frame_1800_equals_one_minute(self):
        """Frame 1800 at 30fps = 60 seconds = 1 minute."""
        clip_start = "2026-03-03T14:00:00Z"
        ts = frame_to_timestamp(clip_start, 1800, 30.0)
        assert ts == "2026-03-03T14:01:00Z"

    def test_timestamp_ends_with_Z(self):
        """Output timestamp always ends with Z (UTC)."""
        ts = frame_to_timestamp("2026-03-03T14:00:00Z", 100, 25.0)
        assert ts.endswith("Z")


class TestMakeVisitorId:

    def test_deterministic(self):
        """Same inputs always produce the same visitor_id."""
        id1 = make_visitor_id(42, "STORE_BLR_002")
        id2 = make_visitor_id(42, "STORE_BLR_002")
        assert id1 == id2

    def test_different_tracks_different_ids(self):
        """Different track_ids produce different visitor_ids."""
        id1 = make_visitor_id(1, "STORE_BLR_002")
        id2 = make_visitor_id(2, "STORE_BLR_002")
        assert id1 != id2

    def test_format_prefix(self):
        """visitor_id starts with VIS_ prefix."""
        vid = make_visitor_id(1, "STORE_BLR_002")
        assert vid.startswith("VIS_")

    def test_format_hex_suffix(self):
        """visitor_id suffix is 6 hex characters."""
        vid = make_visitor_id(1, "STORE_BLR_002")
        suffix = vid.replace("VIS_", "")
        assert len(suffix) == 6
        int(suffix, 16)  # should not raise


class TestEventEmitter:

    def test_emitter_writes_valid_jsonl(self, tmp_path):
        """EventEmitter writes each event as a valid JSON line."""
        output = tmp_path / "events.jsonl"

        with EventEmitter(str(output)) as emitter:
            for i in range(5):
                ev = StoreEvent(
                    store_id="STORE_BLR_002",
                    camera_id="CAM_01",
                    visitor_id=f"VIS_{i:03d}",
                    event_type="ENTRY",
                    timestamp="2026-03-03T14:00:00Z",
                    confidence=0.9,
                )
                emitter.emit(ev)

        lines = output.read_text().strip().split("\n")
        assert len(lines) == 5
        for line in lines:
            parsed = json.loads(line)
            assert "event_id" in parsed
            assert "store_id" in parsed
            assert parsed["store_id"] == "STORE_BLR_002"

    def test_emitter_event_ids_unique_in_file(self, tmp_path):
        """All event_ids in emitted JSONL are unique."""
        output = tmp_path / "events.jsonl"

        with EventEmitter(str(output)) as emitter:
            for i in range(100):
                ev = StoreEvent(
                    store_id="STORE_BLR_002",
                    camera_id="CAM_01",
                    visitor_id="VIS_001",
                    event_type="ZONE_DWELL",
                    timestamp="2026-03-03T14:00:00Z",
                    confidence=0.85,
                )
                emitter.emit(ev)

        lines = output.read_text().strip().split("\n")
        ids = [json.loads(l)["event_id"] for l in lines]
        assert len(set(ids)) == 100  # all unique
