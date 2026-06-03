# CHOICES.md — Key Technical Decisions

## Decision 1: Detection Model Selection

### The Question
Which object detection model should be used as the foundation for the detection pipeline?

### Options Considered

| Model | Pros | Cons |
|-------|------|------|
| YOLOv8m | Excellent speed/accuracy balance, ByteTrack built-in via supervision, COCO pretrained (person class is class 0), active community, runs at ~20fps on RTX 3050 at 1080p | Not the highest accuracy model available |
| YOLOv9 | Better accuracy than v8 on some benchmarks | Less mature ecosystem, supervision integration less tested, slower |
| RT-DETR | Transformer-based, strong at occlusion handling | Memory-hungry, slower on 6GB VRAM, harder to integrate with ByteTrack |
| MediaPipe | Very fast, works on CPU | Poor accuracy at retail CCTV distances (~3-6m), designed for close-up pose |
| CLIP / GPT-4V (VLM) | Could do zero-shot person + zone + staff classification in one pass | API cost, latency (>1s per frame), not viable for video pipeline |

### What AI Suggested
I asked Claude to evaluate these options for a 6GB GPU, 1080p, 30fps input, blurred faces. Claude recommended YOLOv8 as the starting point and specifically YOLOv8m as the sweet spot — not 'n' or 's' (too low accuracy for group detection at distance) and not 'l' or 'x' (VRAM risk at 1080p). It warned against RT-DETR for this VRAM budget.

I also separately asked about using a VLM for zone classification. Claude's suggestion: use GPT-4V or Gemini Vision to classify which zone a person is in based on the bounding box region + a store layout diagram. I evaluated this and rejected it for real-time use — the latency would make 30fps processing take hours. However, I see value in using VLMs for post-hoc validation of zone classifications on a sample of frames.

### What I Chose and Why
**YOLOv8m** on CUDA.

Reasons:
1. The pretrained COCO weights detect "person" (class 0) well at retail distances with natural variation.
2. `supervision` library provides ByteTrack integration with a single function call — faster development.
3. Running at stride 2 (every 2nd frame) on an RTX 3050 takes ~60ms/frame including tracking, leaving headroom for zone classification.
4. The medium variant handles the edge cases in the footage: partial occlusion (multi-scale feature detection), group entry (separate bounding boxes per person), and varying lighting (well-calibrated BN layers from COCO training).

I chose NOT to use a VLM for any real-time pipeline stage. The clips are 2-3 minutes each — at 1 API call per frame that would be 3600-5400 API calls at ~$0.01-0.02 per call = $36-$108 per clip. For batch post-processing or validation, a VLM is sensible. Not for the hot path.

---

## Decision 2: Event Schema Design

### The Question
How should the event schema be structured to support all the analytics queries required by the API?

### Options Considered

**Option A: Flat schema** — all fields at the top level, no nested metadata. Simpler to parse but requires nullable columns for every optional field.

**Option B: Nested metadata object** — core fields at top level, optional/type-specific fields in `metadata`. Matches the spec's sample schema exactly and allows extensibility.

**Option C: Polymorphic schemas** — different schema per event_type (EntryEvent, ZoneDwellEvent, etc.). Strongly typed but breaks batch processing (can't validate a mixed batch uniformly).

### What AI Suggested
Claude suggested Option B (nested metadata) and specifically called out that the `session_seq` field is crucial for debugging: without an ordinal event position per session, replay and debugging becomes very hard. It also suggested adding a `camera_id` field early (before the spec made it explicit) to support cross-camera deduplication at the API level.

I agreed with both suggestions. I also added `confidence` as a first-class field (not buried in metadata) because filtering by confidence threshold is a core analytics operation.

### What I Chose and Why
**Option B: Nested metadata**, exactly as specified, with:
- `confidence` as a top-level field (not suppressed even when low — flag it, keep it)
- `session_seq` in metadata for replay/debugging
- `queue_depth` in metadata (only meaningful for BILLING_QUEUE_JOIN events)
- `is_staff` at top level so all metric queries can filter it in a single WHERE clause

The key design principle: **never silently drop low-confidence events**. The spec explicitly calls this out. A detection with confidence=0.21 that happens to be the only record of a re-entry is better than a clean log with a missing REENTRY event.

---

## Decision 3: API Storage — SQLite vs PostgreSQL

### The Question
What storage engine should back the Intelligence API?

### Options Considered

| Option | Pros | Cons |
|--------|------|------|
| SQLite | Zero-config, single file, Dockerizes trivially, no port conflicts | Write concurrency limited (WAL mode helps), not distributed |
| PostgreSQL | Production-grade, full concurrency, partitioning, extensions (TimescaleDB) | Requires separate container, ~15 seconds startup, credentials management |
| Redis | Extremely fast for real-time metrics | Not a relational store, complex to query for funnel/heatmap |
| DuckDB | Excellent analytical query performance | Less suitable for high-write OLTP (ingest endpoint) |

### What AI Suggested
Claude initially recommended PostgreSQL with TimescaleDB for time-series capabilities, citing that at 40 stores sending events in real time, SQLite would become a bottleneck. It estimated SQLite WAL mode handles ~1000 writes/second, which could be a concern.

I pushed back: for the challenge, we are processing 5 clips offline and replaying events. The ingest rate is bounded by the detection pipeline throughput, not 40 live stores. At challenge scale, SQLite is more than adequate.

Claude then agreed and noted that **the correct decision is SQLite for the challenge** and **PostgreSQL for production**, and that documenting this distinction is itself good engineering.

### What I Chose and Why
**SQLite** for the challenge, with a clear migration path documented:

```python
# Current (challenge)
DATABASE_URL = "sqlite:///./data/store_intelligence.db"

# Production (40 stores, live feed)
DATABASE_URL = "postgresql://user:pass@db:5432/apex_retail"
```

The choice of SQLAlchemy as the ORM means this is a one-line change. The schema uses standard SQL — no SQLite-specific syntax.

**What breaks at 40 live stores**: SQLite's single-writer limitation. With 40 stores each sending a batch of events every 30 seconds, you'd have contention on the events table write lock. PostgreSQL with row-level locking and connection pooling (via PgBouncer) would be the right move. I would also add a Redis cache in front of the metric queries (TTL=30s) so 40 concurrent `/metrics` requests don't each hit the DB.

This is exactly the answer I'd give in a follow-up question about scaling.
