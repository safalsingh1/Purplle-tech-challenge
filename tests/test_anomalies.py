# PROMPT:
# "Write pytest tests for anomaly detection in a retail store analytics system.
#  Anomaly types: BILLING_QUEUE_SPIKE (queue > 5), CONVERSION_DROP (vs rolling avg),
#  DEAD_ZONE (no zone visits in 30 min), STALE_FEED (no events in 10 min).
#  Test that: spike detected when queue_depth consistently high, no spike when below threshold,
#  dead zone detected for zones with no recent activity, healthy zones not flagged,
#  stale feed detected when last event > 10 min ago, no stale when events are recent,
#  severity levels are correct (WARN/CRITICAL)."
#
# CHANGES MADE:
# - Added freeze_time equivalent using manual timestamp manipulation (no freezegun dependency)
# - AI used mock.patch for datetime.now() — replaced with passing timestamps via DB events
# - Fixed DEAD_ZONE test: must insert historical zone event so zone is "known", then nothing recent
# - Added test that STALE_FEED is not triggered if store has no events at all (different from stale)

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models import Event
from app.anomalies import get_store_anomalies, QUEUE_SPIKE_DEPTH, STALE_FEED_MINUTES


@pytest.fixture(scope="function")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture(scope="function")
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(minutes_ago: float) -> str:
    """Return ISO timestamp N minutes in the past."""
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event(event_type="ZONE_ENTER", zone_id="BILLING_QUEUE", queue_depth=None,
               is_staff=False, timestamp=None, visitor_id=None,
               store_id="STORE_BLR_002"):
    return Event(
        event_id=str(uuid.uuid4()),
        store_id=store_id,
        camera_id="CAM_BILLING_01",
        visitor_id=visitor_id or str(uuid.uuid4())[:8],
        event_type=event_type,
        timestamp=timestamp or now_iso(),
        zone_id=zone_id,
        dwell_ms=0,
        is_staff=is_staff,
        confidence=0.9,
        queue_depth=queue_depth,
        session_seq=1,
    )


class TestQueueSpike:

    def test_spike_detected_above_threshold(self, db):
        """Queue depth > QUEUE_SPIKE_DEPTH in recent events → BILLING_QUEUE_SPIKE anomaly."""
        for _ in range(5):
            db.add(make_event(queue_depth=QUEUE_SPIKE_DEPTH + 2))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        spike = [a for a in result.anomalies if a.anomaly_type == "BILLING_QUEUE_SPIKE"]
        assert len(spike) >= 1
        assert spike[0].value >= QUEUE_SPIKE_DEPTH

    def test_no_spike_below_threshold(self, db):
        """Queue depth below threshold → no BILLING_QUEUE_SPIKE."""
        for _ in range(5):
            db.add(make_event(queue_depth=2))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        spike = [a for a in result.anomalies if a.anomaly_type == "BILLING_QUEUE_SPIKE"]
        assert len(spike) == 0

    def test_spike_severity_critical_when_very_deep(self, db):
        """Queue depth >= 10 → CRITICAL severity."""
        for _ in range(5):
            db.add(make_event(queue_depth=12))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        spike = [a for a in result.anomalies if a.anomaly_type == "BILLING_QUEUE_SPIKE"]
        assert spike[0].severity == "CRITICAL"

    def test_spike_severity_warn_when_moderate(self, db):
        """Queue depth 5-9 → WARN severity."""
        for _ in range(5):
            db.add(make_event(queue_depth=7))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        spike = [a for a in result.anomalies if a.anomaly_type == "BILLING_QUEUE_SPIKE"]
        assert spike[0].severity == "WARN"

    def test_no_queue_events_no_spike(self, db):
        """No billing queue events at all → no spike anomaly."""
        db.add(make_event(event_type="ENTRY", zone_id=None, queue_depth=None))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        spike = [a for a in result.anomalies if a.anomaly_type == "BILLING_QUEUE_SPIKE"]
        assert len(spike) == 0


class TestDeadZone:

    def test_dead_zone_detected_for_inactive_zone(self, db):
        """Zone with events only from long ago → DEAD_ZONE anomaly."""
        # Old event (40 minutes ago)
        db.add(make_event(event_type="ZONE_ENTER", zone_id="SKINCARE",
                          queue_depth=None, timestamp=ts(40)))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        dead = [a for a in result.anomalies if a.anomaly_type == "DEAD_ZONE"]
        zone_ids = [a.zone_id for a in dead]
        assert "SKINCARE" in zone_ids

    def test_active_zone_not_flagged(self, db):
        """Zone with recent events → no DEAD_ZONE."""
        # Recent event (2 minutes ago)
        db.add(make_event(event_type="ZONE_ENTER", zone_id="HAIRCARE",
                          queue_depth=None, timestamp=ts(2)))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        dead = [a for a in result.anomalies if a.anomaly_type == "DEAD_ZONE"
                and a.zone_id == "HAIRCARE"]
        assert len(dead) == 0

    def test_billing_zone_not_flagged_as_dead(self, db):
        """BILLING_QUEUE and BILLING_COUNTER are excluded from dead zone check."""
        db.add(make_event(event_type="ZONE_ENTER", zone_id="BILLING_QUEUE",
                          timestamp=ts(40)))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        dead = [a for a in result.anomalies if a.anomaly_type == "DEAD_ZONE"
                and a.zone_id in ("BILLING_QUEUE", "BILLING_COUNTER")]
        assert len(dead) == 0

    def test_staff_only_zone_activity_flagged_dead(self, db):
        """Staff movements don't count as customer activity for dead zone check."""
        db.add(make_event(event_type="ZONE_ENTER", zone_id="WELLNESS",
                          is_staff=True, timestamp=ts(5)))
        # Old customer event
        db.add(make_event(event_type="ZONE_ENTER", zone_id="WELLNESS",
                          is_staff=False, timestamp=ts(40)))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        dead = [a for a in result.anomalies if a.anomaly_type == "DEAD_ZONE"
                and a.zone_id == "WELLNESS"]
        assert len(dead) >= 1  # staff movements don't keep zone alive


class TestStaleFeed:

    def test_stale_feed_detected_after_threshold(self, db):
        """Last event > 10 minutes ago → STALE_FEED anomaly."""
        db.add(make_event(event_type="ENTRY", zone_id=None,
                          timestamp=ts(STALE_FEED_MINUTES + 5)))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        stale = [a for a in result.anomalies if a.anomaly_type == "STALE_FEED"]
        assert len(stale) >= 1
        assert stale[0].severity in ("WARN", "CRITICAL")

    def test_no_stale_when_events_are_recent(self, db):
        """Last event < 10 minutes ago → no STALE_FEED."""
        db.add(make_event(event_type="ENTRY", zone_id=None, timestamp=ts(2)))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        stale = [a for a in result.anomalies if a.anomaly_type == "STALE_FEED"]
        assert len(stale) == 0

    def test_no_events_at_all_no_stale_feed(self, db):
        """Store with no events at all → STALE_FEED not triggered (different from stale)."""
        result = get_store_anomalies("STORE_BLR_002", db)
        stale = [a for a in result.anomalies if a.anomaly_type == "STALE_FEED"]
        assert len(stale) == 0

    def test_stale_severity_critical_when_very_old(self, db):
        """Last event > 30 minutes ago → CRITICAL severity."""
        db.add(make_event(event_type="ENTRY", zone_id=None, timestamp=ts(35)))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        stale = [a for a in result.anomalies if a.anomaly_type == "STALE_FEED"]
        assert stale[0].severity == "CRITICAL"


class TestAnomalyStructure:

    def test_anomaly_has_required_fields(self, db):
        """All anomalies have required fields."""
        db.add(make_event(queue_depth=10))
        db.add(make_event(queue_depth=10))
        db.commit()

        result = get_store_anomalies("STORE_BLR_002", db)
        for anomaly in result.anomalies:
            assert anomaly.anomaly_id
            assert anomaly.anomaly_type
            assert anomaly.severity in ("INFO", "WARN", "CRITICAL")
            assert anomaly.description
            assert anomaly.suggested_action
            assert anomaly.detected_at

    def test_empty_store_no_crash(self, db):
        """Anomaly detection on empty store returns empty list without error."""
        result = get_store_anomalies("STORE_BLR_002", db)
        assert isinstance(result.anomalies, list)
        assert result.store_id == "STORE_BLR_002"
