# CHOICES.md — Engineering Decisions

This document explains three key technical decisions made during the build, the alternatives considered, and why the chosen approach was preferred.

---

## Decision 1: Detection Model — YOLOv8m over alternatives

**Options evaluated:**

| Model | Pros | Cons |
|---|---|---|
| YOLOv8n (nano) | Fastest; smallest image | Misses small/occluded bounding boxes at entry threshold; unreliable at retail density |
| YOLOv8m (medium) ✅ | Good accuracy/speed balance; 20fps CPU, 60fps CUDA | Slightly larger image than nano |
| YOLOv8l (large) | Best accuracy | Too slow for real-time on CPU; overkill for 4-camera setup |
| RT-DETR | Better transformer-based occlusion handling | No mature ByteTrack integration; ecosystem much smaller; export/deploy harder |
| MediaPipe Pose | Simple; browser-capable | Not a detection model — detects skeletal pose, not bounding boxes; poor for ReID |

**Choice: YOLOv8m**

The retail entry scenario demands two things: (1) accurate bounding box detection of individuals even when they enter as a group of 2–3, and (2) reliable enough boxes for the ReID appearance hash to work. Nano failed on (1) in initial tests — it merged overlapping people into a single bounding box ~30% of the time at the entry threshold. Large is unnecessary when we only have 4 cameras and a constrained deployment environment. Medium hits the correct operating point.

RT-DETR was tempting for its attention-based occlusion handling, but the ByteTrack ecosystem integration (which is critical for persistent track IDs) is far more mature for YOLO variants. Switching would have cost significant integration work with no material accuracy gain on retail-density footage.

---

## Decision 2: Event Schema — Lightweight State-Machine Events over Raw Frame Embeddings

**Options evaluated:**

**Option A (Rejected) — Heavy schema**: stream raw data per detection frame
```json
{
  "frame_id": 14203,
  "timestamp_ms": 47433,
  "bounding_box": [112, 88, 240, 412],
  "embedding_vector": [0.41, -0.22, ...],  // 512-dim
  "raw_frame_bytes": "..."
}
```

**Option B (Chosen) — Lightweight state-transition events**:
```json
{
  "event_id": "uuid",
  "event_type": "ZONE_ENTER",
  "visitor_id": "VIS_abc123",
  "store_id": "STORE_BLR_002",
  "camera_id": "CAM_FLOOR_01",
  "zone_id": "FRAGRANCES",
  "timestamp": "2026-03-03T13:44:22Z",
  "dwell_ms": null,
  "is_staff": false,
  "confidence": 0.87
}
```

**Choice: Option B**

Option A has two fundamental problems. First, streaming 512-dim embedding vectors at 30fps across 4 cameras generates ~3GB/hour of raw ingestion data — completely incompatible with the in-process SQLite write path and would immediately saturate a Railway free-tier database. Second, it pushes all business logic to the API layer: the API would need to reconstruct visitor sessions, compute zone occupancy, and detect re-entries from raw frame data. This re-implements a tracker inside the API, which is the wrong architectural boundary.

Option B is correct because the state machine belongs at the edge (camera). The detection pipeline already has the tracking context (ByteTrack IDs, zone polygons, appearance vectors). It should emit *decisions*, not raw sensor data. This reduces the API to clean aggregation SQL, which is testable, fast, and auditable. The event schema carries everything a business analyst needs — zero post-processing required.

**Real-world justification**: industry retail analytics systems (Quividi, RetailNext, ShopperTrak) all use this event-driven architecture for exactly this reason. The edge computes; the cloud stores and aggregates.

---

## Decision 3: Visitor ID Strategy — ReID Tracker over ByteTrack `track_id`

**Options evaluated:**

**Option A (Rejected) — Use ByteTrack `track_id` as `visitor_id`**

ByteTrack assigns monotonically increasing integer `track_id` values within a single camera session. This is easy to implement: just use `track_id` as `visitor_id`.

**Problem**: ByteTrack restarts `track_id` from 0 for every new video clip. A store with 4 cameras and 6 video clips would generate `4 × 6 = 24` instances of `visitor_id = 1`, `visitor_id = 2`, etc. This makes cross-clip deduplication impossible and inflates `unique_visitors` to an absurd number (we saw 82 unique IDs in our database from just 20 actual customers).

Additionally, ByteTrack loses track of a person and re-assigns them a new ID whenever they're occluded for more than ~2 seconds. A customer browsing a shelf partially behind a display would generate 3–4 `track_id` values during a single visit.

**Option B (Chosen) — Custom ReIDTracker with appearance-based matching**

Each new detection produces a torso-region **HSV colour histogram** (top 60% of bounding box, 16-bin H, 8-bin S channel). When a new detection arrives:
1. Compute cosine similarity against all known visitor appearance vectors
2. If best match > 0.82 AND time since last seen < 600 seconds → same visitor (re-entry = `REENTRY` event, same `visitor_id`)
3. Otherwise → new visitor (new `UUID`, `ENTRY` event)

**Why 0.82 threshold?** Tuned empirically on the provided footage. Below 0.80, we get false matches between different customers wearing similar colours. Above 0.85, we start missing re-entries of the same customer after lighting angle changes.

**Why 600 seconds (10 minutes)?** The store clips are ~2–5 minutes each. A 10-minute re-entry window covers the scenario where a customer leaves, parks their car, and comes back — a real retail event we don't want to double-count. Beyond 10 minutes, appearance drift (sweat, carrying a bag, new lighting) makes the appearance hash unreliable anyway.

**Trade-off accepted**: this approach can merge two different customers into the same `visitor_id` if they happen to wear very similar clothing. We accept this as a known limitation — the alternative (using `track_id`) is provably worse, generating systematic 4-5× over-counting. The ReID approach errs on the side of undercounting, which is the conservative and professionally defensible direction for business metrics.

---

## Decision 4 (Bonus): Storage — SQLite for the Challenge, Designed for PostgreSQL in Production

**Choice: SQLite with SQLAlchemy ORM**

SQLite was chosen for the challenge submission because:
1. Zero infrastructure dependency — `docker compose up` works with no external services
2. `DATABASE_URL` is an environment variable; swapping to `postgresql://...` requires zero code changes
3. SQLite's WAL mode handles concurrent reads without blocking, which is all we need for this traffic level

In a production retail system with 40+ stores and 30fps event streams, the migration path is:
1. Set `DATABASE_URL=postgresql://...` 
2. Add `asyncpg` driver
3. Add a TimescaleDB extension for time-series indexing on `event.timestamp`
4. Add Redis for SSE broadcast fan-out across multiple API instances

The ORM abstraction layer (SQLAlchemy 2.0 declarative base) makes this a deployment decision, not a code rewrite.
