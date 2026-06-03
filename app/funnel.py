"""
funnel.py — Conversion funnel computation with session-level deduplication.

Funnel stages (session is the unit, not raw events):
  1. ENTRY       — visitor entered the store
  2. ZONE_VISIT  — visitor entered at least one product zone
  3. BILLING     — visitor entered billing queue or counter
  4. PURCHASE    — visitor correlated to a POS transaction

Design:
  - Re-entries do NOT create new sessions (REENTRY events share visitor_id with prior ENTRY)
  - A single visitor_id counts once per stage, even if they visited a zone multiple times
  - Drop-off % = (stage_count - next_stage_count) / stage_count * 100
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.models import Event, POSTransaction, FunnelResponse, FunnelStage
from app.metrics import CONVERSION_WINDOW_MINUTES

log = logging.getLogger(__name__)


def get_store_funnel(store_id: str, db: Session) -> FunnelResponse:
    """Compute the conversion funnel for a store."""
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

    # Stage 1: Unique customer visitors (ENTRY events, excluding anyone ever marked as staff, dedup by visitor_id)
    entry_visitors: set[str] = set(
        vid
        for (vid,) in db.query(distinct(Event.visitor_id))
        .filter(
            Event.store_id == store_id,
            Event.event_type.in_(["ENTRY", "REENTRY"]),
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
        )
        .all()
    )
    entry_count = len(entry_visitors)

    # Stage 2: Visitors who entered at least one product zone
    zone_visitors: set[str] = set(
        vid
        for (vid,) in db.query(distinct(Event.visitor_id))
        .filter(
            Event.store_id == store_id,
            Event.event_type.in_(["ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"]),
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
            Event.zone_id.isnot(None),
            Event.zone_id.notin_(["BILLING_COUNTER", "BILLING_QUEUE", "ENTRY_THRESHOLD"]),
        )
        .all()
    ) & entry_visitors  # only count those who also had ENTRY

    zone_count = len(zone_visitors)

    # Stage 3: Visitors who entered billing zone
    billing_visitors: set[str] = set(
        vid
        for (vid,) in db.query(distinct(Event.visitor_id))
        .filter(
            Event.store_id == store_id,
            Event.event_type.in_(["ZONE_ENTER", "BILLING_QUEUE_JOIN", "ZONE_EXIT", "ZONE_DWELL"]),
            Event.visitor_id.isnot(None),
            Event.visitor_id.notin_(staff_visitor_ids),
            Event.zone_id.in_(["BILLING_COUNTER", "BILLING_QUEUE"]),
        )
        .all()
    ) & entry_visitors

    billing_count = len(billing_visitors)

    # Stage 4: Visitors correlated to a POS transaction
    converted_visitors = _get_converted_visitors(store_id, db, staff_visitor_ids)
    purchase_count = len(converted_visitors & entry_visitors)

    # Build funnel stages with drop-off %
    stages = []
    counts = [
        ("Entry", entry_count),
        ("Zone Visit", zone_count),
        ("Billing Queue", billing_count),
        ("Purchase", purchase_count),
    ]

    for i, (stage_name, count) in enumerate(counts):
        if i == 0:
            drop_off = 0.0
        else:
            prev_count = counts[i - 1][1]
            if prev_count > 0:
                drop_off = round((prev_count - count) / prev_count * 100, 1)
            else:
                drop_off = 0.0

        stages.append(FunnelStage(
            stage=stage_name,
            count=count,
            drop_off_pct=drop_off,
        ))

    return FunnelResponse(
        store_id=store_id,
        stages=stages,
        computed_at=now_str,
    )


def _get_converted_visitors(store_id: str, db: Session, staff_visitor_ids) -> set[str]:
    """Return set of visitor_ids who are correlated to a POS transaction."""
    transactions = (
        db.query(POSTransaction.timestamp)
        .filter(POSTransaction.store_id == store_id)
        .all()
    )

    converted: set[str] = set()
    for (txn_ts_str,) in transactions:
        try:
            txn_ts = datetime.fromisoformat(txn_ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        window_start = txn_ts - timedelta(minutes=CONVERSION_WINDOW_MINUTES)
        window_start_str = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        txn_ts_str_iso = txn_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        billing_visitors = (
            db.query(distinct(Event.visitor_id))
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
            converted.add(vid)

    return converted
