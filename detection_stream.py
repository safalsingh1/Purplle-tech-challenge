"""
detection_stream.py — Standalone MJPEG server that runs YOLOv8 + ByteTrack
on the CCTV clips and streams annotated frames to the browser.

Draws:
  - Person bounding boxes (colour-coded by track ID)
  - Track ID labels
  - Zone polygon overlays (semi-transparent fills)
  - Entry line (for entry cameras)
  - Frame counter + FPS overlay
  - Detection count badge

Usage:
  python detection_stream.py
  python detection_stream.py --cam CAM_ENTRY_01 --speed 1.0 --port 8001

Streams at: http://localhost:8001/stream
"""

import argparse
import json
import logging
import sys
import time
import threading
import io
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO
import supervision as sv
from flask import Flask, Response, jsonify
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("detect_stream")

# ── Config ───────────────────────────────────────────────────────────────────

LAYOUT_PATH = "data/store_layout.json"
CLIPS_DIR   = "../CCTV Footage"
if not Path(CLIPS_DIR).exists() and Path("../new resouces/all_clips").exists():
    CLIPS_DIR = "../new resouces/all_clips"
MODEL_PATH  = "yolov8n.pt"
CONF_THRESH = 0.25
IOU_THRESH  = 0.45
PERSON_CLASS = 0
FRAME_STRIDE = 2      # process every 2nd frame

# Zone colour map (BGR) — one per zone type
ZONE_COLORS = {
    "ENTRY_THRESHOLD":  (0,   220, 100),
    "BILLING_COUNTER":  (0,   140, 255),
    "BILLING_QUEUE":    (0,    80, 220),
    "SKINCARE":         (180,  60, 255),
    "HAIRCARE":         (255, 120,  60),
    "FRAGRANCES":       (60,  200, 255),
    "WELLNESS":         (60,  255, 180),
    "IMPULSE_BUYS":     (80,  200, 255),
}
DEFAULT_ZONE_COLOR = (100, 100, 200)

# Track ID → distinct BGR colour (cycle through 20 colours)
_TRACK_PALETTE = [
    (255, 80,  80),  (80, 255,  80),  (80,  80, 255), (255, 255,  80),
    (255,  80, 255), (80, 255, 255),  (255, 160,  80), (80, 160, 255),
    (160, 255,  80), (255,  80, 160), (160,  80, 255), (80, 255, 160),
    (220, 220,  80), (80, 220, 220),  (220,  80, 220), (200, 120, 60),
    (60, 200, 120),  (120,  60, 200), (180, 200,  60), (60, 180, 200),
]

def track_color(track_id: int):
    return _TRACK_PALETTE[int(track_id) % len(_TRACK_PALETTE)]


# ── Layout helpers ───────────────────────────────────────────────────────────

# Mapping of standard camera IDs to filenames
CAM_MAP = {
    "CAM_1": "CAM 1 - zone.mp4",
    "CAM_2": "CAM 2 - zone.mp4",
    "CAM_3": "CAM 3 - entry.mp4",
    "CAM_4": "CAM 4.mp4",
    "CAM_5": "CAM 5 - billing.mp4",
    "CAM_S2_ENTRY1": "entry 1.mp4",
    "CAM_S2_ENTRY2": "entry 2.mp4",
    "CAM_S2_ZONE": "zone.mp4",
    "CAM_S2_BILLING": "billing_area.mp4",
    "CAM_ENTRY_01": "cam1_entry.mp4",
    "CAM_FLOOR_01": "cam2_floor.mp4",
    "CAM_BILLING_01": "cam6_billing.mp4",
}

def load_layout():
    with open(LAYOUT_PATH, "r") as f:
        return json.load(f)

def get_cam_info(layout: dict, cam_id: str):
    """Find (store_id, cam_data) for a given cam_id (layout ID or standard ID)."""
    filename = CAM_MAP.get(cam_id.upper())
    if filename:
        for store_id, store in layout["stores"].items():
            for cid, cam in store["cameras"].items():
                if cam["clip_file"] == filename:
                    return store_id, cam
    
    # Fallback to searching by layout camera ID
    for store_id, store in layout["stores"].items():
        for cid, cam in store["cameras"].items():
            if cid == cam_id:
                return store_id, cam
    return None, None

def all_cameras(layout: dict):
    cams = []
    # Map layout cameras to standard IDs where possible
    inv_map = {v: k for k, v in CAM_MAP.items()}
    for store_id, store in layout["stores"].items():
        for cid, cam in store["cameras"].items():
            clip = cam["clip_file"]
            std_id = inv_map.get(clip, cid)
            cams.append({
                "cam_id":      std_id,
                "layout_id":   cid,
                "store_id":    store_id,
                "clip_file":   clip,
                "type":        cam.get("type", "unknown"),
                "description": cam.get("description", ""),
            })
    return cams


# ── Zone overlay helpers ─────────────────────────────────────────────────────

def draw_zones(frame: np.ndarray, cam_data: dict, alpha: float = 0.18):
    h, w = frame.shape[:2]
    overlay = frame.copy()
    zones = cam_data.get("zones", {})

    for zone_name, zone_def in zones.items():
        poly_norm = zone_def["polygon"]
        pts = np.array([[int(x * w), int(y * h)] for x, y in poly_norm], dtype=np.int32)
        color = ZONE_COLORS.get(zone_name, DEFAULT_ZONE_COLOR)

        # Fill
        cv2.fillPoly(overlay, [pts], color)

        # Border
        cv2.polylines(overlay, [pts], isClosed=True, color=color, thickness=2)

        # Label at centroid
        cx = int(np.mean(pts[:, 0]))
        cy = int(np.mean(pts[:, 1]))
        label = zone_name.replace("_", " ")
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(overlay, (cx - tw//2 - 4, cy - th - 4), (cx + tw//2 + 4, cy + 4),
                      (0, 0, 0), -1)
        cv2.putText(overlay, label, (cx - tw//2, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    # Draw borders again on top (crisp)
    for zone_name, zone_def in zones.items():
        poly_norm = zone_def["polygon"]
        pts = np.array([[int(x * w), int(y * h)] for x, y in poly_norm], dtype=np.int32)
        color = ZONE_COLORS.get(zone_name, DEFAULT_ZONE_COLOR)
        cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2, lineType=cv2.LINE_AA)


def draw_entry_line(frame: np.ndarray, cam_data: dict):
    line_y = cam_data.get("entry_line_y_ratio")
    if line_y is None:
        return
    h, w = frame.shape[:2]
    y = int(line_y * h)
    cv2.line(frame, (0, y), (w, y), (0, 255, 200), 2, cv2.LINE_AA)
    cv2.putText(frame, "ENTRY LINE", (10, y - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 200), 1, cv2.LINE_AA)


# ── HUD overlay ──────────────────────────────────────────────────────────────

def draw_hud(frame: np.ndarray, cam_id: str, store_id: str, frame_no: int,
             fps: float, n_people: int, cam_type: str):
    h, w = frame.shape[:2]

    # Top banner
    cv2.rectangle(frame, (0, 0), (w, 44), (0, 0, 0), -1)
    cv2.rectangle(frame, (0, 44), (w, 45), (60, 60, 60), -1)

    # Camera ID + type
    cv2.putText(frame, f"  {cam_id}  [{cam_type.upper()}]",
                (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220, 220, 220), 1, cv2.LINE_AA)

    # Store
    cv2.putText(frame, store_id, (8, 44 + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (140, 140, 140), 1, cv2.LINE_AA)

    # FPS right-aligned
    fps_str = f"{fps:.1f} FPS"
    (tw, _), _ = cv2.getTextSize(fps_str, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(frame, fps_str, (w - tw - 10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 220, 100), 1, cv2.LINE_AA)

    # Frame counter
    fc_str = f"F#{frame_no}"
    (tw2, _), _ = cv2.getTextSize(fc_str, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
    cv2.putText(frame, fc_str, (w - tw2 - 10, 44),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 140, 80), 1, cv2.LINE_AA)

    # Detection count badge (bottom-left)
    badge_txt = f"  YOLO: {n_people} person{'s' if n_people != 1 else ''}  "
    badge_color = (0, 200, 80) if n_people == 0 else (0, 180, 255)
    (btw, bth), _ = cv2.getTextSize(badge_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.rectangle(frame, (0, h - bth - 16), (btw + 8, h), (20, 20, 20), -1)
    cv2.putText(frame, badge_txt, (4, h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, badge_color, 1, cv2.LINE_AA)

    # "● LIVE" badge (bottom-right)
    live_txt = " ● YOLO v8n "
    (ltw, _), _ = cv2.getTextSize(live_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
    cv2.rectangle(frame, (w - ltw - 8, h - 28), (w, h), (40, 0, 0), -1)
    cv2.putText(frame, live_txt, (w - ltw - 4, h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (80, 80, 255), 1, cv2.LINE_AA)


# ── Detection box drawing ─────────────────────────────────────────────────────

def draw_detections(frame: np.ndarray, detections: sv.Detections):
    if len(detections) == 0:
        return

    for i in range(len(detections)):
        x1, y1, x2, y2 = map(int, detections.xyxy[i])
        track_id = int(detections.tracker_id[i]) if detections.tracker_id is not None else i
        conf = float(detections.confidence[i]) if detections.confidence is not None else 1.0
        color = track_color(track_id)

        # Bounding box
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

        # Label background + text
        label = f"ID:{track_id}  {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
        top = max(y1 - th - 8, 48)
        cv2.rectangle(frame, (x1, top), (x1 + tw + 8, top + th + 8), color, -1)
        cv2.putText(frame, label, (x1 + 4, top + th + 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA)

        # Foot-point dot
        foot_x, foot_y = (x1 + x2) // 2, y2
        cv2.circle(frame, (foot_x, foot_y), 5, color, -1, cv2.LINE_AA)


# ── Frame generator ───────────────────────────────────────────────────────────

class DetectionStreamer:
    def __init__(self, cam_id: str, speed: float = 1.0):
        self.cam_id = cam_id
        self.speed  = speed
        self._lock  = threading.Lock()
        self._frame: Optional[bytes] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.stats = {"cam_id": cam_id, "people": 0, "frame": 0, "fps": 0.0}

        layout = load_layout()
        store_id, cam_data = get_cam_info(layout, cam_id)
        if cam_data is None:
            raise ValueError(f"Camera '{cam_id}' not found in layout")

        self._cam_data = cam_data
        self._store_id = store_id

        clip = str(Path(CLIPS_DIR) / cam_data["clip_file"])
        if not Path(clip).exists():
            raise FileNotFoundError(f"Clip not found: {clip}")
        self._clip = clip

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_frame(self) -> Optional[bytes]:
        with self._lock:
            return self._frame

    def _run(self):
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        log.info(f"Loading YOLOv8 model ({MODEL_PATH}) on device='{device}' for {self.cam_id}…")
        model = YOLO(MODEL_PATH)
        model.to(device)
        tracker = sv.ByteTrack()
        cam_data = self._cam_data
        cam_type  = cam_data.get("type", "unknown")

        while self._running:
            cap = cv2.VideoCapture(self._clip)
            fps_src = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_no = 0

            t_fps = time.time()
            fps_display = 0.0

            log.info(f"Streaming {self.cam_id} ({self._clip}) at {self.speed}x speed")

            while self._running:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_no += 1
                if frame_no % FRAME_STRIDE != 0:
                    continue

                # Resize frame to target width of 800px to optimize drawing, inference, and compression performance
                h, w = frame.shape[:2]
                target_w = 800
                if w > target_w:
                    scale = target_w / w
                    target_h = int(h * scale)
                    frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

                t0 = time.perf_counter()

                # YOLO inference
                results = model(frame, conf=CONF_THRESH, iou=IOU_THRESH,
                                classes=[PERSON_CLASS], verbose=False, device=device)[0]

                detections = sv.Detections.from_ultralytics(results)
                detections = tracker.update_with_detections(detections)

                n_people = len(detections)

                # Draw overlays
                draw_zones(frame, cam_data)
                draw_entry_line(frame, cam_data)
                draw_detections(frame, detections)

                # Update FPS counter
                elapsed = time.time() - t_fps
                if elapsed > 1.0:
                    fps_display = FRAME_STRIDE / elapsed
                    t_fps = time.time()

                draw_hud(frame, self.cam_id, self._store_id or "", frame_no,
                         fps_display, n_people, cam_type)

                # Encode to JPEG
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
                with self._lock:
                    self._frame = buf.tobytes()
                    self.stats = {
                        "cam_id":  self.cam_id,
                        "people":  n_people,
                        "frame":   frame_no,
                        "fps":     round(fps_display, 1),
                    }

                # Throttle to approximate real-time / speed multiplier
                proc_ms = (time.perf_counter() - t0) * 1000
                target_ms = (1000.0 / fps_src * FRAME_STRIDE) / self.speed
                wait_ms = max(0, target_ms - proc_ms)
                time.sleep(wait_ms / 1000.0)

            cap.release()
            log.info(f"{self.cam_id}: clip ended, looping…")

        log.info(f"{self.cam_id}: streamer stopped")


# ── Flask MJPEG server ────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

_streamer: Optional[DetectionStreamer] = None


def _mjpeg_generator():
    global _streamer
    while True:
        if _streamer is None:
            time.sleep(0.1)
            continue
        frame = _streamer.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )
        time.sleep(0.033)   # ~30fps cap on the HTTP side


@app.route("/stream")
def stream():
    return Response(
        _mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                 "Access-Control-Allow-Origin": "*"},
    )


@app.route("/stats")
def stats():
    global _streamer
    if _streamer is None:
        return jsonify({"error": "not running"})
    return jsonify(_streamer.stats)


@app.route("/cameras")
def cameras():
    try:
        layout = load_layout()
        return jsonify({"cameras": all_cameras(layout)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/switch/<cam_id>", methods=["POST"])
def switch_camera(cam_id: str):
    global _streamer
    try:
        if _streamer:
            _streamer.stop()
        _streamer = DetectionStreamer(cam_id, speed=_current_speed)
        _streamer.start()
        return jsonify({"ok": True, "cam_id": cam_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/speed/<val>", methods=["POST"])
def set_speed(val: str):
    global _current_speed, _streamer
    try:
        val_float = float(val)
        _current_speed = val_float
        if _streamer:
            _streamer.speed = val_float
        return jsonify({"ok": True, "speed": val_float})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


_current_speed = 1.0


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APEX YOLO Detection MJPEG Stream Server")
    parser.add_argument("--cam",   default="CAM_ENTRY_01", help="Camera ID to stream")
    parser.add_argument("--speed", type=float, default=1.0,  help="Playback speed multiplier")
    parser.add_argument("--port",  type=int,   default=8001, help="HTTP port")
    args = parser.parse_args()

    _current_speed = args.speed

    log.info(f"Starting detection stream server on port {args.port}")
    log.info(f"Camera: {args.cam}  Speed: {args.speed}x")

    _streamer = DetectionStreamer(args.cam, speed=args.speed)
    _streamer.start()

    # Give YOLO a moment to load
    log.info(f"Stream available at: http://localhost:{args.port}/stream")
    log.info(f"Stats at:            http://localhost:{args.port}/stats")
    log.info(f"Switch camera: POST  http://localhost:{args.port}/switch/{{cam_id}}")

    app.run(host="0.0.0.0", port=args.port, threaded=True)
