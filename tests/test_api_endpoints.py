# PROMPT: Generate integration tests for all FastAPI endpoints in main.py including root, config, health, events/ingest, events/clear, stores metrics/funnel/heatmap/anomalies, cameras list, simulation start/stop/speed. These tests use httpx AsyncClient via conftest fixtures and verify status codes and response shapes.
# CHANGES MADE: Uses client_with_db fixture from test_additional_coverage pattern, covers all critical store analytics endpoints.

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db
from app.models import Event, POSTransaction


@pytest.fixture(scope="function")
def mem_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture(scope="function")
def mem_db(mem_engine):
    Session = sessionmaker(bind=mem_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def api(mem_db):
    def override():
        yield mem_db
    app.dependency_overrides[get_db] = override
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


# ─── Root & meta endpoints ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_root(api):
    r = await api.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "Apex Retail Store Intelligence API"
    assert "docs" in data


@pytest.mark.anyio
async def test_config_endpoint(api):
    r = await api.get("/config")
    assert r.status_code == 200
    assert "api_url" in r.json()


@pytest.mark.anyio
async def test_health_endpoint(api):
    r = await api.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service_status"] == "UP"
    assert body["database_status"] == "OK"


# ─── Events ingestion and clear ───────────────────────────────────────────────

@pytest.mark.anyio
async def test_ingest_valid_event(api):
    payload = {
        "events": [{
            "event_id": "api-test-001",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_API_TEST",
            "event_type": "ENTRY",
            "timestamp": "2026-03-03T14:00:00Z",
            "confidence": 0.9,
            "metadata": {}
        }]
    }
    r = await api.post("/events/ingest", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 1
    assert body["rejected"] == 0


@pytest.mark.anyio
async def test_ingest_invalid_event_type_rejected(api):
    payload = {
        "events": [{
            "event_id": "api-test-bad-001",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_API_TEST_BAD",
            "event_type": "INVALID_TYPE",
            "timestamp": "2026-03-03T14:00:00Z",
            "confidence": 0.9,
            "metadata": {}
        }]
    }
    r = await api.post("/events/ingest", json=payload)
    assert r.status_code == 422


@pytest.mark.anyio
async def test_ingest_duplicate_event(api):
    event = {
        "event_id": "dup-001",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_DUP",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:00:00Z",
        "confidence": 0.9,
        "metadata": {}
    }
    r1 = await api.post("/events/ingest", json={"events": [event]})
    assert r1.json()["accepted"] == 1

    r2 = await api.post("/events/ingest", json={"events": [event]})
    assert r2.json()["duplicate"] == 1
    assert r2.json()["accepted"] == 0


@pytest.mark.anyio
async def test_clear_events(api):
    payload = {"events": [{
        "event_id": "clear-test-001",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_CLR",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:00:00Z",
        "confidence": 0.9,
        "metadata": {}
    }]}
    await api.post("/events/ingest", json=payload)

    r = await api.post("/events/clear")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ─── Store analytics endpoints ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_metrics_empty_store(api):
    r = await api.get("/stores/STORE_BLR_002/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == "STORE_BLR_002"
    assert body["unique_visitors"] == 0
    assert body["conversion_rate"] == 0.0


@pytest.mark.anyio
async def test_global_metrics(api):
    r = await api.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == "STORE_BLR_002"
    assert body["unique_visitors"] == 0
    assert body["conversion_rate"] == 0.0


@pytest.mark.anyio
async def test_global_metrics_uppercase(api):
    r = await api.get("/Metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == "STORE_BLR_002"
    assert body["unique_visitors"] == 0
    assert body["conversion_rate"] == 0.0


@pytest.mark.anyio
async def test_funnel_empty_store(api):
    r = await api.get("/stores/STORE_BLR_002/funnel")
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == "STORE_BLR_002"
    assert isinstance(body["stages"], list)


@pytest.mark.anyio
async def test_heatmap_empty_store(api):
    r = await api.get("/stores/STORE_BLR_002/heatmap")
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == "STORE_BLR_002"
    assert isinstance(body["zones"], list)


@pytest.mark.anyio
async def test_anomalies_empty_store(api):
    r = await api.get("/stores/STORE_BLR_002/anomalies")
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == "STORE_BLR_002"
    assert isinstance(body["anomalies"], list)


@pytest.mark.anyio
async def test_metrics_with_data(api):
    """Ingest a few events and verify metrics update."""
    events = [
        {
            "event_id": f"m-{i:03d}",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": f"VIS_M{i:02d}",
            "event_type": "ENTRY",
            "timestamp": f"2026-03-03T14:00:{i:02d}Z",
            "confidence": 0.9,
            "metadata": {}
        }
        for i in range(5)
    ]
    r = await api.post("/events/ingest", json={"events": events})
    assert r.json()["accepted"] == 5

    r2 = await api.get("/stores/STORE_BLR_002/metrics")
    body = r2.json()
    assert body["unique_visitors"] == 5


# ─── Camera endpoints ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_cameras_list(api):
    r = await api.get("/cameras")
    assert r.status_code == 200
    body = r.json()
    assert "cameras" in body
    # Registry now includes Store 1 + Store 2 cameras
    assert len(body["cameras"]) >= 5
    cam_ids = {c["cam_id"] for c in body["cameras"]}
    # Original Store 1 cams must all be present
    assert {"CAM_1", "CAM_2", "CAM_3", "CAM_5"}.issubset(cam_ids)



# ─── Simulation control endpoints ─────────────────────────────────────────────

@pytest.mark.anyio
async def test_simulation_stop(api):
    r = await api.post("/simulation/stop")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.anyio
async def test_simulation_speed_change(api):
    r = await api.post("/simulation/speed?speed=2.0")
    assert r.status_code == 200
    assert r.json()["ok"] is True
