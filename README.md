# Apex Retail Store Intelligence

> **End-to-end CCTV → Analytics pipeline for physical retail stores.**
> From raw camera footage to a live, queryable REST API — and a real-time React Command Center.

---

## Live Deployments

| Service | URL |
|---------|-----|
| **Backend API** | `https://purplle-tech-challenge-production.up.railway.app` |
| **Live Dashboard** | `https://purplle-tech-challenge.vercel.app` |
| **Swagger UI** | `https://purplle-tech-challenge-production.up.railway.app/docs` |
| **Built-in Dashboard** | `https://purplle-tech-challenge-production.up.railway.app/dashboard` |

---

## Quick Start — Local (5 Commands)

```bash
# 1. Clone the repository
git clone https://github.com/safalsingh1/Purplle-tech-challenge.git store-intelligence && cd store-intelligence

# 2. Start the API  
docker compose up -d

# 3. Verify it's running  
curl http://localhost:8000/health

# 4. Run the detection pipeline against your CCTV clips
pip install -r requirements.txt
python run_pipeline.py --clips-dir "path/to/CCTV Footage"

# 5. Ingest the generated events into the API
python -c "
import json, httpx
events = [json.loads(l) for l in open('data/events.jsonl') if l.strip()]
for i in range(0, len(events), 500):
    r = httpx.post('http://localhost:8000/events/ingest', json={'events': events[i:i+500]})
    print(r.json())
"
```

Then open **http://localhost:8000/dashboard** for the built-in live dashboard,  
or run `cd frontend && npm install && npm run dev` to launch the full React Command Center at **http://localhost:3000**.

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events/ingest` | POST | Ingest batches of up to 500 detection events (idempotent by `event_id`) |
| `/stores/{id}/metrics` | GET | Real-time: visitors, conversion rate, dwell per zone, queue depth, abandonment |
| `/stores/{id}/funnel` | GET | Conversion funnel: Entry → Zone → Billing → Purchase with drop-off % |
| `/stores/{id}/heatmap` | GET | Zone visit frequency + dwell, normalised 0–100 |
| `/stores/{id}/anomalies` | GET | Active anomalies with severity (INFO/WARN/CRITICAL) and suggested actions |
| `/health` | GET | Service health + per-store feed lag status |
| `/dashboard` | GET | Live HTML dashboard (SSE-based, no JS framework) |
| `/docs` | GET | Interactive Swagger UI |

**Example store ID**: `STORE_BLR_002`

```bash
curl http://localhost:8000/stores/STORE_BLR_002/metrics
curl http://localhost:8000/stores/STORE_BLR_002/funnel
curl http://localhost:8000/stores/STORE_BLR_002/heatmap
curl http://localhost:8000/stores/STORE_BLR_002/anomalies
curl http://localhost:8000/health
```

---

## Running the Detection Pipeline

The detection pipeline processes CCTV clips and emits structured events to a JSONL file.

### Prerequisites

```bash
pip install -r requirements.txt
# YOLOv8m weights auto-download on first run (~52 MB)
# GPU (CUDA) is used if available; falls back to CPU automatically
```

### Process all clips (batch mode)

```bash
python run_pipeline.py \
  --clips-dir "path/to/CCTV Footage" \
  --layout data/store_layout.json \
  --output data/events.jsonl
```

### Stream events to the API in real time (Part E live demo)

```bash
# Terminal 1: start API
docker compose up

# Terminal 2: run pipeline and POST each event to the API live
python run_pipeline.py \
  --clips-dir "path/to/CCTV Footage" \
  --api-url http://localhost:8000

# Terminal 3: start the live React dashboard
cd frontend && npm install && npm run dev
# Open http://localhost:3000 — metrics update in real time
```

### Use the built-in simulation (no CCTV clips needed)

If you don't have the raw clips handy, the pre-generated events can be replayed via the simulation controller:

```bash
# Start API
docker compose up -d

# Trigger simulation (replays data/events.jsonl at 1x speed)
curl -X POST "http://localhost:8000/simulation/start?speed=1.0&cam_id=CAM_1"

# Speed it up without restarting
curl -X POST "http://localhost:8000/simulation/speed?speed=5.0"

# Stop it
curl -X POST http://localhost:8000/simulation/stop
```

---

## Running Tests

```bash
# From the store-intelligence directory
pytest tests/ -v --cov=app --cov=pipeline --cov-report=term-missing

# Quick run (stop on first failure)
pytest tests/ -x

# Coverage badge values
pytest --cov=app --cov-report=term | tail -5
```

All **138 tests** pass across 11 test files with **89% coverage** covering ingestion, metrics, funnel, anomalies, pipeline schema, API endpoints, new POS schemas, and dashboard SSE/HTML edge cases.

---

## Deploying to Railway (Backend)

Railway can deploy directly from your Git repo.

### Steps

1. Push your repo to GitHub (make sure `data/store_intelligence.db` is gitignored but `data/events.jsonl` and `data/pos_transactions.csv` are **committed**).

2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select `store-intelligence`.

3. Railway auto-detects the `Dockerfile`. It will build and deploy.

4. Add these **environment variables** in Railway's Settings → Variables:

   | Variable | Value |
   |----------|-------|
   | `DATABASE_URL` | `sqlite:///./data/store_intelligence.db` |
   | `POS_CSV_PATH` | `data/pos_transactions.csv` |

   > Railway automatically sets `PORT`. The Dockerfile reads `${PORT:-8000}` so no changes needed.

5. Railway will give you a public URL like `https://apex-store-intelligence-production.railway.app`.

6. Test it:
   ```bash
   curl https://apex-store-intelligence-production.railway.app/health
   curl https://apex-store-intelligence-production.railway.app/stores/STORE_BLR_002/metrics
   ```

> **Note on GPU:** Railway's free and hobby plans are CPU-only. The pipeline automatically detects this and runs YOLOv8 on CPU. Expect ~3–5 fps instead of ~20 fps per clip. The API itself (no YOLO) is fully performant on CPU.

---

## Deploying to Vercel (Frontend)

1. In `frontend/`, the React app reads `VITE_API_URL` at build time to know where the backend is.

2. Push your repo to GitHub.

3. Go to [vercel.com](https://vercel.com) → **New Project** → import your GitHub repo → set **Root Directory** to `frontend/`.

4. Add this **environment variable** in Vercel → Settings → Environment Variables:

   | Variable | Value |
   |----------|-------|
   | `VITE_API_URL` | `https://purplle-tech-challenge-production.up.railway.app` |

5. Deploy. Vercel will run `npm run build` and serve the `dist/` folder.

6. Your dashboard is now live at `https://purplle-tech-challenge.vercel.app`.

> **CORS:** The backend has `allow_origins=["*"]` enabled so Vercel's domain is automatically allowed.

---

## Project Structure

```
store-intelligence/
├── pipeline/
│   ├── detect.py          # Main YOLO + ByteTrack detection loop (CPU/GPU auto-select)
│   ├── tracker.py         # Re-ID: torso HSV hash, cross-camera dedup, re-entry detection
│   ├── zone_classifier.py # Polygon ray-casting zone assignment (resolution-agnostic)
│   ├── staff_detector.py  # HSV colour histogram + duration heuristics for staff exclusion
│   ├── emit.py            # Event schema (Pydantic) + JSONL writer + real-time POST
│   └── run.sh             # Shell wrapper for pipeline (Linux/macOS)
├── app/
│   ├── main.py            # FastAPI entrypoint + middleware + simulation controller
│   ├── models.py          # SQLAlchemy ORM + Pydantic API schemas
│   ├── database.py        # SQLite/SQLAlchemy setup + health check
│   ├── ingestion.py       # Batch ingest with idempotent dedup (savepoints)
│   ├── metrics.py         # Real-time metric computation + conversion rate
│   ├── funnel.py          # 4-stage conversion funnel with session dedup
│   ├── anomalies.py       # Rule-based anomaly detection (4 anomaly types)
│   ├── heatmap.py         # Zone heatmap with normalised scores 0–100
│   ├── health.py          # Health check logic + STALE_FEED detection
│   └── dashboard.py       # SSE live dashboard + broadcast infrastructure
├── frontend/
│   ├── src/
│   │   ├── App.tsx            # Main React app + routing
│   │   ├── hooks/useStoreSSE.ts  # SSE hook with exponential backoff reconnect
│   │   └── components/        # MetricCard, FunnelChart, HeatmapChart, AnomaliesLog, etc.
│   ├── vite.config.ts         # Reads VITE_API_URL for Railway/Vercel
│   └── vercel.json            # Vercel deployment config
├── tests/
│   ├── conftest.py
│   ├── test_ingestion.py   # Ingest, idempotency, validation (14 tests)
│   ├── test_metrics.py     # Metric computation edge cases (13 tests)
│   ├── test_funnel.py      # Funnel + session deduplication (9 tests)
│   ├── test_anomalies.py   # Anomaly detection correctness (15 tests)
│   ├── test_pipeline.py    # Schema compliance, event emission (28 tests)
│   └── test_additional_coverage.py  # Heatmap, health, dashboard, simulation (17 tests)
├── data/
│   ├── store_layout.json   # Zone polygon definitions per camera
│   ├── pos_transactions.csv # Timestamped POS records (6 transactions in 2-min window)
│   └── events.jsonl        # Pre-generated 12-visitor 2-minute simulation dataset
├── docs/
│   ├── DESIGN.md           # Architecture + AI-assisted decisions
│   └── CHOICES.md          # 3 key technical decisions with full reasoning
├── detection_stream.py     # Standalone MJPEG server for live YOLO stream (port 8001)
├── run_pipeline.py         # Windows-friendly pipeline runner
├── docker-compose.yml      # One-command startup (Railway PORT env var compatible)
├── Dockerfile              # Multi-stage build (CPU/GPU compatible)
├── requirements.txt        # All Python dependencies
└── README.md
```

---

## Architecture Summary

```
CCTV Clips (MP4)
     │
     ▼
┌─────────────────────────────────────────────┐
│  Detection Layer (pipeline/)                 │
│  YOLOv8m (CUDA/CPU) → ByteTrack → Events   │
│  Staff detection (HSV histogram + duration)  │
│  Zone classifier (polygon ray-casting)       │
│  Re-ID tracker (torso HSV hash + time window)│
└──────────────┬──────────────────────────────┘
               │ events.jsonl / real-time POST
               ▼
┌─────────────────────────────────────────────┐
│  Intelligence API (FastAPI + SQLite)         │
│  POST /events/ingest (idempotent, 500/batch) │
│  GET  /stores/{id}/metrics                   │
│  GET  /stores/{id}/funnel                    │
│  GET  /stores/{id}/heatmap                   │
│  GET  /stores/{id}/anomalies                 │
│  GET  /health                                │
└──────────────┬──────────────────────────────┘
               │ Server-Sent Events (SSE)
               ▼
┌─────────────────────────────────────────────┐
│  Live Dashboard (Part E)                     │
│  /dashboard — built-in HTML (no framework)  │
│  localhost:3000 — React + Vite Command Center│
└─────────────────────────────────────────────┘
```

**Detailed design decisions** → [docs/DESIGN.md](docs/DESIGN.md)  
**Key technical choices** → [docs/CHOICES.md](docs/CHOICES.md)

---

## Live Dashboard Features (Part E)

The React Command Center at **http://localhost:3000** (or your Vercel URL) shows:

- 🔴 **Live connection indicator** — SSE connection status with exponential backoff reconnect
- 📊 **Real-time KPI cards** — unique visitors, conversion rate, queue depth, abandonment rate — with delta badges showing per-update changes
- 🔽 **Conversion funnel SVG chart** — live drop-off percentages at each stage
- 🌡️ **Zone heatmap** — zone visit frequency with normalised intensity
- 🚨 **Anomaly log** — colour-coded alerts with `suggested_action` strings
- 📹 **Camera feed viewer** — browser-native video player for CCTV clips via HTTP range requests
- ⏱️ **Simulation controls** — start/stop/speed controls to replay events at 1x–10x speed

Updates appear within **< 100ms** of events hitting `/events/ingest`.

---

## Edge Cases Handled

| Edge Case | How the System Handles It |
|-----------|--------------------------|
| Group entry (2–4 people) | Each ByteTrack bounding box = 1 ENTRY event. YOLOv8m detects individuals in groups. |
| Staff movement | Dual heuristic: track duration ≥ 65% of clip + torso HSV uniform clustering → `is_staff=true`, excluded from all metrics. |
| Re-entry | ReIDTracker matches returning visitor by appearance hash within 10-minute window → emits `REENTRY` not a second `ENTRY`. |
| Partial occlusion | `confidence_threshold=0.20` keeps uncertain detections. Confidence score included in every event — never silently dropped. |
| Billing queue buildup | Queue depth tracked per `BILLING_QUEUE_JOIN` event. `BILLING_QUEUE_ABANDON` emitted when visitor leaves zone before transaction. |
| Empty store periods | All metric queries handle zero-visitor state gracefully — no nulls, no crashes. Conversion rate returns `0.0`. |
| Cross-camera overlap | ReIDTracker's appearance pool matches same visitor across cameras within 30s window using torso HSV hash. |

---

## Design Documents

- **[docs/DESIGN.md](docs/DESIGN.md)** — Architecture overview, zone classification design, Re-ID approach, AI-assisted decisions (ByteTrack choice, staff heuristics, conversion window)
- **[docs/CHOICES.md](docs/CHOICES.md)** — Full reasoning for model selection (YOLOv8m vs alternatives), event schema design (Option B: nested metadata), storage choice (SQLite → PostgreSQL migration path)
