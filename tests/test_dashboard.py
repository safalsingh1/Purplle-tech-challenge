# PROMPT: Generate tests for the FastAPI dashboard endpoint and the SSE broadcast_update function in dashboard.py to boost code coverage above 70%.
# CHANGES MADE: Tests dashboard HTML response, broadcast_update, and /dashboard/stream initial snapshot via AsyncClient.

import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db
from app.dashboard import broadcast_update, _sse_subscribers
from app.models import Event
import uuid


@pytest.fixture(scope="function")
def dash_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture(scope="function")
def dash_db(dash_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=dash_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def dash_client(dash_db):
    def override():
        yield dash_db
    app.dependency_overrides[get_db] = override
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_dashboard_page_returns_html(dash_client):
    """Dashboard page should return valid HTML with 200 status."""
    r = await dash_client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<html" in r.text.lower()


@pytest.mark.anyio
async def test_broadcast_update_to_subscribers():
    """broadcast_update should deliver messages to all subscribed queues."""
    q1 = asyncio.Queue(maxsize=10)
    q2 = asyncio.Queue(maxsize=10)
    _sse_subscribers.append(q1)
    _sse_subscribers.append(q2)
    try:
        await broadcast_update({"type": "metrics", "store_id": "STORE_BLR_002", "data": {}})
        msg1 = q1.get_nowait()
        msg2 = q2.get_nowait()
        assert msg1["type"] == "metrics"
        assert msg2["store_id"] == "STORE_BLR_002"
    finally:
        _sse_subscribers.remove(q1)
        _sse_subscribers.remove(q2)


@pytest.mark.anyio
async def test_broadcast_update_full_queue_no_crash():
    """broadcast_update should silently skip full queues without raising."""
    full_q = asyncio.Queue(maxsize=1)
    await full_q.put({"dummy": True})  # pre-fill to capacity
    _sse_subscribers.append(full_q)
    try:
        # Should not raise even with full queue
        await broadcast_update({"type": "metrics", "store_id": "X", "data": {}})
    finally:
        _sse_subscribers.remove(full_q)


@pytest.mark.anyio
async def test_dashboard_stream_endpoint(dash_client, dash_db):
    """dashboard_stream should return initial metrics snapshot and stream new updates."""
    # Insert a dummy event so we have a store
    ev = Event(
        event_id=str(uuid.uuid4()),
        store_id="STORE_BLR_002",
        camera_id="CAM_ENTRY_01",
        visitor_id="VIS_DASH_TEST",
        event_type="ENTRY",
        timestamp="2026-03-03T14:00:00Z",
        confidence=0.95
    )
    dash_db.add(ev)
    dash_db.commit()

    # Request the stream using a generator
    call_count = 0
    original_wait_for = asyncio.wait_for

    async def mock_wait_for(aw, timeout):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise asyncio.CancelledError()
        return await original_wait_for(aw, timeout)

    from unittest.mock import patch
    with patch("asyncio.wait_for", mock_wait_for):
        async with dash_client.stream("GET", "/dashboard/stream") as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            
            # Read the first chunk (initial snapshot)
            chunk = ""
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    chunk = line
                    break
            
            assert "STORE_BLR_002" in chunk


@pytest.mark.anyio
async def test_dashboard_stream_heartbeat(dash_client):
    """dashboard_stream should emit heartbeat when wait_for times out."""
    from unittest.mock import patch
    
    call_count = 0
    async def mock_wait_for(aw, timeout):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise asyncio.CancelledError()
        raise asyncio.TimeoutError()

    with patch("asyncio.wait_for", mock_wait_for):
        async with dash_client.stream("GET", "/dashboard/stream") as r:
            assert r.status_code == 200
            lines = []
            async for line in r.aiter_lines():
                if line:
                    lines.append(line)
                    break
            assert ": heartbeat" in lines[0]
