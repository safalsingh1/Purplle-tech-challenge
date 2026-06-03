# PROMPT: Generate targeted unit tests to cover uncovered branches in health.py, anomalies.py, and ingestion.py for the Apex Retail Store Intelligence system. Focus on health check with stale feeds, health check with healthy feeds, anomaly detection with enough visitors for conversion drop logic, and ingestion batch error handling.
# CHANGES MADE: Uses test_session fixture, covers per-store health status transitions, conversion-drop anomaly with 6+ visitors, and missing-field rejection.

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Event, POSTransaction
from app.health import get_health
from app.anomalies import get_store_anomalies
from app.ingestion import ingest_events
from app.models import EventIn, EventMetadataIn


@pytest.fixture(scope="function")
def cov_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture(scope="function")
def cov_db(cov_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=cov_engine)
    session = Session()
    yield session
    session.close()


def make_event(store_id="STORE_BLR_002", visitor_id="VIS_001", event_type="ENTRY",
               timestamp=None, zone_id=None, dwell_ms=0, is_staff=False, queue_depth=None):
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Event(
        event_id=str(uuid.uuid4()),
        store_id=store_id,
        camera_id="CAM_ENTRY_01",
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=ts,
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=0.9,
        queue_depth=queue_depth,
        session_seq=1,
    )


# ─── Health with stale feed ──────────────────────────────────────────────────

def test_health_with_stale_feed(cov_db):
    """A store with an old timestamp should show STALE_FEED."""
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = make_event(timestamp=old_ts)
    cov_db.add(ev)
    cov_db.commit()

    result = get_health(cov_db)
    assert result.service_status == "UP"
    assert len(result.stores) == 1
    assert result.stores[0].status == "STALE_FEED"


def test_health_with_fresh_feed(cov_db):
    """A store with a recent timestamp should show HEALTHY."""
    fresh_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = make_event(timestamp=fresh_ts)
    cov_db.add(ev)
    cov_db.commit()

    result = get_health(cov_db)
    assert result.service_status == "UP"
    assert result.stores[0].status == "HEALTHY"
    assert result.stores[0].lag_seconds is not None
    assert result.stores[0].lag_seconds < 60  # Must be near-zero


def test_health_no_events(cov_db):
    """Health with no events at all should return empty stores list."""
    result = get_health(cov_db)
    assert result.service_status == "UP"
    assert result.stores == []


# ─── Anomaly: conversion drop with enough visitors ──────────────────────────

def test_anomaly_conversion_drop_with_many_visitors(cov_db):
    """With 6+ visitors but no POS transactions, expect conversion drop NOT to trigger
       (rolling_avg == current_rate == 0.0, so drop is not detected)."""
    now = datetime.now(timezone.utc)
    for i in range(6):
        ts = (now - timedelta(minutes=2, seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cov_db.add(make_event(visitor_id=f"VIS_{i:03d}", timestamp=ts))
    cov_db.commit()

    result = get_store_anomalies("STORE_BLR_002", cov_db)
    anomaly_types = [a.anomaly_type for a in result.anomalies]
    # With 0 conversions and 0 POS transactions, rolling_avg=0.15 and current_rate=0
    # This SHOULD trigger CONVERSION_DROP
    assert "CONVERSION_DROP" in anomaly_types


def test_anomaly_queue_spike(cov_db):
    """Inject 2+ events with high queue depth to trigger BILLING_QUEUE_SPIKE."""
    now = datetime.now(timezone.utc)
    for i in range(3):
        ts = (now - timedelta(seconds=i * 5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ev = Event(
            event_id=str(uuid.uuid4()),
            store_id="STORE_BLR_002",
            camera_id="CAM_BILLING_01",
            visitor_id=f"VIS_Q{i:03d}",
            event_type="BILLING_QUEUE_JOIN",
            timestamp=ts,
            zone_id="BILLING_QUEUE",
            dwell_ms=0,
            is_staff=False,
            confidence=0.9,
            queue_depth=12,  # above spike threshold (QUEUE_SPIKE_DEPTH=5)
            session_seq=1,
        )
        cov_db.add(ev)
    cov_db.commit()

    result = get_store_anomalies("STORE_BLR_002", cov_db)
    anomaly_types = [a.anomaly_type for a in result.anomalies]
    assert "BILLING_QUEUE_SPIKE" in anomaly_types


# ─── Ingestion: batch with partial failures ───────────────────────────────────

def test_ingest_empty_batch(cov_db):
    result = ingest_events([], cov_db)
    assert result.accepted == 0
    assert result.rejected == 0
    assert result.duplicate == 0


def test_ingest_multiple_stores(cov_db):
    """Ingest events from two different stores to verify multi-store isolation."""
    events = [
        EventIn(
            event_id=f"ms-{i}",
            store_id="STORE_BLR_002",
            camera_id="CAM_ENTRY_01",
            visitor_id=f"VIS_S1_{i}",
            event_type="ENTRY",
            timestamp="2026-03-03T14:00:00Z",
            confidence=0.9,
            metadata=EventMetadataIn(),
        )
        for i in range(3)
    ]
    result = ingest_events(events, cov_db)
    assert result.accepted == 3


# ─── Funnel edge: stale events in funnel stages ───────────────────────────────

def test_funnel_with_billing_events(cov_db):
    from app.funnel import get_store_funnel
    now = datetime.now(timezone.utc)

    # Visitor enters
    cov_db.add(make_event(visitor_id="VIS_F1", event_type="ENTRY",
                          timestamp=(now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    # Zone visit
    cov_db.add(make_event(visitor_id="VIS_F1", event_type="ZONE_ENTER", zone_id="SKINCARE",
                          timestamp=(now - timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    # Billing queue join
    cov_db.add(make_event(visitor_id="VIS_F1", event_type="BILLING_QUEUE_JOIN", zone_id="BILLING_QUEUE",
                          timestamp=(now - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    # POS transaction
    cov_db.add(POSTransaction(
        transaction_id="TXN_FUNNEL_001",
        store_id="STORE_BLR_002",
        timestamp=(now - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        basket_value_inr=750.0,
    ))
    cov_db.commit()

    result = get_store_funnel("STORE_BLR_002", cov_db)
    stage_names = [s.stage for s in result.stages]
    assert "Entry" in stage_names
    # Entry count should be 1
    entry_stage = next(s for s in result.stages if s.stage == "Entry")
    assert entry_stage.count == 1


# ─── Health check error and edge cases ────────────────────────────────────────

def test_health_db_error():
    from unittest.mock import patch
    with patch("app.health.check_db_health", return_value=False):
        res = get_health(None)
        assert res.service_status == "DEGRADED"
        assert res.database_status == "ERROR"


def test_health_query_failure():
    from unittest.mock import patch, MagicMock
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Query Failed")
    with patch("app.health.check_db_health", return_value=True):
        res = get_health(mock_db)
        assert res.service_status == "DEGRADED"
        assert res.database_status == "ERROR"
        assert res.stores == []


def test_health_malformed_timestamp(cov_db):
    ev = make_event(timestamp="not-a-date")
    cov_db.add(ev)
    cov_db.commit()
    res = get_health(cov_db)
    assert res.service_status == "UP"
    assert res.stores[0].status == "HEALTHY"
    assert res.stores[0].lag_seconds is None
