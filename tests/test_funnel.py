# PROMPT:
# "Write pytest tests for a store conversion funnel endpoint.
#  The funnel has 4 stages: Entry → Zone Visit → Billing Queue → Purchase.
#  Cover: full happy-path funnel (all stages populated), re-entry should not
#  double-count the same visitor in Entry stage, zone visits only count product zones
#  (not ENTRY_THRESHOLD or BILLING zones), funnel with no billing visits,
#  funnel for empty store, drop-off % calculations correctness."
#
# CHANGES MADE:
# - AI's test for drop_off_pct was using >= 0 — replaced with exact expected values
# - Added explicit test that REENTRY event does NOT create extra Entry stage entry
# - Fixed zone filter: AI included BILLING_QUEUE in zone_visit stage, which should not count
# - Added assertion that stages are always exactly 4 in length

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models import Event, POSTransaction
from app.funnel import get_store_funnel


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


def ev(visitor_id, event_type, zone_id=None, dwell_ms=0, is_staff=False,
       timestamp="2026-03-03T14:00:00Z", store_id="STORE_BLR_002"):
    return Event(
        event_id=str(uuid.uuid4()),
        store_id=store_id,
        camera_id="CAM_01",
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=timestamp,
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=0.9,
        session_seq=1,
    )


def txn(store_id="STORE_BLR_002", timestamp="2026-03-03T14:05:00Z"):
    return POSTransaction(
        transaction_id=str(uuid.uuid4()),
        store_id=store_id,
        timestamp=timestamp,
        basket_value_inr=1000.0,
    )


class TestFunnel:

    def test_empty_store_funnel(self, db):
        """Empty store: all funnel stages are 0."""
        result = get_store_funnel("STORE_BLR_002", db)
        assert len(result.stages) == 4
        for stage in result.stages:
            assert stage.count == 0
            assert stage.drop_off_pct == 0.0

    def test_full_funnel_happy_path(self, db):
        """10 visitors → 8 zone → 5 billing → 3 purchase."""
        # 10 entries
        for i in range(10):
            db.add(ev(f"VIS_{i:03d}", "ENTRY", timestamp="2026-03-03T14:00:00Z"))

        # 8 zone visits (product zones)
        for i in range(8):
            db.add(ev(f"VIS_{i:03d}", "ZONE_ENTER", zone_id="SKINCARE",
                      timestamp="2026-03-03T14:01:00Z"))

        # 5 billing queue entries — 8 minutes before transaction (OUTSIDE 5-min window)
        for i in range(5):
            db.add(ev(f"VIS_{i:03d}", "ZONE_ENTER", zone_id="BILLING_QUEUE",
                      timestamp="2026-03-03T13:57:00Z"))

        # 3 transactions at 14:05:00, with only VIS_000, VIS_001, VIS_002
        # entering billing WITHIN the 5-min window (14:04:30 → 14:05:00 is 30s, within window)
        for i in range(3):
            db.add(ev(f"VIS_{i:03d}", "ZONE_ENTER", zone_id="BILLING_QUEUE",
                      timestamp="2026-03-03T14:04:30Z"))
        db.add(txn(timestamp="2026-03-03T14:05:00Z"))
        db.add(txn(timestamp="2026-03-03T14:05:30Z"))
        db.add(txn(timestamp="2026-03-03T14:06:00Z"))

        db.commit()

        result = get_store_funnel("STORE_BLR_002", db)
        assert len(result.stages) == 4

        entry_stage = result.stages[0]
        zone_stage = result.stages[1]
        billing_stage = result.stages[2]
        purchase_stage = result.stages[3]

        assert entry_stage.stage == "Entry"
        assert entry_stage.count == 10
        assert entry_stage.drop_off_pct == 0.0

        assert zone_stage.stage == "Zone Visit"
        assert zone_stage.count == 8
        assert zone_stage.drop_off_pct == 20.0  # (10-8)/10 * 100

        assert billing_stage.stage == "Billing Queue"
        assert billing_stage.count == 5
        assert billing_stage.drop_off_pct == 37.5  # (8-5)/8 * 100

        assert purchase_stage.stage == "Purchase"
        assert purchase_stage.count == 3  # only 3 were in billing within 5-min window


    def test_reentry_does_not_inflate_entry_count(self, db):
        """Same visitor with ENTRY + REENTRY is counted only once in Entry stage."""
        db.add(ev("VIS_001", "ENTRY", timestamp="2026-03-03T14:00:00Z"))
        db.add(ev("VIS_001", "EXIT", timestamp="2026-03-03T14:10:00Z"))
        db.add(ev("VIS_001", "REENTRY", timestamp="2026-03-03T14:15:00Z"))
        db.commit()

        result = get_store_funnel("STORE_BLR_002", db)
        # Entry stage counts distinct visitor_ids from ENTRY+REENTRY events
        # VIS_001 appears in both → distinct count = 1
        entry_stage = result.stages[0]
        assert entry_stage.count == 1

    def test_billing_zone_not_counted_as_product_zone(self, db):
        """BILLING_QUEUE visits should NOT count as Zone Visit stage."""
        db.add(ev("VIS_001", "ENTRY"))
        db.add(ev("VIS_001", "ZONE_ENTER", zone_id="BILLING_QUEUE"))
        db.commit()

        result = get_store_funnel("STORE_BLR_002", db)
        # Zone Visit stage should be 0 (only billing, no product zone)
        zone_stage = result.stages[1]
        assert zone_stage.count == 0

    def test_entry_threshold_not_counted_as_product_zone(self, db):
        """ENTRY_THRESHOLD zone visits should not inflate Zone Visit stage."""
        db.add(ev("VIS_001", "ENTRY"))
        db.add(ev("VIS_001", "ZONE_ENTER", zone_id="ENTRY_THRESHOLD"))
        db.commit()

        result = get_store_funnel("STORE_BLR_002", db)
        zone_stage = result.stages[1]
        assert zone_stage.count == 0

    def test_staff_excluded_from_all_funnel_stages(self, db):
        """Staff events don't appear in any funnel stage."""
        db.add(ev("VIS_staff", "ENTRY", is_staff=True))
        db.add(ev("VIS_staff", "ZONE_ENTER", zone_id="SKINCARE", is_staff=True))
        db.add(ev("VIS_staff", "ZONE_ENTER", zone_id="BILLING_QUEUE", is_staff=True))
        db.add(txn())
        db.commit()

        result = get_store_funnel("STORE_BLR_002", db)
        for stage in result.stages:
            assert stage.count == 0

    def test_funnel_no_billing_stage(self, db):
        """Visitors who visited product zones but never reached billing."""
        for i in range(5):
            db.add(ev(f"VIS_{i}", "ENTRY"))
            db.add(ev(f"VIS_{i}", "ZONE_ENTER", zone_id="SKINCARE"))
        db.commit()

        result = get_store_funnel("STORE_BLR_002", db)
        billing_stage = result.stages[2]
        assert billing_stage.count == 0
        purchase_stage = result.stages[3]
        assert purchase_stage.count == 0

    def test_drop_off_pct_when_zero_at_stage(self, db):
        """Drop-off to 0 at a stage should show 100% drop-off."""
        for i in range(4):
            db.add(ev(f"VIS_{i}", "ENTRY"))
            db.add(ev(f"VIS_{i}", "ZONE_ENTER", zone_id="HAIRCARE"))
        # No one reaches billing
        db.commit()

        result = get_store_funnel("STORE_BLR_002", db)
        billing_stage = result.stages[2]
        assert billing_stage.count == 0
        assert billing_stage.drop_off_pct == 100.0

    def test_stages_always_exactly_four(self, db):
        """Funnel always returns exactly 4 stages."""
        result = get_store_funnel("STORE_BLR_002", db)
        assert len(result.stages) == 4
        stage_names = [s.stage for s in result.stages]
        assert stage_names == ["Entry", "Zone Visit", "Billing Queue", "Purchase"]
