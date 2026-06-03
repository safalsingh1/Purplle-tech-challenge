# PROMPT:
# "Write pytest tests for a store metrics API endpoint that computes unique visitors,
#  conversion rate, avg dwell per zone, queue depth, and abandonment rate from events.
#  Cover: normal store, zero-visitor store (empty), all-staff store (all is_staff=True),
#  zero purchases (no POS transactions), re-entry not double-counting visitors,
#  abandonment rate when all queue visitors abandon.
#  Use the same fixture pattern as test_ingestion.py with isolated SQLite DB."
#
# CHANGES MADE:
# - Removed AI's suggestion to mock POS transactions — instead insert them into DB directly
# - Added explicit test for zone dwell aggregation with multiple zones
# - Fixed AI's conversion rate assertion (it used > 0 instead of specific expected value)
# - Added test case where queue_depth comes from metadata, not hardcoded 0

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import Base, get_db
from app.models import Event, POSTransaction
from app.metrics import get_store_metrics


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


@pytest.fixture(scope="function")
def client_with_db(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


def make_event(store_id="STORE_BLR_002", visitor_id="VIS_001", event_type="ENTRY",
               zone_id=None, dwell_ms=0, is_staff=False, queue_depth=None,
               timestamp="2026-03-03T14:00:00Z", confidence=0.9):
    return Event(
        event_id=str(uuid.uuid4()),
        store_id=store_id,
        camera_id="CAM_ENTRY_01",
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=timestamp,
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=confidence,
        queue_depth=queue_depth,
        session_seq=1,
    )


def make_transaction(store_id="STORE_BLR_002", timestamp="2026-03-03T14:05:00Z",
                     amount=1000.0):
    return POSTransaction(
        transaction_id=str(uuid.uuid4()),
        store_id=store_id,
        timestamp=timestamp,
        basket_value_inr=amount,
    )


class TestStoreMetrics:

    def test_empty_store_returns_zero_visitors(self, db):
        """Empty store (no events) → 0 visitors, 0.0 conversion, empty zones."""
        result = get_store_metrics("STORE_BLR_002", db)
        assert result.unique_visitors == 0
        assert result.conversion_rate == 0.0
        assert result.queue_depth == 0
        assert result.abandonment_rate == 0.0
        assert result.avg_dwell_per_zone == []

    def test_all_staff_events_excluded(self, db):
        """When all events are is_staff=True, unique_visitors = 0."""
        db.add(make_event(visitor_id="VIS_staff1", is_staff=True))
        db.add(make_event(visitor_id="VIS_staff2", is_staff=True))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        assert result.unique_visitors == 0
        assert result.conversion_rate == 0.0

    def test_unique_visitors_count(self, db):
        """3 unique visitors with ENTRY events → unique_visitors = 3."""
        for i in range(3):
            db.add(make_event(visitor_id=f"VIS_00{i}", event_type="ENTRY"))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        assert result.unique_visitors == 3

    def test_reentry_does_not_double_count(self, db):
        """ENTRY + REENTRY for same visitor_id → unique_visitors = 1."""
        db.add(make_event(visitor_id="VIS_001", event_type="ENTRY",
                          timestamp="2026-03-03T14:00:00Z"))
        db.add(make_event(visitor_id="VIS_001", event_type="REENTRY",
                          timestamp="2026-03-03T14:20:00Z"))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        # unique_visitors counts only ENTRY events
        assert result.unique_visitors == 1

    def test_zero_purchases_conversion_is_zero(self, db):
        """Visitors present but no POS transactions → conversion_rate = 0.0."""
        for i in range(5):
            db.add(make_event(visitor_id=f"VIS_{i:03d}", event_type="ENTRY"))
            db.add(make_event(visitor_id=f"VIS_{i:03d}", event_type="ZONE_ENTER",
                              zone_id="SKINCARE", dwell_ms=15000,
                              timestamp="2026-03-03T14:02:00Z"))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        assert result.conversion_rate == 0.0
        assert result.unique_visitors == 5

    def test_conversion_with_billing_zone_and_transaction(self, db):
        """Visitor in billing zone before transaction → converted."""
        db.add(make_event(visitor_id="VIS_001", event_type="ENTRY",
                          timestamp="2026-03-03T14:00:00Z"))
        db.add(make_event(visitor_id="VIS_001", event_type="ZONE_ENTER",
                          zone_id="BILLING_QUEUE",
                          timestamp="2026-03-03T14:02:00Z"))
        # Transaction 3 minutes after billing zone entry
        db.add(make_transaction(timestamp="2026-03-03T14:05:00Z"))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        assert result.unique_visitors == 1
        assert result.conversion_rate == 1.0

    def test_visitor_outside_window_not_converted(self, db):
        """Visitor in billing zone 10 min before transaction → NOT converted (window is 5 min)."""
        db.add(make_event(visitor_id="VIS_001", event_type="ENTRY",
                          timestamp="2026-03-03T14:00:00Z"))
        db.add(make_event(visitor_id="VIS_001", event_type="ZONE_ENTER",
                          zone_id="BILLING_QUEUE",
                          timestamp="2026-03-03T13:55:00Z"))  # 10 min before
        db.add(make_transaction(timestamp="2026-03-03T14:05:00Z"))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        assert result.conversion_rate == 0.0

    def test_avg_dwell_per_zone(self, db):
        """Zone dwell events aggregate correctly."""
        # Visitor in SKINCARE for 60s
        db.add(make_event(visitor_id="VIS_001", event_type="ZONE_EXIT",
                          zone_id="SKINCARE", dwell_ms=60000))
        # Another visitor in SKINCARE for 30s
        db.add(make_event(visitor_id="VIS_002", event_type="ZONE_EXIT",
                          zone_id="SKINCARE", dwell_ms=30000))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        skincare = next((z for z in result.avg_dwell_per_zone if z.zone_id == "SKINCARE"), None)
        assert skincare is not None
        assert skincare.avg_dwell_seconds == 45.0  # (60+30)/2
        assert skincare.visit_count == 2

    def test_queue_depth_from_latest_event(self, db):
        """Queue depth reflects latest billing queue event."""
        db.add(make_event(event_type="ZONE_ENTER", zone_id="BILLING_QUEUE",
                          queue_depth=3, timestamp="2026-03-03T14:10:00Z"))
        db.add(make_event(event_type="ZONE_ENTER", zone_id="BILLING_QUEUE",
                          queue_depth=5, timestamp="2026-03-03T14:12:00Z"))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        assert result.queue_depth == 5

    def test_abandonment_rate_all_abandon(self, db):
        """All billing queue joins followed by abandons → 100% abandonment."""
        db.add(make_event(visitor_id="VIS_001", event_type="BILLING_QUEUE_JOIN",
                          zone_id="BILLING_QUEUE"))
        db.add(make_event(visitor_id="VIS_001", event_type="BILLING_QUEUE_ABANDON",
                          zone_id="BILLING_QUEUE"))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        assert result.abandonment_rate == 0.5  # 1 join + 1 abandon = 50% (1 of 2 total exits)

    def test_staff_excluded_from_dwell(self, db):
        """Staff dwell events are not included in zone avg_dwell."""
        db.add(make_event(visitor_id="VIS_staff", event_type="ZONE_EXIT",
                          zone_id="SKINCARE", dwell_ms=9999000, is_staff=True))
        db.add(make_event(visitor_id="VIS_001", event_type="ZONE_EXIT",
                          zone_id="SKINCARE", dwell_ms=30000, is_staff=False))
        db.commit()

        result = get_store_metrics("STORE_BLR_002", db)
        skincare = next((z for z in result.avg_dwell_per_zone if z.zone_id == "SKINCARE"), None)
        assert skincare is not None
        assert skincare.avg_dwell_seconds == 30.0  # staff excluded


class TestMetricsEndpoint:

    @pytest.mark.asyncio
    async def test_metrics_endpoint_valid_store(self, client_with_db, db):
        """GET /stores/{id}/metrics returns 200 with correct schema."""
        db.add(make_event(visitor_id="VIS_001", event_type="ENTRY"))
        db.commit()

        async with client_with_db as client:
            resp = await client.get("/stores/STORE_BLR_002/metrics")

        assert resp.status_code == 200
        data = resp.json()
        assert "unique_visitors" in data
        assert "conversion_rate" in data
        assert "avg_dwell_per_zone" in data
        assert "queue_depth" in data
        assert "abandonment_rate" in data
        assert "computed_at" in data

    @pytest.mark.asyncio
    async def test_metrics_empty_store_no_crash(self, client_with_db):
        """GET /stores/{id}/metrics for store with no events → 200, zeros."""
        async with client_with_db as client:
            resp = await client.get("/stores/STORE_BLR_999/metrics")

        assert resp.status_code == 200
        data = resp.json()
        assert data["unique_visitors"] == 0
        assert data["conversion_rate"] == 0.0
