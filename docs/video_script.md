# 🎬 APEX RETAIL STORE INTELLIGENCE — DEMO VIDEO SCRIPT
# Duration Target: ~3–4 minutes
# Format: Screen recording with voiceover
# Tone: Confident, technical, concise. Like a senior engineer presenting to a hiring panel.

---

## ⏱️ [0:00 – 0:20] HOOK / INTRO

**[SCREEN: Show the live deployed dashboard at https://purplle-tech-challenge.vercel.app]**

> "Retail stores are flying blind. Every online click is tracked.
> But the moment a customer walks through a physical door — nothing.
> This is Apex Retail Store Intelligence.
> In the next 3 minutes, I'll show you this fully deployed, containerised store analytics system 
> running live on Vercel and Railway, showing how we go from raw camera streams to real-time metrics."

---

## ⏱️ [0:20 – 0:50] ARCHITECTURE Overview

**[SCREEN: Show docs/DESIGN.md in VS Code — scroll to the architecture diagram]**

> "The system consists of four key layers:
>
> 1. **The Detection Pipeline:** Runs YOLOv8 and ByteTrack on raw video clips to emit entry, exit, and zone events.
> 2. **The Intelligence API:** A FastAPI backend backed by SQLite, fully containerised with Docker and deployed on Railway.
> 3. **The Live Data Stream:** Server-Sent Events (SSE) that broadcast updates to client applications in under 100ms.
> 4. **The Premium Dashboard:** A React frontend deployed on Vercel that renders real-time retail intelligence."

---

## ⏱️ [0:50 – 1:35] LIVE DASHBOARD & SIMULATION CONTROL

**[SCREEN: Switch to Vercel Frontend (https://purplle-tech-challenge.vercel.app)]**

> "Here is our live dashboard. All metrics are updated in real-time.
> Let's head over to the **Cameras** tab to control the playback."

**[SCREEN: Click on "Cameras" tab. Click the "🔄 Sync & Restart" button, then click "5.0x" speed button]**

> "By clicking 'Sync & Restart', we trigger the backend simulation to reset the database and stream events from the beginning.
> I will speed it up to 5x so we can watch the metrics tick up quickly."

**[SCREEN: Click back to the "Dashboard" tab. Watch the visitors, conversion rate, queue depth, and timeline update in real time]**

> "As the events stream in, the visitor count climbs in real time. The conversion funnel updates dynamically.
> The timeline log records each visitor's journey, and the active queue depth keeps track of the billing queue.
>
> This is driven by Server-Sent Events — the pipeline emits structured events, the Railway backend processes them, and broadcasts the updates to the Vercel frontend in under 100ms."

---

## ⏱️ [1:35 – 2:15] DYNAMIC CAMERA FEED & BACKEND FALLBACK

**[SCREEN: Click back to the "Cameras" tab. Show the camera player playing the simulated YOLO stream]**

> "If we look at the live video stream, you can see YOLOv8 bounding boxes, tracker IDs, and zone polygon overlays.
>
> Since raw CCTV video files are extremely large (~680MB) and cannot be pushed to a cloud container, 
> I built a **resilient backend-hosted camera fallback**. 
>
> When the local YOLO server is offline, the Railway backend dynamically generates a simulated store overlay stream! 
> It loads the camera zone coordinates from the layout file, moves mock customers through them, and streams it as MJPEG.
>
> If you run the YOLO detection stream locally on your machine, the frontend automatically detects it 
> and seamlessly switches to the local GPU stream, showing 'YOLO LIVE (LOCAL)'."

**[SCREEN: Click on different camera thumbnails (CCTV 2, CCTV 3) to show the stream and zones switching dynamically]**

> "You can switch between any of the 5 cameras. The backend dynamically updates the overlays, labels, and stats for Skincare, Haircare, or the Billing Counter."

---

## ⏱️ [2:15 – 2:45] API CORRECTNESS & ENDPOINTS

**[SCREEN: Switch to Terminal or Postman. Show requests to Railway endpoints]**

```bash
# Windows PowerShell (Native formatting):
Invoke-RestMethod -Uri "https://purplle-tech-challenge-production.up.railway.app/stores/STORE_BLR_002/metrics" | ConvertTo-Json -Depth 5

# Linux / Mac Bash / Git Bash (using curl and jq):
curl -s "https://purplle-tech-challenge-production.up.railway.app/stores/STORE_BLR_002/metrics" | jq .

# -------------------------------------------------------------
# Additional endpoints can be fetched similarly (Metrics, Funnel, Heatmap, Anomalies, Health)
# e.g., Funnel endpoint:
# PowerShell:
Invoke-RestMethod -Uri "https://purplle-tech-challenge-production.up.railway.app/stores/STORE_BLR_002/funnel" | ConvertTo-Json
# Bash:
curl -s "https://purplle-tech-challenge-production.up.railway.app/stores/STORE_BLR_002/funnel" | jq .
```

> "All five required endpoints are fully functional on Railway. 
> Responses are returned as structured, validated JSON. 
> Ingestion is completely idempotent, and we return a 503 health warning if the database is unavailable, never exposing raw stack traces."

---

## ⏱️ [2:45 – 3:10] AUTOMATED TESTS

**[SCREEN: Switch to terminal and run tests]**

```bash
pytest tests/ -v
```

**[Wait for the 98 tests to pass successfully]**

> "I wrote a robust test suite covering 98 distinct test cases. 
> This includes all major edge cases: empty stores, all-staff clips, visitor re-entry deduplication in the funnel, 
> zero purchases, conversion rate drop anomalies, and stale feed detections. 
> All tests are green."

---

## ⏱️ [3:10 – 3:35] DECISION LOG & NORTH STAR

**[SCREEN: Open docs/CHOICES.md or docs/DESIGN.md in VS Code — scroll slowly]**

> "Every engineering decision has been documented:
>
> - **ByteTrack vs DeepSORT:** Used ByteTrack because its IoU-based tracking performs cleanly even with anonymised/blurred faces.
> - **Torso-Color Re-ID:** Torso color matching deduplicates visitors across cameras without expensive facial recognition.
> - **FastAPI + SQLite:** SQLite provides a zero-config, highly-performant local DB that handles sequential stream writes safely, with a clear path to PostgreSQL for multi-store scaling.
>
> All of these components directly serve our North Star metric: **offline conversion rate**."

---

## ⏱️ [3:35 – 3:45] OUTRO

**[SCREEN: Show the GitHub repo tree in the terminal]**

> "The codebase is containerised and ready. 
> The frontend and backend are fully deployed and running. 
> Thank you, and I look forward to your follow-up questions."

**[Fade to black / end recording]**

---

# 📋 RECORDING TIPS

- **Resolution:** 1920×1080.
- **Audio:** Use a clean microphone in a quiet room.
- **Speed:** Talk at a steady, confident pace.
- **Simulated Stream:** The simulated stream is active and running 24/7 on Railway, meaning your Vercel site is completely self-contained for the reviewers!
