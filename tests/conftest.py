"""
conftest.py — Shared pytest fixtures across all test modules.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import Base, get_db


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function")
def test_engine():
    """Create a fresh in-memory SQLite engine for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_engine):
    """Provide a database session bound to the test engine."""
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture(scope="function")
def override_get_db(test_session):
    """Override FastAPI's get_db dependency to use the test session."""
    def _get_test_db():
        yield test_session

    app.dependency_overrides[get_db] = _get_test_db
    yield test_session
    app.dependency_overrides.clear()


@pytest.fixture
def api_client(override_get_db):
    """Return an async HTTP client wired to the test app."""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    )
