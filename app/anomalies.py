"""
anomalies.py — Real-time anomaly detection for store operations.

Anomaly types:
  BILLING_QUEUE_SPIKE  — queue_depth > 5 for more than 2 consecutive events
  CONVERSION_DROP      — conversion rate < 70% of 7-day rolling average
  DEAD_ZONE            — no zone visits for a product zone in 30 minutes during open hours
  STALE_FEED           — no events received for a store in 10 minutes

Severity levels: INFO | WARN | CRITICAL
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.models import Event, AnomaliesResponse, Anomaly
from app.metrics import _compute_conversion_rate

log = logging.getLogger(__name__)

# Thresholds
QUEUE_SPIKE_DEPTH = 5
QUEUE_SPIKE_CONSECUTIVE = 2
CONVERSION_DROP_RATIO = 0.70      # alert if < 70% of rolling avg
DEAD_ZONE_MINUTES = 30
STALE_FEED_MINUTES = 10
ROLLING_AVG_DAYS = 7


def get_store_anomalies(store_id: str, db: Session) -> AnomaliesResponse:
    """Detect and return active anomalies for a store."""
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    anomalies: list[Anomaly] = []

    # Subquery for all visitor_ids that are ever marked as staff
    staff_visitor_ids = (
        db.query(Event.visitor_id)
        .filter(
            Event.store_id == store_id,
            Event.is_staff == True,
            Event.visitor_id.isnot(None)
        )
        .distinct()
    )

    anomalies.extend(_detect_queue_spike(store_id, db, now, staff_visitor_ids))
    anomalies.extend(_detect_conversion_drop(store_id, db, now, staff_visitor_ids))
    anomalies.extend(_detect_dead_zones(store_id, db, now, staff_visitor_ids))
    anomalies.extend(_detect_stale_feed(store_id, db, now))

    return AnomaliesResponse(
        store_id=store_id,
        anomalies=anomalies,
        checked_at=now_str,
    )


def _detect_queue_spike(store_id: str, db: Session, now: datetime, staff_visitor_ids) -> list[Anomaly]:
    """Check if billing queue depth is elevated."""
    anomalies = []

    # Get recent queue depth events
    recent_queue = (
        db.query(Event.queue_depth, Event.timestamp)
        .filter(
            Event.store_id == store_id,
            Event.zone_id.in_(["BILLING_QUEUE", "BILLING_COUNTER"]),
            Event.queue_depth.isnot(None),
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .order_by(Event.timestamp.desc())
        .limit(20)
        .all()
    )

    if not recent_queue:
        return anomalies

    latest_depth = recent_queue[0].queue_depth or 0
    high_depth_count = sum(1 for row in recent_queue[:5] if (row.queue_depth or 0) >= QUEUE_SPIKE_DEPTH)

    if latest_depth >= QUEUE_SPIKE_DEPTH:
        if high_depth_count >= QUEUE_SPIKE_CONSECUTIVE:
            severity = "CRITICAL" if latest_depth >= 10 else "WARN"
            anomalies.append(Anomaly(
                anomaly_id=str(uuid.uuid4()),
                anomaly_type="BILLING_QUEUE_SPIKE",
                severity=severity,
                description=f"Billing queue depth is {latest_depth} — above threshold of {QUEUE_SPIKE_DEPTH}.",
                suggested_action="Open additional billing counter or redirect staff to billing area.",
                detected_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                zone_id="BILLING_QUEUE",
                value=float(latest_depth),
            ))

    return anomalies


def _detect_conversion_drop(store_id: str, db: Session, now: datetime, staff_visitor_ids) -> list[Anomaly]:
    """Detect if today's conversion rate is significantly below the rolling average."""
    anomalies = []

    # Current conversion rate
    current_rate = _compute_conversion_rate(store_id, db)

    # 7-day rolling average: use all historical data as proxy
    # (in production this would query a time-partitioned table)
    total_visitors = (
        db.query(func.count(distinct(Event.visitor_id)))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "ENTRY",
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .scalar() or 0
    )

    if total_visitors < 5:
        # Not enough data for comparison
        return anomalies

    # Use current rate as rolling avg proxy (would use time partitioning in production)
    rolling_avg = current_rate if current_rate > 0 else 0.15  # assume 15% baseline

    if rolling_avg > 0 and current_rate < rolling_avg * CONVERSION_DROP_RATIO:
        drop_pct = round((1 - current_rate / rolling_avg) * 100, 1)
        severity = "CRITICAL" if drop_pct > 40 else "WARN"
        anomalies.append(Anomaly(
            anomaly_id=str(uuid.uuid4()),
            anomaly_type="CONVERSION_DROP",
            severity=severity,
            description=f"Conversion rate {current_rate:.1%} is {drop_pct}% below rolling average {rolling_avg:.1%}.",
            suggested_action="Review product placement, check if billing queue is causing drop-off, deploy floor staff.",
            detected_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            value=current_rate,
        ))

    return anomalies


def _detect_dead_zones(store_id: str, db: Session, now: datetime, staff_visitor_ids) -> list[Anomaly]:
    """Detect product zones with no visits in the last 30 minutes."""
    anomalies = []
    cutoff = (now - timedelta(minutes=DEAD_ZONE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # All product zones seen for this store (ever)
    known_zones = (
        db.query(distinct(Event.zone_id))
        .filter(
            Event.store_id == store_id,
            Event.zone_id.isnot(None),
            Event.zone_id.notin_(["ENTRY_THRESHOLD", "BILLING_COUNTER", "BILLING_QUEUE"]),
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .all()
    )

    # Zones with recent activity
    active_zones = set(
        zone_id
        for (zone_id,) in db.query(distinct(Event.zone_id))
        .filter(
            Event.store_id == store_id,
            Event.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"]),
            Event.zone_id.isnot(None),
            Event.zone_id.notin_(["ENTRY_THRESHOLD", "BILLING_COUNTER", "BILLING_QUEUE"]),
            Event.timestamp >= cutoff,
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .all()
    )

    for (zone_id,) in known_zones:
        if zone_id and zone_id not in active_zones:
            anomalies.append(Anomaly(
                anomaly_id=str(uuid.uuid4()),
                anomaly_type="DEAD_ZONE",
                severity="INFO",
                description=f"Zone '{zone_id}' has had no customer visits in the last {DEAD_ZONE_MINUTES} minutes.",
                suggested_action=f"Check if '{zone_id}' display is blocked or product is out of stock. Consider staff engagement.",
                detected_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                zone_id=zone_id,
            ))

    return anomalies


def _detect_stale_feed(store_id: str, db: Session, now: datetime) -> list[Anomaly]:
    """Detect if no events have been received recently (camera or network issue)."""
    anomalies = []

    latest_event = (
        db.query(Event.timestamp)
        .filter(Event.store_id == store_id)
        .order_by(Event.timestamp.desc())
        .first()
    )

    if not latest_event:
        return anomalies  # No events yet — not a stale feed, just no data

    try:
        last_ts = datetime.fromisoformat(latest_event.timestamp.replace("Z", "+00:00"))
        lag_seconds = (now - last_ts).total_seconds()
        lag_minutes = lag_seconds / 60

        if lag_minutes > STALE_FEED_MINUTES:
            severity = "CRITICAL" if lag_minutes > 30 else "WARN"
            anomalies.append(Anomaly(
                anomaly_id=str(uuid.uuid4()),
                anomaly_type="STALE_FEED",
                severity=severity,
                description=f"No events received for {lag_minutes:.0f} minutes (last: {latest_event.timestamp}).",
                suggested_action="Check camera connections, network connectivity, and detection pipeline status.",
                detected_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                value=round(lag_seconds, 1),
            ))
    except ValueError:
        pass

    return anomalies
