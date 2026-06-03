"""
ingestion.py — Event ingest, validation, and deduplication.

Key design decisions:
  - Idempotent by event_id: INSERT OR IGNORE (SQLite) / ON CONFLICT DO NOTHING (Postgres)
  - Partial success: malformed events are rejected with structured errors;
    well-formed events in the same batch still succeed
  - Batch limit: 500 events per request
  - Validation: full Pydantic validation before any DB write
"""

import logging
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import Event, EventIn, IngestResponse

log = logging.getLogger(__name__)


def ingest_events(events: List[EventIn], db: Session) -> IngestResponse:
    """
    Ingest a batch of events. Returns counts of accepted, rejected, and duplicate events.
    """
    accepted = 0
    rejected = 0
    duplicate = 0
    errors: list[dict] = []

    for ev in events:
        # ── Resolve schema aliases from new resource format ──
        # store_code → store_id
        resolved_store_id = ev.store_id or ev.store_code
        # id_token → visitor_id; track_id as fallback
        resolved_visitor_id = ev.visitor_id or ev.id_token or (f"TRACK_{ev.track_id}" if ev.track_id else None)
        # event_timestamp / event_time → timestamp
        resolved_timestamp = ev.timestamp or ev.event_timestamp or ev.event_time
        # zone_name → zone_id fallback
        resolved_zone_id = ev.zone_id or ev.zone_name
        # gender alias
        resolved_gender = ev.gender_pred or ev.gender
        # age alias
        resolved_age = ev.age_pred or ev.age
        # camera_id fallback
        resolved_camera_id = ev.camera_id or "UNKNOWN"

        # ── Check for duplicate by event_id ──
        existing = db.query(Event.id).filter(Event.event_id == ev.event_id).first()
        if existing:
            duplicate += 1
            continue

        # Use a savepoint so a single-event failure doesn't roll back the whole batch
        try:
            with db.begin_nested():
                db_event = Event(
                    event_id=ev.event_id,
                    store_id=resolved_store_id,
                    camera_id=resolved_camera_id,
                    visitor_id=resolved_visitor_id,
                    event_type=ev.event_type,
                    timestamp=resolved_timestamp,
                    zone_id=resolved_zone_id,
                    dwell_ms=ev.dwell_ms,
                    is_staff=ev.is_staff,
                    confidence=ev.confidence,
                    queue_depth=ev.metadata.queue_depth,
                    sku_zone=ev.metadata.sku_zone,
                    session_seq=ev.metadata.session_seq,
                    # New demographic fields
                    gender_pred=resolved_gender,
                    age_pred=resolved_age,
                    age_bucket=ev.age_bucket,
                    group_id=ev.group_id,
                    group_size=ev.group_size,
                    # New queue enrichment fields
                    queue_join_ts=ev.queue_join_ts,
                    queue_served_ts=ev.queue_served_ts,
                    queue_exit_ts=ev.queue_exit_ts,
                    wait_seconds=ev.wait_seconds,
                    queue_position_at_join=ev.queue_position_at_join,
                )
                db.add(db_event)
            accepted += 1
        except Exception as e:
            rejected += 1
            errors.append({
                "event_id": ev.event_id,
                "error": str(e),
            })
            log.warning(f"Failed to insert event {ev.event_id}: {e}")
            continue


    try:
        db.commit()
    except Exception as e:
        db.rollback()
        log.error(f"Batch commit failed: {e}")
        # Count all as rejected
        return IngestResponse(
            accepted=0,
            rejected=len(events),
            duplicate=0,
            errors=[{"error": f"Batch commit failed: {e}"}],
        )

    return IngestResponse(
        accepted=accepted,
        rejected=rejected,
        duplicate=duplicate,
        errors=errors,
    )


def ingest_pos_transactions(csv_path: str, db: Session) -> int:
    """Load POS transactions from CSV into the database."""
    import csv
    from datetime import datetime, timezone
    from collections import defaultdict
    from app.models import POSTransaction

    count = 0
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        # Check which schema we have
        if "transaction_id" in fieldnames:
            # Original schema
            for row in reader:
                existing = db.query(POSTransaction.id).filter(
                    POSTransaction.transaction_id == row["transaction_id"]
                ).first()
                if existing:
                    continue
                db.add(POSTransaction(
                    transaction_id=row["transaction_id"],
                    store_id=row["store_id"],
                    timestamp=row["timestamp"],
                    basket_value_inr=float(row["basket_value_inr"] or 0.0),
                ))
                count += 1
        elif "order_id" in fieldnames:
            # New real-world schema: multiple lines per order, order_date, order_time, total_amount, store_id
            orders = defaultdict(lambda: {"total_amount": 0.0, "store_id": None, "timestamp": None})
            for row in reader:
                order_id = row["order_id"]
                if not order_id:
                    continue
                
                # Sum the total amount for basket value
                total_amount = float(row["total_amount"] or 0.0)
                orders[order_id]["total_amount"] += total_amount
                
                # Only construct timestamp and store_id if not done yet
                if not orders[order_id]["timestamp"]:
                    orders[order_id]["store_id"] = row["store_id"]
                    
                    # Convert DD-MM-YYYY and HH:MM:SS to ISO-8601 UTC
                    try:
                        date_dt = datetime.strptime(row["order_date"].strip(), "%d-%m-%Y")
                        date_part = date_dt.strftime("%Y-%m-%d")
                        time_part = row["order_time"].strip()
                        orders[order_id]["timestamp"] = f"{date_part}T{time_part}Z"
                    except Exception as e:
                        log.warning(f"Failed to parse date/time {row['order_date']} {row['order_time']}: {e}")
                        orders[order_id]["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Now insert the aggregated orders
            for order_id, info in orders.items():
                existing = db.query(POSTransaction.id).filter(
                    POSTransaction.transaction_id == order_id
                ).first()
                if existing:
                    continue
                db.add(POSTransaction(
                    transaction_id=order_id,
                    store_id=info["store_id"],
                    timestamp=info["timestamp"],
                    basket_value_inr=info["total_amount"],
                ))
                count += 1
        else:
            log.error(f"Unknown POS CSV schema headers: {fieldnames}")
            return 0

    db.commit()
    log.info(f"Loaded {count} POS transactions.")
    return count
