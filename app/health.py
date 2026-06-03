"""
health.py — Service health endpoint logic.
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, text

from app.models import Event, HealthResponse, StoreHealth
from app.database import check_db_health

log = logging.getLogger(__name__)

STALE_FEED_THRESHOLD_MINUTES = 10


def get_health(db: Session) -> HealthResponse:
    """Check overall service health and per-store feed status."""
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    db_ok = check_db_health()
    db_status = "OK" if db_ok else "ERROR"

    if not db_ok:
        return HealthResponse(
            service_status="DEGRADED",
            database_status=db_status,
            stores=[],
            checked_at=now_str,
        )

    # Get all known stores
    try:
        store_ids = [
            sid
            for (sid,) in db.query(distinct(Event.store_id)).all()
        ]
    except Exception as e:
        log.error(f"Health check DB query failed: {e}")
        return HealthResponse(
            service_status="DEGRADED",
            database_status="ERROR",
            stores=[],
            checked_at=now_str,
        )

    store_healths: list[StoreHealth] = []

    for store_id in store_ids:
        latest = (
            db.query(Event.timestamp)
            .filter(Event.store_id == store_id)
            .order_by(Event.timestamp.desc())
            .first()
        )

        if not latest:
            store_healths.append(StoreHealth(
                store_id=store_id,
                last_event_timestamp=None,
                lag_seconds=None,
                status="NO_DATA",
            ))
            continue

        try:
            last_ts = datetime.fromisoformat(latest.timestamp.replace("Z", "+00:00"))
            lag_s = (now - last_ts).total_seconds()
            is_stale = lag_s > STALE_FEED_THRESHOLD_MINUTES * 60
            status = "STALE_FEED" if is_stale else "HEALTHY"
        except ValueError:
            lag_s = None
            status = "HEALTHY"

        store_healths.append(StoreHealth(
            store_id=store_id,
            last_event_timestamp=latest.timestamp,
            lag_seconds=round(lag_s, 1) if lag_s is not None else None,
            status=status,
        ))

    overall = "UP" if db_ok else "DEGRADED"
    return HealthResponse(
        service_status=overall,
        database_status=db_status,
        stores=store_healths,
        checked_at=now_str,
    )
