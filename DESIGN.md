# DESIGN.md — Apex Retail Store Intelligence

## 1. Problem Decomposition

The core challenge decomposes into three distinct problems:

1. **Signal Extraction** — How do we turn raw pixel data into structured behavioural events?
2. **Business Logic** — How do we aggregate those events into meaningful retail metrics without double-counting?
3. **Delivery** — How do we surface those metrics in real-time via a queryable API and live dashboard?

Each layer is intentionally decoupled so that any one of them can be swapped without affecting the others.

---

## 2. System Architecture

```
CCTV Video Clips (MP4)
         │
         ▼
┌────────────────────────────────────────────────┐
│  Detection & Tracking Layer  (pipeline/)        │
│                                                  │
│  YOLOv8m  →  ByteTrack  →  ReIDTracker         │
│  ZoneClassifier  →  StaffDetector  →  emit.py  │
│                                                  │
│  Output: Structured events → data/events.jsonl  │
│          OR real-time POST /events/ingest        │
└──────────────────────┬─────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────┐
│  Intelligence API  (app/ — FastAPI)             │
│                                                  │
│  POST /events/ingest   — idempotent batch ingest│
│  GET  /stores/{id}/metrics                       │
│  GET  /stores/{id}/funnel                        │
│  GET  /stores/{id}/heatmap                       │
│  GET  /stores/{id}/anomalies                     │
│  GET  /health                                    │
│  GET  /dashboard   — built-in SSE HTML          │
└──────────────────────┬─────────────────────────┘
                       │ Server-Sent Events (SSE)
                       ▼
┌────────────────────────────────────────────────┐
│  Live Command Center  (frontend/ — React+Vite) │
│  Real-time KPI cards, funnel, heatmap,          │
│  anomaly log, spatial floor map overlay         │
└────────────────────────────────────────────────┘
```

---

## 3. Detection Layer Design

### 3.1 Model Selection
We use **YOLOv8m** (medium) rather than nano or large. The trade-off: nano misses partially occluded people and small bounding boxes at the store entry threshold; large is unnecessarily slow on CPU-only deployment environments. Medium hits the correct operating point for retail surveillance footage at ~20fps on a 4-core CPU or ~60fps with CUDA.

### 3.2 Multi-Camera Tracking Strategy
Each camera runs an independent **ByteTrack** instance. ByteTrack assigns short-lived `track_id` integers per camera per clip. These are ephemeral and NOT used as persistent visitor IDs.

Persistent visitor identity is managed by a custom **ReIDTracker** (`pipeline/tracker.py`) which:
- Extracts a **torso HSV colour histogram** (top 60% of bounding box, 16-bin H, 8-bin S) for each new track.
- On every new detection, computes **cosine similarity** against all known visitor appearance vectors.
- If similarity > 0.82 AND the gap since last seen < 600 seconds → treat as a **re-entry** (`REENTRY` event, same `visitor_id`).
- Otherwise → emit a new `ENTRY` event with a fresh `visitor_id`.

This design deliberately trades perfect accuracy for **predictable correctness**: we only emit `ENTRY` when a person physically crosses the door threshold on `CAM_ENTRY_*`, so the `unique_visitors` count is always grounded in door-crossing evidence — not floor-camera tracker fragments.

### 3.3 Staff Detection
Staff are identified via a dual heuristic in `pipeline/staff_detector.py`:
1. **Duration heuristic**: if a track is present for ≥ 65% of the clip duration, mark `is_staff=true`. Customers browse and leave; staff stay.
2. **Colour uniformity heuristic**: staff often wear uniforms. Tracks whose torso HSV histogram has low spread (Bhattacharyya coefficient < 0.15 relative to a uniform-colour prior) are flagged.

Both criteria must trigger for `is_staff=true`. This prevents false-positives on customers who stop to browse for extended periods.

**Backend safety net**: even if a visitor is misclassified frame-to-frame, the metrics layer builds a **global staff exclusion set** — any `visitor_id` ever seen with `is_staff=True` is permanently excluded from all customer metrics. This prevents even one bad frame from contaminating the unique visitor count.

### 3.4 Zone Classification
Zone boundaries are defined as **normalised resolution-agnostic polygons** in `data/store_layout.json`. The `ZoneClassifier` uses standard **point-in-polygon ray casting** so the same zone definitions work regardless of whether the input video is 720p, 1080p, or 4K.

Events emitted:
| Event Type | Trigger |
|---|---|
| `ENTRY` | Track centroid crosses entry line (y-ratio threshold) moving inward |
| `EXIT` | Track centroid crosses entry line moving outward |
| `REENTRY` | ENTRY-equivalent for a known ReID match |
| `ZONE_ENTER` | Track centroid enters a zone polygon |
| `ZONE_EXIT` | Track centroid exits a zone polygon (dwell_ms populated) |
| `ZONE_DWELL` | Track still inside zone after N frames (heartbeat) |
| `BILLING_QUEUE_JOIN` | Track enters BILLING_QUEUE zone |
| `BILLING_QUEUE_ABANDON` | Track exits BILLING_QUEUE without reaching BILLING_COUNTER |

---

## 4. Intelligence API Design

### 4.1 Idempotent Ingestion
The `POST /events/ingest` endpoint uses `event_id` (UUID) as the deduplication key. Duplicate submissions of the same event are silently ignored via a per-event savepoint check. This means the detection pipeline can be re-run or fail-restart without corrupting the metrics database.

### 4.2 Unique Visitor Counting
`unique_visitors` is counted as:
```sql
COUNT(DISTINCT visitor_id)
WHERE event_type = 'ENTRY'
  AND visitor_id NOT IN (
    SELECT DISTINCT visitor_id WHERE is_staff = TRUE
  )
```

The explicit `ENTRY` requirement ensures floor-camera tracker fragments (people seen in zones but never at the door) are never counted as unique visitors. The global staff exclusion ensures mixed-classification visitors (staff misidentified as customer in one frame) are consistently excluded.

### 4.3 Conversion Rate
Computed via a **5-minute POS correlation window**: for each POS transaction, we find all non-staff visitors who were in `BILLING_COUNTER` or `BILLING_QUEUE` in the 5 minutes prior. The union of these sets (across all transactions) is the converted visitor pool. 

```
conversion_rate = |converted_visitor_set| / unique_visitors
```

This is the industry-standard approach because we don't have linked customer IDs between the camera system and the POS — we correlate by time proximity and physical location.

### 4.4 Conversion Funnel (4-stage, session-level)
```
ENTRY → Zone Visit → Billing Queue → Purchase
```
Each stage uses `DISTINCT visitor_id` to prevent a single visitor browsing 5 zones from being counted 5 times. Re-entries do not create new sessions — `REENTRY` events share the same `visitor_id` as the original `ENTRY`.

### 4.5 Anomaly Detection (4 rule-based anomaly types)
| Anomaly | Trigger |
|---|---|
| `BILLING_QUEUE_SPIKE` | `queue_depth ≥ 5` in ≥ 2 of last 5 queue events |
| `CONVERSION_DROP` | Current conversion rate < 70% of rolling baseline |
| `DEAD_ZONE` | No customer zone visits for a product zone in 30 minutes |
| `STALE_FEED` | No events received for a store in 10 minutes |

### 4.6 Real-time Delivery: SSE
Rather than WebSockets (which require connection state management), we use **Server-Sent Events (SSE)** via `/stores/{id}/stream`. The simulation loop broadcasts a metrics update after every ingested event. The frontend reconnects automatically with exponential backoff. This gives sub-100ms dashboard latency with zero infrastructure overhead.

---

## 5. Edge Cases and Assumptions

| Edge Case | Approach |
|---|---|
| Re-entry | ReIDTracker matches by appearance+time window, emits `REENTRY` (not a second `ENTRY`) |
| Cross-camera same person | ReIDTracker runs globally — same `visitor_id` across CAM_FLOOR_01 and CAM_FLOOR_02 |
| Staff movement | Dual heuristic (duration + colour uniformity) + global backend exclusion set |
| Group entry | YOLOv8 detects individuals within groups; each bounding box = 1 person = 1 `ENTRY` |
| Partial occlusion | Low confidence threshold (0.20) keeps uncertain detections; confidence included in event |
| Queue buildup | `queue_depth` recorded per event; `BILLING_QUEUE_ABANDON` emitted on early exit |
| Zero visitors | All metric endpoints return `0` values, not null/error |
| Empty store | `active_visitors` uses `ingested_at` timestamp (real-time) so it decays to 0 naturally |

---

## 6. Production Readiness

- **Docker**: single `docker compose up` starts the API on port 8000 with health check
- **SQLite → PostgreSQL**: swap is a one-line `DATABASE_URL` env var change; SQLAlchemy ORM handles everything else
- **Structured JSON logging**: every request logs `trace_id`, `latency_ms`, `store_id`, `endpoint`, `status_code`
- **Test coverage**: 140 tests across 11 files covering ingestion, metrics, funnel, anomaly detection, pipeline schema, and API endpoints
- **Railway + Vercel**: API deployed to Railway, React dashboard deployed to Vercel (CORS pre-configured)

---

## 7. AI-Assisted Engineering Decisions

This section documents where AI assistance directly shaped engineering decisions, what the AI identified, what alternatives were considered, and how the final approach was validated.

### 7.1 Re-ID Tracker Architecture

**Problem identified by AI:** ByteTrack assigns monotonically increasing `track_id` values *within a single video clip session*. When a new clip is loaded, IDs reset from 0. Across 4 cameras and 6 video clips, this creates 24 instances of `track_id=1`, making `visitor_id` globally non-unique. Additionally, ByteTrack re-assigns IDs when a person is occluded for >2 seconds, turning one real customer into 3–4 `visitor_id` values during a single visit.

**AI's recommendation:** Build a persistent appearance-based Re-ID layer *above* ByteTrack. Use HSV colour histograms (top 60% of bounding box) as a lightweight appearance descriptor. Match new detections to known visitors using cosine similarity.

**Threshold tuning:** The AI suggested starting at 0.80 and testing empirically. After validation against the provided footage:
- Below 0.80: different customers in similar-coloured clothing are merged (false match).
- Above 0.85: the same customer after lighting angle change is split (false split).
- **Final threshold: 0.82** — minimises both error types on this footage.

**Re-entry window:** AI recommended 600 seconds (10 minutes) as the maximum gap for re-entry matching. Longer gaps introduce appearance drift (changed lighting, angle, accessories) that makes the histogram unreliable. This parameter is configurable via environment variable.

---

### 7.2 Global Staff Exclusion vs. Per-Event Flag

**Problem identified by AI:** During metric validation, the AI audited the database and found that several visitor IDs had mixed `is_staff` labels — the same person's bounding box was classified as staff in some frames and customer in others due to pose changes (e.g., staff member bending over a shelf looks like a browsing customer). A simple `WHERE is_staff=0` filter would let those events through, inflating unique visitor counts.

**AI's recommendation:** Build a *global exclusion subquery* that identifies any `visitor_id` ever flagged as staff, and exclude that entire ID from all customer metrics — regardless of per-event flag value. This is a pessimistic, conservative approach that accepts a small false-exclusion risk in exchange for never over-counting.

```sql
-- Global staff ID set used in all metric queries
staff_ids AS (
    SELECT DISTINCT visitor_id FROM events WHERE is_staff = 1
)
SELECT COUNT(DISTINCT visitor_id) FROM events
WHERE event_type = 'ENTRY'
  AND visitor_id NOT IN (SELECT visitor_id FROM staff_ids)
```

**Validation:** Applied to the test dataset, this reduced unique visitor count from an inflated ~82 to a grounded ~20, which is visually consistent with what the footage actually shows.

---

### 7.3 `ingested_at` vs. `event.timestamp` for Active Visitor Window

**Problem identified by AI:** The CCTV footage is historical (recorded March 3rd, 2026). If `active_visitors` is computed as visitors seen in the last 2 minutes by `event.timestamp`, the count drops to 0 the moment event replay pauses — making the floor map freeze at zero even though the simulation just ran.

**AI's recommendation:** Track two timestamps per event:
- `timestamp` — the video wall-clock time (business logic, historical, for analytics)
- `ingested_at` — the real-world wall-clock of the API write (for freshness/recency)

The `active_visitors` metric uses `ingested_at` to measure recency, so it naturally decays to 0 over the configured window *after* ingestion stops, regardless of when the footage was recorded.

**Impact:** This makes the floor map animation look live and natural — dots fade out organically 2 minutes after the simulation ends, rather than cutting to zero abruptly.

---

### 7.4 Conversion Rate via POS Time-Window Join

**Problem identified by AI:** Simple conversion (billing zone visitors / total visitors) would be wrong because staff members also pass through the billing zone, and a customer can visit the zone multiple times without purchasing. The AI proposed joining the visitor event log to POS transaction records using a time-window overlap: a visitor "converts" only if a POS transaction occurs within ±15 minutes of their billing zone entry.

**SQL approach generated with AI assistance:**

```sql
SELECT COUNT(DISTINCT e.visitor_id)
FROM events e
JOIN pos_transactions t ON t.store_id = e.store_id
WHERE e.event_type = 'ZONE_ENTER'
  AND e.zone_id LIKE '%BILLING%'
  AND e.visitor_id NOT IN (SELECT visitor_id FROM staff_ids)
  AND ABS(CAST((julianday(t.timestamp) - julianday(e.timestamp)) * 86400 AS INTEGER)) < 900
```

This prevents billing zone walkthroughs (e.g., exiting the store past the counter) from being miscounted as purchases.
