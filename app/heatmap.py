"""
heatmap.py — Zone heatmap computation for store intelligence.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.models import Event, HeatmapResponse, HeatmapZone

log = logging.getLogger(__name__)

MIN_SESSIONS_FOR_CONFIDENCE = 20


def get_store_heatmap(store_id: str, db: Session) -> HeatmapResponse:
    """Compute zone visit frequency and dwell heatmap, normalised 0-100."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Group only by zone_id — use MAX(sku_zone) to pick one label per zone.
    # Grouping by (zone_id, sku_zone) creates duplicate rows when some events
    # have sku_zone=NULL and others have a value for the same zone.
    zone_rows = (
        db.query(
            Event.zone_id,
            func.max(Event.sku_zone).label("sku_zone"),
            func.count(distinct(Event.visitor_id)).label("visitor_count"),
            func.avg(func.nullif(Event.dwell_ms, 0)).label("avg_dwell_ms"),
        )
        .filter(
            Event.store_id == store_id,
            Event.event_type.in_(["ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"]),
            Event.zone_id.isnot(None),
            Event.zone_id.notin_(["ENTRY_THRESHOLD"]),
            Event.is_staff == False,
        )
        .group_by(Event.zone_id)
        .all()
    )

    if not zone_rows:
        return HeatmapResponse(
            store_id=store_id,
            zones=[],
            data_confidence=False,
            computed_at=now_str,
        )

    # Compute total unique sessions
    total_sessions = (
        db.query(func.count(distinct(Event.visitor_id)))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "ENTRY",
            Event.is_staff == False,
        )
        .scalar() or 0
    )

    data_confidence = total_sessions >= MIN_SESSIONS_FOR_CONFIDENCE

    # Normalise visitor_count to 0-100
    max_count = max((row.visitor_count for row in zone_rows), default=1)

    zones = [
        HeatmapZone(
            zone_id=row.zone_id,
            normalised_score=round((row.visitor_count / max_count) * 100, 1) if max_count > 0 else 0.0,
            visit_count=row.visitor_count,
            avg_dwell_seconds=round((row.avg_dwell_ms or 0) / 1000, 1),
            sku_zone=row.sku_zone,
        )
        for row in zone_rows
    ]

    # Sort by normalised score descending
    zones.sort(key=lambda z: z.normalised_score, reverse=True)

    return HeatmapResponse(
        store_id=store_id,
        zones=zones,
        data_confidence=data_confidence,
        computed_at=now_str,
    )
