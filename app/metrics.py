"""
metrics.py — Real-time store metric computation.

All metrics are computed fresh from the events table on each request —
no cached stale values. This is appropriate for a store intelligence
system where data freshness matters.

Conversion rate computation:
  A visitor session is "converted" if the visitor was present in a
  billing zone in the 5-minute window before any POS transaction at
  the same store. We join events with pos_transactions by time proximity.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.models import Event, POSTransaction, StoreMetrics, ZoneDwellMetric

log = logging.getLogger(__name__)

CONVERSION_WINDOW_MINUTES = 5
QUEUE_DEPTH_LOOKBACK_MINUTES = 10


def get_store_metrics(store_id: str, db: Session) -> StoreMetrics:
    """Compute real-time metrics for a store."""

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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

    # ── Unique visitors (non-staff, excluding anyone ever marked as staff) ──
    unique_visitors = (
        db.query(func.count(func.distinct(Event.visitor_id)))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "ENTRY",
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .scalar() or 0
    )

    # ── Active visitors (non-staff present in the last 2 minutes real-time) ─────────
    # We use ingested_at instead of timestamp because the video events have 
    # historical timestamps (March 3rd). When the simulation finishes, 
    # ingestion stops, and the active count naturally decays to 0.
    # We ALSO restrict this to visitors who have an explicitly valid ENTRY event
    # so tracker fragments don't inflate active dots beyond the Total Visitors count.
    two_mins_ago_realtime = datetime.utcnow() - timedelta(minutes=2)
    valid_visitor_subq = (
        db.query(Event.visitor_id)
        .filter(
            Event.store_id == store_id,
            Event.event_type == "ENTRY",
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
    )
    active_visitors = (
        db.query(func.count(func.distinct(Event.visitor_id)))
        .filter(
            Event.store_id == store_id,
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
            Event.ingested_at >= two_mins_ago_realtime,
            Event.visitor_id.in_(valid_visitor_subq)
        )
        .scalar() or 0
    )

    # ── Conversion rate ──────────────────────────────────────────────────────
    conversion_rate = _compute_conversion_rate(store_id, db)

    # ── Average dwell per zone ───────────────────────────────────────────────
    zone_dwell_rows = (
        db.query(
            Event.zone_id,
            func.avg(Event.dwell_ms).label("avg_dwell_ms"),
            func.count(Event.id).label("visit_count"),
        )
        .filter(
            Event.store_id == store_id,
            Event.event_type.in_(["ZONE_EXIT", "ZONE_DWELL"]),
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
            Event.zone_id.isnot(None),
            Event.dwell_ms > 0,
        )
        .group_by(Event.zone_id)
        .all()
    )

    avg_dwell_per_zone = [
        ZoneDwellMetric(
            zone_id=row.zone_id,
            avg_dwell_seconds=round((row.avg_dwell_ms or 0) / 1000, 1),
            visit_count=row.visit_count,
        )
        for row in zone_dwell_rows
    ]

    # ── Current queue depth ──────────────────────────────────────────────────
    latest_queue = (
        db.query(Event.queue_depth)
        .filter(
            Event.store_id == store_id,
            Event.zone_id == "BILLING_QUEUE",
            Event.queue_depth.isnot(None),
        )
        .order_by(Event.timestamp.desc())
        .first()
    )
    queue_depth = (latest_queue.queue_depth or 0) if latest_queue else 0

    # ── Abandonment rate ─────────────────────────────────────────────────────
    total_queue_joins = (
        db.query(func.count(Event.id))
        .filter(
            Event.store_id == store_id,
            Event.event_type.in_(["BILLING_QUEUE_JOIN", "ZONE_ENTER"]),
            Event.zone_id == "BILLING_QUEUE",
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .scalar() or 0
    )
    total_abandons = (
        db.query(func.count(Event.id))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "BILLING_QUEUE_ABANDON",
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .scalar() or 0
    )

    if total_queue_joins > 0:
        abandonment_rate = round(total_abandons / (total_queue_joins + total_abandons), 4)
    else:
        abandonment_rate = 0.0

    return StoreMetrics(
        store_id=store_id,
        unique_visitors=unique_visitors,
        active_visitors=active_visitors,
        conversion_rate=round(conversion_rate, 4),
        avg_dwell_per_zone=avg_dwell_per_zone,
        queue_depth=queue_depth,
        abandonment_rate=round(abandonment_rate, 4),
        computed_at=now_str,
    )


def _compute_conversion_rate(store_id: str, db: Session) -> float:
    """
    Conversion = visitors who were in billing zone in 5-min window before a POS transaction
               / total unique customer visitors.

    Since we don't have customer_id in POS data, we correlate by time window + store.
    A visitor who was in BILLING_COUNTER or BILLING_QUEUE in the 5 minutes
    before any transaction at the same store = converted.
    """
    # Get all POS transaction timestamps for this store
    transactions = (
        db.query(POSTransaction.timestamp)
        .filter(POSTransaction.store_id == store_id)
        .all()
    )

    if not transactions:
        return 0.0

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

    # Get all unique customer visitors
    all_visitors = (
        db.query(func.distinct(Event.visitor_id))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "ENTRY",
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .all()
    )
    total_visitors = len(all_visitors)
    if total_visitors == 0:
        return 0.0

    visitor_ids_set = {v[0] for v in all_visitors}

    # For each transaction, find which visitors were in billing zone in prior 5 min
    converted_visitors: set[str] = set()

    for (txn_ts_str,) in transactions:
        try:
            txn_ts = datetime.fromisoformat(txn_ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        window_start = txn_ts - timedelta(minutes=CONVERSION_WINDOW_MINUTES)
        window_start_str = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        txn_ts_str_iso = txn_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Visitors in billing zone within the window
        billing_visitors = (
            db.query(func.distinct(Event.visitor_id))
            .filter(
                Event.store_id == store_id,
                Event.event_type.in_(["ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL", "BILLING_QUEUE_JOIN"]),
                Event.zone_id.in_(["BILLING_COUNTER", "BILLING_QUEUE"]),
                Event.visitor_id.isnot(None),
                Event.visitor_id.notin_(staff_visitor_ids),
                Event.timestamp >= window_start_str,
                Event.timestamp <= txn_ts_str_iso,
            )
            .all()
        )
        for (vid,) in billing_visitors:
            if vid in visitor_ids_set:
                converted_visitors.add(vid)

    return len(converted_visitors) / total_visitors
