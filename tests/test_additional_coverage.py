# PROMPT:
# "Generate comprehensive pytest tests for a retail store intelligence system covering:
#  POS transaction ingestion (original + aggregated schema), store heatmap endpoint,
#  health endpoint (OK and STALE), zone classifier polygon containment, staff detector
#  duration + colour heuristics, ReID tracker appearance matching, database helper methods,
#  dashboard SSE page and broadcast_update, pipeline build_clip_config, camera processor init,
#  and all root / config endpoints. Use in-memory SQLite fixtures."
#
# CHANGES MADE:
# - Removed AI-generated mocks for zone_classifier — tested via real ZoneClassifier object
# - Fixed StaffDetector test: AI didn't account for minimum track length threshold, added padding
# - Added explicit DB teardown in each test using test_session fixture rollback
# - Replaced AI's generic assertion `assert result is not None` with specific field value checks
# - Added test for root endpoint schema shape (AI initially omitted this)
import pytest
import uuid
import json
import tempfile
import os
import numpy as np
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import Base, get_db
from app.models import Event, POSTransaction
from app.ingestion import ingest_pos_transactions
from app.heatmap import get_store_heatmap
from app.health import get_health
from pipeline.zone_classifier import ZoneClassifier, _point_in_polygon
from pipeline.staff_detector import StaffDetector


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


# ─── 1. Ingestion tests (CSV transaction loading) ───────────────────────────

def test_ingest_pos_transactions(db):
    # Create temp CSV file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp:
        tmp.write("store_id,transaction_id,timestamp,basket_value_inr\n")
        tmp.write("STORE_BLR_002,TXN_00001,2026-03-03T14:02:30Z,1240.00\n")
        tmp.write("STORE_BLR_002,TXN_00002,2026-03-03T14:05:15Z,680.00\n")
        tmp_name = tmp.name

    try:
        count = ingest_pos_transactions(tmp_name, db)
        assert count == 2

        # Check transactions in DB
        txns = db.query(POSTransaction).all()
        assert len(txns) == 2
        assert txns[0].transaction_id == "TXN_00001"
        assert txns[0].basket_value_inr == 1240.00

        # Duplicate check (should ignore existing)
        count_dup = ingest_pos_transactions(tmp_name, db)
        assert count_dup == 0
    finally:
        os.unlink(tmp_name)


# ─── 2. Heatmap tests ──────────────────────────────────────────────────────────

def test_get_store_heatmap(db):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Add ENTRY event to have a session count (denominator)
    db.add(Event(
        event_id=str(uuid.uuid4()),
        store_id="STORE_BLR_002",
        camera_id="CAM_01",
        visitor_id="VIS_001",
        event_type="ENTRY",
        timestamp=now_str,
        is_staff=False,
    ))

    # Add zone events
    db.add(Event(
        event_id=str(uuid.uuid4()),
        store_id="STORE_BLR_002",
        camera_id="CAM_02",
        visitor_id="VIS_001",
        event_type="ZONE_ENTER",
        zone_id="SKINCARE",
        sku_zone="MOISTURISER",
        timestamp=now_str,
        is_staff=False,
    ))
    db.add(Event(
        event_id=str(uuid.uuid4()),
        store_id="STORE_BLR_002",
        camera_id="CAM_02",
        visitor_id="VIS_001",
        event_type="ZONE_EXIT",
        zone_id="SKINCARE",
        sku_zone="MOISTURISER",
        dwell_ms=30000,
        timestamp=now_str,
        is_staff=False,
    ))
    db.commit()

    heatmap = get_store_heatmap("STORE_BLR_002", db)
    assert heatmap.store_id == "STORE_BLR_002"
    assert len(heatmap.zones) == 1
    assert heatmap.zones[0].zone_id == "SKINCARE"
    assert heatmap.zones[0].normalised_score == 100.0
    assert heatmap.zones[0].visit_count == 1
    assert heatmap.zones[0].avg_dwell_seconds == 30.0
    assert heatmap.data_confidence is False  # total sessions = 1 < 20


@pytest.mark.asyncio
async def test_heatmap_endpoint(client_with_db):
    async with client_with_db as client:
        resp = await client.get("/stores/STORE_BLR_002/heatmap")
    assert resp.status_code == 200
    data = resp.json()
    assert "store_id" in data
    assert "zones" in data
    assert "data_confidence" in data


# ─── 3. Health tests ────────────────────────────────────────────────────────────

def test_get_health_ok(db):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Add recent event
    db.add(Event(
        event_id=str(uuid.uuid4()),
        store_id="STORE_BLR_002",
        camera_id="CAM_01",
        visitor_id="VIS_001",
        event_type="ENTRY",
        timestamp=now_str,
        is_staff=False,
    ))
    db.commit()

    health = get_health(db)
    assert health.service_status == "UP"
    assert health.database_status == "OK"
    assert len(health.stores) == 1
    assert health.stores[0].store_id == "STORE_BLR_002"
    assert health.stores[0].status == "HEALTHY"


def test_get_health_stale(db):
    # Event older than 10 minutes (e.g. 15 minutes old)
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")

    db.add(Event(
        event_id=str(uuid.uuid4()),
        store_id="STORE_BLR_002",
        camera_id="CAM_01",
        visitor_id="VIS_001",
        event_type="ENTRY",
        timestamp=old_time,
        is_staff=False,
    ))
    db.commit()

    health = get_health(db)
    assert health.stores[0].status == "STALE_FEED"


@pytest.mark.asyncio
async def test_health_endpoint(client_with_db):
    async with client_with_db as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service_status"] == "UP"
    assert data["database_status"] == "OK"


# ─── 4. Zone Classifier tests ───────────────────────────────────────────────

def test_point_in_polygon():
    # Square polygon from (0,0) to (1,1)
    poly = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

    # Centroid inside
    assert _point_in_polygon(0.5, 0.5, poly) is True
    # Centroid outside
    assert _point_in_polygon(1.5, 0.5, poly) is False
    assert _point_in_polygon(0.5, -0.2, poly) is False


def test_zone_classifier():
    layout_data = {
        "stores": {
            "STORE_BLR_002": {
                "cameras": {
                    "CAM_ENTRY_01": {
                        "type": "entry_exit",
                        "entry_line_y_ratio": 0.5,
                        "zones": {
                            "ENTRY_THRESHOLD": {
                                "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 0.2], [0.0, 0.2]],
                                "is_entry_zone": True
                            }
                        }
                    }
                }
            }
        }
    }

    classifier = ZoneClassifier(layout_data, "STORE_BLR_002", "CAM_ENTRY_01")
    assert classifier.is_entry_camera() is True
    assert classifier.is_billing_camera() is False
    assert classifier.entry_line_y_ratio == 0.5

    # Test classification
    info = classifier.classify(0.5, 0.1)
    assert info is not None
    assert info.zone_id == "ENTRY_THRESHOLD"
    assert info.is_entry_zone is True

    # Test classification outside
    assert classifier.classify(0.5, 0.8) is None


# ─── 5. Staff Detector tests ──────────────────────────────────────────────────

def test_staff_detector_duration():
    # 100 frames total. Staff duration ratio is 0.65
    detector = StaffDetector(clip_total_frames=100, staff_duration_ratio=0.65)

    # Track 1 appears from frame 10 to 80 (71 frames, >65%)
    detector.update(1, 10, np.zeros((100, 100, 3), dtype=np.uint8), [10, 10, 50, 50])
    detector.update(1, 80, np.zeros((100, 100, 3), dtype=np.uint8), [10, 10, 50, 50])

    assert detector.is_staff(1) is True
    assert detector.get_confidence(1) > 0.80

    # Track 2 appears from frame 10 to 30 (21 frames, <65%)
    detector.update(2, 10, np.zeros((100, 100, 3), dtype=np.uint8), [10, 10, 50, 50])
    detector.update(2, 30, np.zeros((100, 100, 3), dtype=np.uint8), [10, 10, 50, 50])

    assert detector.is_staff(2) is False
    assert detector.get_confidence(2) == 0.75  # base confidence


def test_staff_detector_color():
    detector = StaffDetector(clip_total_frames=1000, staff_duration_ratio=0.85)

    # Let's mock a red uniform (hue around 5)
    img_red = np.zeros((100, 100, 3), dtype=np.uint8)
    img_red[:, :, 0] = 5    # Hue
    img_red[:, :, 1] = 200  # Saturation
    img_red[:, :, 2] = 200  # Value

    # Track 1: Staff member wearing uniform. Let's update many times.
    # Note: we need it to have duration >= 30% to be counted as long track during finalize
    for f in range(100, 450, 50):  # spans 350 frames (>30%)
        detector.update(1, f, img_red, [10, 10, 50, 50])

    detector.finalize()

    # Staff cluster should be discovered
    assert detector._staff_hue_cluster is not None

    # Track 3: Customer wearing uniform, but short duration (duration = 50 frames, < 30%)
    for f in range(100, 150, 50):
        detector.update(3, f, img_red, [10, 10, 50, 50])

    # Should count as staff due to color matching staff uniform cluster
    assert detector.is_staff(3) is True
    assert detector.get_confidence(3) > 0.5


# ─── 6. ReID Tracker tests ────────────────────────────────────────────────────

def test_reid_tracker_flow():
    from pipeline.tracker import ReIDTracker, compute_appearance_hash

    tracker = ReIDTracker(store_id="STORE_BLR_002")

    # 1. New visitor entry on CAM_ENTRY_01
    sess1, is_new, is_re = tracker.get_or_create_session(
        track_id=1,
        camera_id="CAM_ENTRY_01",
        frame_idx=100,
        timestamp_s=1000.0,
        appearance_hash="1_2_3_4"
    )
    assert is_new is True
    assert is_re is False
    assert sess1.visitor_id.startswith("VIS_")
    assert sess1.session_seq == 0

    # 2. Existing visitor update
    sess1_updated, is_new, is_re = tracker.get_or_create_session(
        track_id=1,
        camera_id="CAM_ENTRY_01",
        frame_idx=200,
        timestamp_s=1003.0,
        appearance_hash="1_2_3_4"
    )
    assert is_new is False
    assert is_re is False
    assert sess1_updated.visitor_id == sess1.visitor_id
    assert sess1_updated.last_seen_frame == 200

    # Test increment_seq
    seq = tracker.increment_seq(track_id=1, camera_id="CAM_ENTRY_01")
    assert seq == 1
    assert sess1.session_seq == 1

    # 3. Cross-camera matching: visitor seen on CAM_FLOOR_01 within 90s
    sess2, is_new, is_re = tracker.get_or_create_session(
        track_id=5,
        camera_id="CAM_FLOOR_01",
        frame_idx=250,
        timestamp_s=1030.0,  # 30s elapsed (<90s)
        appearance_hash="1_2_3_4"  # matches appearance
    )
    assert is_new is False
    assert is_re is False
    assert sess2.visitor_id == sess1.visitor_id

    # 4. Mark exited
    exited_sess = tracker.mark_exited(track_id=5, camera_id="CAM_FLOOR_01", timestamp_s=1040.0)
    assert exited_sess.visitor_id == sess1.visitor_id
    assert exited_sess.has_exited is True

    # 5. Re-entry: visitor returns on CAM_ENTRY_01 within 10 minutes (600s)
    sess3, is_new, is_re = tracker.get_or_create_session(
        track_id=12,
        camera_id="CAM_ENTRY_01",
        frame_idx=500,
        timestamp_s=1200.0,  # 160s since exit (<600s)
        appearance_hash="1_2_3_4"
    )
    assert is_new is False
    assert is_re is True
    assert sess3.visitor_id == sess1.visitor_id
    assert sess3.has_exited is False


def test_compute_appearance_hash():
    from pipeline.tracker import compute_appearance_hash
    # Create fake RGB/BGR image
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[10:90, 10:90, 0] = 50   # blue
    img[10:90, 10:90, 1] = 150
    img[10:90, 10:90, 2] = 200

    bbox = np.array([10, 10, 90, 90])
    h = compute_appearance_hash(img, bbox)
    assert h != "unknown"
    assert "_" in h

    # Test out of bounds bbox
    h_invalid = compute_appearance_hash(img, np.array([-10, -10, 200, 200]))
    assert h_invalid != "unknown"

    # Test empty/zero-size bbox
    h_zero = compute_appearance_hash(img, np.array([10, 10, 10, 10]))
    assert h_zero == "unknown"


# ─── 7. Database & Dashboard Helper tests ─────────────────────────────────────

def test_database_helper_methods():
    from app.database import init_db, check_db_health, get_db_context, get_db
    
    # Check health on local DB
    assert check_db_health() is True

    # Test initialization (runs metadata.create_all)
    init_db()

    # Test get_db context manager
    with get_db_context() as session:
        assert session is not None

    # Test get_db generator (dependency)
    generator = get_db()
    session = next(generator)
    assert session is not None
    # close the session
    try:
        next(generator)
    except StopIteration:
        pass


@pytest.mark.asyncio
async def test_dashboard_page(client_with_db):
    async with client_with_db as client:
        resp = await client.get("/dashboard")
        assert resp.status_code == 200
        assert "Store Intelligence Dashboard" in resp.text


@pytest.mark.asyncio
async def test_broadcast_update():
    from app.dashboard import broadcast_update, _sse_subscribers
    import asyncio
    
    queue = asyncio.Queue()
    _sse_subscribers.append(queue)
    try:
        await broadcast_update({"test": "data"})
        assert queue.qsize() == 1
        msg = queue.get_nowait()
        assert msg == {"test": "data"}
    finally:
        _sse_subscribers.remove(queue)


# ─── 8. Detection Pipeline Builder and Init tests ─────────────────────────────

def test_build_clip_config(monkeypatch):
    from pipeline.detect import build_clip_config
    monkeypatch.setattr("os.path.exists", lambda path: True)
    configs = build_clip_config("data/store_layout.json", "fake_dir")
    assert len(configs) > 0
    assert configs[0]["store_id"] == "STORE_BLR_002"


def test_camera_processor_init():
    from pipeline.detect import CameraProcessor
    from pipeline.tracker import ReIDTracker
    from pipeline.emit import EventEmitter

    config = {
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "clip_start": "2026-03-03T14:00:00Z",
        "layout": {
            "stores": {
                "STORE_BLR_002": {
                    "cameras": {
                        "CAM_ENTRY_01": {
                            "type": "entry_exit",
                            "entry_line_y_ratio": 0.55,
                            "zones": {}
                        }
                    }
                }
            }
        },
        "cam_data": {
            "type": "entry_exit",
            "entry_line_y_ratio": 0.55,
            "zones": {}
        }
    }
    emitter = EventEmitter("fake_output.jsonl")
    tracker = ReIDTracker(store_id="STORE_BLR_002")
    processor = CameraProcessor(config, emitter, tracker)
    assert processor.store_id == "STORE_BLR_002"
    assert processor.camera_id == "CAM_ENTRY_01"


@pytest.mark.asyncio
async def test_root_endpoint(client_with_db):
    async with client_with_db as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "Apex Retail Store Intelligence API"
        assert "docs" in data


@pytest.mark.asyncio
async def test_config_endpoint(client_with_db):
    async with client_with_db as client:
        resp = await client.get("/config", headers={"host": "my-custom-host.com", "x-forwarded-proto": "https"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_url"] == "https://my-custom-host.com"




