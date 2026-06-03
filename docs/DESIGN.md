# DESIGN.md — Apex Retail Store Intelligence System

## Architecture Overview

This system converts raw CCTV footage from physical retail stores into a live analytics API. It is built in four connected layers:

```
CCTV Clips (MP4)
     │
     ▼
┌────────────────────────────────────────┐
│  Detection Layer                        │
│  YOLOv8m (GPU) → ByteTrack → Events   │
│  Staff detection (HSV histograms)       │
│  Zone classifier (polygon containment)  │
│  Re-ID tracker (appearance hash)        │
└──────────────┬─────────────────────────┘
               │  data/events.jsonl
               ▼
┌────────────────────────────────────────┐
│  Intelligence API (FastAPI)            │
│  POST /events/ingest                   │
│  GET  /stores/{id}/metrics             │
│  GET  /stores/{id}/funnel              │
│  GET  /stores/{id}/heatmap             │
│  GET  /stores/{id}/anomalies           │
│  GET  /health                          │
└──────────────┬─────────────────────────┘
               │  Server-Sent Events
               ▼
┌────────────────────────────────────────┐
│  Live Dashboard                        │
│  /dashboard — SSE, auto-update UI      │
└────────────────────────────────────────┘
```

### Detection Layer

**Model**: YOLOv8m, loaded via the `ultralytics` library and pinned to CUDA device. The 'm' (medium) variant was chosen specifically for the 6GB RTX 3050 — the 'l' model would saturate VRAM at 1080p.

**Tracking**: ByteTrack via the `supervision` library. ByteTrack assigns continuous track IDs across frames even through occlusion, which is the foundation for session continuity. It runs as a filter on top of YOLOv8 detections.

**Frame stride**: Every 2nd frame is processed (~15fps effective at 30fps source). This halves GPU time with negligible accuracy loss — humans don't teleport between frames.

**Zone classification**: Each camera's frame is divided into named polygons from `store_layout.json`. A person's bounding box centroid is tested against these polygons using a ray-casting algorithm. Zones are defined in normalised [0,1] coordinates so the classifier is resolution-agnostic.

**Entry/Exit detection**: A horizontal line (`entry_line_y_ratio`) divides the entry camera frame. A centroid crossing this line from top-to-bottom = ENTRY (customer entering store), bottom-to-top = EXIT. We track the centroid history per track_id and check for line crossings on each frame pair.

**Staff detection**: Two heuristics are combined:
1. **Duration**: Any person whose track spans ≥65% of the total clip duration is staff (customers don't stay for 2.5 minutes straight in a 3-minute clip).
2. **Uniform colour**: We sample the torso region of each bounding box, compute an 18-bin HSV hue histogram, and cluster dominant hues across long-duration tracks. Staff wearing a consistent uniform colour are identified by matching this cluster.

Neither heuristic is perfect in isolation, but together they achieve high precision on the short clips in this dataset.

**Re-ID**: Cross-camera deduplication uses an "appearance hash" — the top-4 dominant 8-bin HSV hue bins from the bounding box region. Two detections within 90 seconds with the same appearance hash are assumed to be the same person. Re-entry detection uses a 10-minute window: a person who exits and re-enters within 10 minutes is flagged as REENTRY rather than a new ENTRY.

### Intelligence API

**Framework**: FastAPI with Uvicorn. FastAPI's async support means the SSE dashboard stream runs concurrently with metric queries without blocking.

**Storage**: SQLite via SQLAlchemy. For the challenge scale (5 clips, 2 stores), SQLite is sufficient. In production at 40 stores, this would be replaced by PostgreSQL with time-based partitioning on the `events` table.

**Idempotency**: `POST /events/ingest` deduplicates by `event_id` before any DB write. The detection pipeline generates UUID v4 event_ids at emission time, so replaying the pipeline output or re-posting the same JSONL file is safe.

**Real-time metrics**: All metric queries hit the database directly — there is no cache. This ensures the API always reflects the latest ingested state. For production scale, a Redis cache with short TTL (30s) would be appropriate.

**Conversion rate correlation**: POS transactions have no customer_id. We correlate by time window: a customer who was in the BILLING_COUNTER or BILLING_QUEUE zone in the 5 minutes preceding any POS transaction at the same store counts as "converted." This is the industry-standard approach when customer identity isn't available in POS data.

**Anomaly detection**: Rule-based, not ML-based. Each anomaly type has a clear threshold:
- BILLING_QUEUE_SPIKE: queue_depth ≥ 5 in 2+ consecutive events
- CONVERSION_DROP: current rate < 70% of rolling average
- DEAD_ZONE: no customer zone visits in 30 minutes
- STALE_FEED: no events received in 10 minutes

The structured `suggested_action` field per anomaly makes this actionable for store managers without requiring them to interpret raw metrics.

### Live Dashboard (Part E)

There are two visualization frontends provided:
1. **Built-in HTML/JS Dashboard**: Serves a fast, single-file template directly from the FastAPI server at `/dashboard`. It uses browser-native `EventSource` to receive Server-Sent Events (SSE) updates instantly.
2. **React + TypeScript Command Center**: A state-of-the-art React + Vite frontend located in the `frontend/` directory, served at `http://localhost:3000`. It features:
   - Custom **glowing glassmorphism styling** with cyberpunk visual cues.
   - Custom **reactive SVG charts** showing vertical conversion funnels and horizontal traffic heatmaps.
   - Dynamic **queue line occupancy telemetry** showing cashier wait points.
   - Real-time **SSE custom hooks** (`useStoreSSE`) with exponential backoff automatic reconnection.

Both update in under 100ms from when events hit the ingest endpoint.

---

## AI-Assisted Decisions

### 1. ByteTrack vs DeepSORT for multi-object tracking

I asked Claude: *"Compare ByteTrack and DeepSORT for retail CCTV tracking where faces are blurred and lighting varies. Which should I choose?"*

Claude's response correctly identified that DeepSORT's appearance feature extractor (typically a ResNet) relies on face/body texture features that are degraded when faces are blurred — ByteTrack uses pure motion (Kalman filter + IoU) which is robust to appearance changes. I agreed with this reasoning and chose ByteTrack. Claude also noted that ByteTrack is now integrated into `ultralytics` directly via `supervision`, which simplified the implementation.

**Decision**: Use ByteTrack. I agreed with the AI recommendation.

### 2. Staff detection approach: re-ID model vs heuristics

I asked Claude: *"I don't have labelled training data for staff vs customer classification. Should I use a zero-shot VLM to classify each bounding box, or use simpler heuristics?"*

Claude initially suggested using GPT-4V or CLIP zero-shot classification per frame, which would have been accurate but extremely slow (API latency per frame) and expensive. After I pushed back, it agreed that for a batch pipeline with 30fps video, per-frame VLM calls are impractical.

**My decision**: I overrode the initial AI suggestion and implemented the colour-histogram + duration heuristic approach. This runs in microseconds per frame and works well for the structured retail environment where staff wear consistent uniforms. I documented this in CHOICES.md.

### 3. Conversion rate correlation method

I asked Claude: *"With no customer_id in POS data, how do I correlate visitors to transactions to compute conversion rate?"*

Claude suggested three approaches: (a) time window matching, (b) session count ratio (transactions/visitors), (c) billing zone dwell pattern matching. It recommended (b) as simplest, but I disagreed — session count ratio double-counts when multiple customers purchase in quick succession and misses the causal link between billing zone presence and transaction.

**My decision**: I implemented (a) time window matching with a 5-minute window before each transaction, tracking which visitors were in the billing zone during that window. This better represents actual conversion intent and is more defensible under follow-up questioning. I partly deviated from the AI recommendation.
