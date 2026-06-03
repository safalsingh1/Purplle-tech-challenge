"""
replay.py — Real-time event replay for Part E (live dashboard demo).

Reads events.jsonl and POSTs them to the API with simulated real-time pacing.
Events are replayed at configurable speed (default: 10x real-time).

Usage:
  python replay.py --events data/events.jsonl --api http://localhost:8000
  python replay.py --events data/events.jsonl --api http://localhost:8000 --speed 5
"""

import json
import time
import argparse
import httpx
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("replay")


def load_events(path: str) -> list[dict]:
    events = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def replay(events: list[dict], api_url: str, speed: float = 10.0, batch_size: int = 50):
    """
    Replay events in timestamp order, simulating real-time pacing.
    Sends batches to the API and prints running metrics.
    """
    if not events:
        log.error("No events to replay.")
        return

    # Sort by timestamp
    events.sort(key=lambda e: e.get("timestamp", ""))

    # Get time range
    first_ts = datetime.fromisoformat(events[0]["timestamp"].replace("Z", "+00:00"))
    last_ts = datetime.fromisoformat(events[-1]["timestamp"].replace("Z", "+00:00"))
    total_duration_s = (last_ts - first_ts).total_seconds()

    log.info(f"Replaying {len(events)} events over {total_duration_s:.0f}s at {speed}x speed")
    log.info(f"Time range: {events[0]['timestamp']} → {events[-1]['timestamp']}")
    log.info(f"API: {api_url}")

    ingest_url = f"{api_url}/events/ingest"
    start_wall = time.time()
    total_ingested = 0
    total_failed = 0

    # Group events into time-ordered batches
    pending = []
    last_flush_clip_ts = first_ts

    for i, event in enumerate(events):
        event_ts = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        clip_elapsed_s = (event_ts - first_ts).total_seconds()
        wall_elapsed_s = clip_elapsed_s / speed

        # Wait until this event's wall-clock time arrives
        target_wall = start_wall + wall_elapsed_s
        now = time.time()
        if now < target_wall:
            # Flush current pending batch
            if pending:
                total_ingested, total_failed = _flush(
                    pending, ingest_url, total_ingested, total_failed
                )
                pending = []

                # Print metrics
                _print_metrics(api_url, total_ingested)

            sleep_s = target_wall - now
            if sleep_s > 0.01:
                time.sleep(sleep_s)

        pending.append(event)

        # Flush if batch is full
        if len(pending) >= batch_size:
            total_ingested, total_failed = _flush(
                pending, ingest_url, total_ingested, total_failed
            )
            pending = []
            _print_metrics(api_url, total_ingested)

    # Flush remainder
    if pending:
        total_ingested, total_failed = _flush(pending, ingest_url, total_ingested, total_failed)
        _print_metrics(api_url, total_ingested)

    wall_total = time.time() - start_wall
    log.info(f"\nReplay complete in {wall_total:.1f}s")
    log.info(f"Total ingested: {total_ingested} | Failed: {total_failed}")
    log.info(f"Dashboard: {api_url}/dashboard")


def _flush(events, ingest_url, total_ingested, total_failed):
    try:
        resp = httpx.post(
            ingest_url,
            json={"events": events},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            total_ingested += data.get("accepted", 0)
            if data.get("rejected", 0) > 0:
                log.warning(f"  Rejected {data['rejected']} events")
        else:
            log.error(f"  Ingest failed: {resp.status_code}")
            total_failed += len(events)
    except Exception as e:
        log.error(f"  Request failed: {e}")
        total_failed += len(events)
    return total_ingested, total_failed


def _print_metrics(api_url, total_ingested):
    """Fetch and display current metrics for all known stores."""
    known_stores = ["STORE_BLR_002"]
    for store_id in known_stores:
        try:
            resp = httpx.get(f"{api_url}/stores/{store_id}/metrics", timeout=5.0)
            if resp.status_code == 200:
                m = resp.json()
                print(
                    f"  [{store_id}] "
                    f"Visitors: {m['unique_visitors']:3d} | "
                    f"Conv: {m['conversion_rate']:.1%} | "
                    f"Queue: {m['queue_depth']:2d} | "
                    f"Abandon: {m['abandonment_rate']:.1%} | "
                    f"Events ingested: {total_ingested}"
                )
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time event replay for live dashboard demo")
    parser.add_argument("--events", default="data/events.jsonl", help="Path to events.jsonl")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--speed", type=float, default=10.0, help="Replay speed multiplier (default: 10x)")
    parser.add_argument("--batch-size", type=int, default=50, help="Events per API call")
    parser.add_argument("--clear", action="store_true", help="Clear all database events before replaying")
    args = parser.parse_args()

    if args.clear:
        log.info("Sending clear command to API...")
        try:
            resp = httpx.post(f"{args.api}/events/clear", timeout=10.0)
            if resp.status_code == 200:
                log.info("Database events cleared successfully.")
                time.sleep(1.0)  # Wait a moment for browser to reload
            else:
                log.error(f"Failed to clear database events: {resp.status_code}")
        except Exception as e:
            log.error(f"Failed to clear database events: {e}")

    events = load_events(args.events)
    replay(events, args.api, speed=args.speed, batch_size=args.batch_size)
