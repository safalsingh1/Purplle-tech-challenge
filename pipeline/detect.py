"""
detect.py — Main CCTV detection and event generation pipeline.

Architecture:
  1. Load YOLOv8m on GPU (CUDA) for person detection.
  2. ByteTrack (via supervision) for multi-object tracking.
  3. Per-frame: classify zones, detect staff, check entry/exit.
  4. Emit structured events to events.jsonl.

Processing optimisation:
  - Stride: process every Nth frame (default N=2, ~15fps effective at 30fps source)
  - Batch size: 1 (memory-efficient for 6GB VRAM at 1080p)
  - YOLOv8m chosen for best accuracy/speed on 6GB GPU

Edge cases handled:
  - Group entry: each tracked bbox = 1 person → N separate ENTRY events
  - Partial occlusion: low-confidence detections kept (confidence > 0.20) and
    flagged with confidence score; NOT silently dropped
  - Re-entry: ReIDTracker detects returning visitors via appearance hash
  - Staff: StaffDetector classifies using duration + colour heuristics
  - Empty periods: no events emitted (pipeline handles zero-traffic correctly)
  - Cross-camera overlap: ReIDTracker deduplicates via appearance matching
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO
import supervision as sv

# Add pipeline dir to path
sys.path.insert(0, str(Path(__file__).parent))

from emit import EventEmitter, StoreEvent, EventMetadata, frame_to_timestamp, make_visitor_id
from zone_classifier import ZoneClassifier, load_layout
from staff_detector import StaffDetector
from tracker import ReIDTracker, compute_appearance_hash

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
log = logging.getLogger("detect")


# ── Constants ────────────────────────────────────────────────────────────────

YOLO_MODEL = "yolov8m.pt"
YOLO_CONF_THRESHOLD = 0.20     # keep low — flag uncertain detections, don't drop them
YOLO_IOU_THRESHOLD = 0.45
PERSON_CLASS_ID = 0            # COCO class 0 = person
FRAME_STRIDE = 2               # process every 2nd frame
DWELL_EMIT_INTERVAL_S = 30     # emit ZONE_DWELL every 30s of continuous dwell
ENTRY_LINE_CROSSING_FRAMES = 3 # number of frames to confirm line crossing
BILLING_QUEUE_THRESHOLD = 2    # queue depth to trigger BILLING_QUEUE_JOIN
CLIP_START_BASE = "2026-03-03T14:00:00Z"  # base timestamp for clip 1


# ── Clip configuration ───────────────────────────────────────────────────────

def build_clip_config(layout_path: str, clips_dir: str) -> list[dict]:
    """Build processing config for each clip from store_layout.json."""
    layout = load_layout(layout_path)
    configs = []
    base_dt = datetime.fromisoformat(CLIP_START_BASE.replace("Z", "+00:00"))

    for store_id, store_data in layout["stores"].items():
        for camera_id, cam_data in store_data["cameras"].items():
            clip_file = cam_data["clip_file"]
            clip_path = os.path.join(clips_dir, clip_file)
            if not os.path.exists(clip_path):
                log.warning(f"Clip not found: {clip_path}")
                continue

            # All cameras share the same wall-clock start — they record simultaneously.
            # Staggering timestamps is incorrect for a real store where all cameras
            # see the same moment in time.
            clip_start = base_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            configs.append({
                "clip_path": clip_path,
                "store_id": store_id,
                "camera_id": camera_id,
                "cam_data": cam_data,
                "clip_start": clip_start,
                "layout": layout,
            })

    return configs


# ── Processing state per camera ──────────────────────────────────────────────

class CameraProcessor:
    """Stateful processor for a single camera clip."""

    def __init__(self, config: dict, emitter: EventEmitter, reid_tracker: ReIDTracker):
        self.config = config
        self.emitter = emitter
        self.reid = reid_tracker
        self.store_id = config["store_id"]
        self.camera_id = config["camera_id"]
        self.clip_start = config["clip_start"]

        self.zone_clf = ZoneClassifier(
            config["layout"], config["store_id"], config["camera_id"]
        )

        # Per-track state
        self._track_centroids: dict[int, list[tuple[float, float]]] = {}  # for direction
        self._track_zone_enter_frame: dict[int, tuple[str, int]] = {}      # zone_id, frame
        self._track_last_dwell_emit_frame: dict[int, int] = {}
        self._track_has_entered: set[int] = set()   # crossed entry line inbound
        self._track_has_exited: set[int] = set()    # crossed entry line outbound
        self._billing_zone_tracks: set[int] = set() # currently in billing queue

        self.staff_detector: Optional[StaffDetector] = None  # set after knowing total frames

    def process(self, model: YOLO, fps: float) -> int:
        """Process the full clip. Returns number of events emitted."""
        clip_path = self.config["clip_path"]
        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            log.error(f"Cannot open clip: {clip_path}")
            return 0

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        log.info(f"Processing {self.camera_id} ({clip_path}): {total_frames} frames @ {fps:.1f}fps")

        self.staff_detector = StaffDetector(total_frames)

        # Configure ByteTrack (suppress deprecation warning — we handle the API change)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            byte_tracker = sv.ByteTrack(
                track_activation_threshold=0.25,
                lost_track_buffer=50,
                minimum_matching_threshold=0.8,
                frame_rate=int(fps),
            )

        frame_idx = 0
        events_emitted = 0
        active_tracks_last_frame: set[int] = set()

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Skip frames per stride
            if frame_idx % FRAME_STRIDE != 0:
                frame_idx += 1
                continue

            timestamp = frame_to_timestamp(self.clip_start, frame_idx, fps)
            timestamp_s = frame_idx / fps

            # YOLOv8 inference (GPU)
            results = model(
                frame,
                classes=[PERSON_CLASS_ID],
                conf=YOLO_CONF_THRESHOLD,
                iou=YOLO_IOU_THRESHOLD,
                verbose=False,
            )

            # Convert to supervision detections
            detections = sv.Detections.from_ultralytics(results[0])
            if len(detections) == 0:
                frame_idx += 1
                active_tracks_last_frame = set()
                continue

            # Apply ByteTrack
            tracks = byte_tracker.update_with_detections(detections)

            h, w = frame.shape[:2]
            active_this_frame: set[int] = set()

            for i in range(len(tracks)):
                track_id = int(tracks.tracker_id[i])
                bbox = tracks.xyxy[i]  # [x1, y1, x2, y2]
                conf = float(tracks.confidence[i])

                active_this_frame.add(track_id)

                # Normalised centroid
                cx = ((bbox[0] + bbox[2]) / 2) / w
                cy = ((bbox[1] + bbox[3]) / 2) / h

                # Update staff detector
                self.staff_detector.update(track_id, frame_idx, frame, bbox)

                # Appearance hash for Re-ID
                app_hash = compute_appearance_hash(frame, bbox)

                # Get or create session
                session, is_new, is_reentry = self.reid.get_or_create_session(
                    track_id=track_id,
                    camera_id=self.camera_id,
                    frame_idx=frame_idx,
                    timestamp_s=timestamp_s,
                    appearance_hash=app_hash,
                )

                is_staff = self.staff_detector.is_staff(track_id)
                staff_conf = self.staff_detector.get_confidence(track_id) if is_staff else conf

                # ── Entry camera logic ────────────────────────────────────
                if self.zone_clf.is_entry_camera():
                    events_emitted += self._handle_entry_camera(
                        track_id, cx, cy, timestamp, frame_idx, fps,
                        session, is_new, is_reentry, is_staff, conf
                    )

                # ── Floor / Billing camera logic ──────────────────────────
                else:
                    events_emitted += self._handle_zone_camera(
                        track_id, cx, cy, timestamp, frame_idx, fps,
                        session, is_staff, conf
                    )

                # Track centroid history
                if track_id not in self._track_centroids:
                    self._track_centroids[track_id] = []
                self._track_centroids[track_id].append((cx, cy))

            # Detect vanished tracks → possible exits
            vanished = active_tracks_last_frame - active_this_frame
            for vanished_id in vanished:
                events_emitted += self._handle_track_lost(
                    vanished_id, timestamp, frame_idx
                )

            active_tracks_last_frame = active_this_frame
            frame_idx += 1

        # Finalize staff detection model
        self.staff_detector.finalize()

        # Flush any remaining zone dwells for tracks still visible at end
        for track_id in list(self._track_zone_enter_frame.keys()):
            zone_id, enter_frame = self._track_zone_enter_frame[track_id]
            dwell_s = (frame_idx - enter_frame) / fps
            if dwell_s >= DWELL_EMIT_INTERVAL_S:
                session = self.reid.get_session(track_id, self.camera_id)
                if session:
                    self._emit_zone_dwell(session, zone_id, enter_frame, frame_idx, fps)
                    events_emitted += 1

        cap.release()
        log.info(f"  → {events_emitted} events from {self.camera_id}")
        return events_emitted

    def _handle_entry_camera(
        self, track_id, cx, cy, timestamp, frame_idx, fps,
        session, is_new, is_reentry, is_staff, conf
    ) -> int:
        """Handle entry/exit line crossing detection."""
        events = 0
        entry_line_y = self.config["cam_data"].get("entry_line_y_ratio", 0.55)

        centroids = self._track_centroids.get(track_id, [])
        if len(centroids) < 2:
            return 0

        prev_cy = centroids[-1][1] if centroids else cy

        # Direction: moving from top (outside) to bottom (inside) = ENTRY
        #            moving from bottom (inside) to top (outside) = EXIT
        if prev_cy < entry_line_y <= cy:
            # Crossed downward — entering store
            if track_id not in self._track_has_entered:
                self._track_has_entered.add(track_id)
                event_type = "REENTRY" if is_reentry else "ENTRY"
                seq = self.reid.increment_seq(track_id, self.camera_id)
                self._emit(StoreEvent(
                    store_id=self.store_id,
                    camera_id=self.camera_id,
                    visitor_id=session.visitor_id,
                    event_type=event_type,
                    timestamp=timestamp,
                    zone_id=None,
                    dwell_ms=0,
                    is_staff=is_staff,
                    confidence=round(conf, 3),
                    metadata=EventMetadata(session_seq=seq),
                ))
                events += 1

        elif prev_cy >= entry_line_y > cy:
            # Crossed upward — exiting store
            if track_id not in self._track_has_exited:
                self._track_has_exited.add(track_id)
                ts_s = frame_idx / fps
                self.reid.mark_exited(track_id, self.camera_id, ts_s)
                seq = self.reid.increment_seq(track_id, self.camera_id)
                self._emit(StoreEvent(
                    store_id=self.store_id,
                    camera_id=self.camera_id,
                    visitor_id=session.visitor_id,
                    event_type="EXIT",
                    timestamp=timestamp,
                    zone_id=None,
                    dwell_ms=0,
                    is_staff=is_staff,
                    confidence=round(conf, 3),
                    metadata=EventMetadata(session_seq=seq),
                ))
                events += 1

        return events

    def _handle_zone_camera(
        self, track_id, cx, cy, timestamp, frame_idx, fps,
        session, is_staff, conf
    ) -> int:
        """Handle zone enter/exit/dwell events for floor and billing cameras."""
        events = 0
        zone_info = self.zone_clf.classify(cx, cy)
        zone_id = zone_info.zone_id if zone_info else None

        prev_zone_data = self._track_zone_enter_frame.get(track_id)
        prev_zone_id = prev_zone_data[0] if prev_zone_data else None
        prev_enter_frame = prev_zone_data[1] if prev_zone_data else frame_idx

        # Zone change
        if zone_id != prev_zone_id:
            # Emit ZONE_EXIT for previous zone
            if prev_zone_id is not None:
                dwell_s = (frame_idx - prev_enter_frame) / fps
                dwell_ms = int(dwell_s * 1000)
                seq = self.reid.increment_seq(track_id, self.camera_id)
                self._emit(StoreEvent(
                    store_id=self.store_id,
                    camera_id=self.camera_id,
                    visitor_id=session.visitor_id,
                    event_type="ZONE_EXIT",
                    timestamp=timestamp,
                    zone_id=prev_zone_id,
                    dwell_ms=dwell_ms,
                    is_staff=is_staff,
                    confidence=round(conf, 3),
                    metadata=EventMetadata(session_seq=seq),
                ))
                events += 1

                # Check billing queue abandon (was in billing, no transaction followed)
                if prev_zone_id == "BILLING_QUEUE" and track_id in self._billing_zone_tracks:
                    self._billing_zone_tracks.discard(track_id)
                    # Check POS correlation later at API level — emit abandon candidate
                    seq = self.reid.increment_seq(track_id, self.camera_id)
                    self._emit(StoreEvent(
                        store_id=self.store_id,
                        camera_id=self.camera_id,
                        visitor_id=session.visitor_id,
                        event_type="BILLING_QUEUE_ABANDON",
                        timestamp=timestamp,
                        zone_id="BILLING_QUEUE",
                        dwell_ms=dwell_ms,
                        is_staff=is_staff,
                        confidence=round(conf, 3),
                        metadata=EventMetadata(
                            queue_depth=len(self._billing_zone_tracks),
                            session_seq=seq,
                        ),
                    ))
                    events += 1

            # Emit ZONE_ENTER for new zone
            if zone_id is not None:
                queue_depth = None
                if zone_id == "BILLING_QUEUE":
                    self._billing_zone_tracks.add(track_id)
                    queue_depth = len(self._billing_zone_tracks)

                seq = self.reid.increment_seq(track_id, self.camera_id)

                if zone_id == "BILLING_QUEUE" and queue_depth and queue_depth > BILLING_QUEUE_THRESHOLD:
                    event_type = "BILLING_QUEUE_JOIN"
                else:
                    event_type = "ZONE_ENTER"

                self._emit(StoreEvent(
                    store_id=self.store_id,
                    camera_id=self.camera_id,
                    visitor_id=session.visitor_id,
                    event_type=event_type,
                    timestamp=timestamp,
                    zone_id=zone_id,
                    dwell_ms=0,
                    is_staff=is_staff,
                    confidence=round(conf, 3),
                    metadata=EventMetadata(
                        queue_depth=queue_depth,
                        sku_zone=zone_info.sku_zone if zone_info else None,
                        session_seq=seq,
                    ),
                ))
                events += 1

                self._track_zone_enter_frame[track_id] = (zone_id, frame_idx)
                self._track_last_dwell_emit_frame[track_id] = frame_idx

        else:
            # Same zone — check for ZONE_DWELL emission every 30s
            if zone_id is not None:
                frames_since_dwell = frame_idx - self._track_last_dwell_emit_frame.get(track_id, frame_idx)
                dwell_since_enter = frame_idx - prev_enter_frame
                if (frames_since_dwell / fps >= DWELL_EMIT_INTERVAL_S and
                        dwell_since_enter / fps >= DWELL_EMIT_INTERVAL_S):
                    self._emit_zone_dwell(session, zone_id, prev_enter_frame, frame_idx, fps)
                    self._track_last_dwell_emit_frame[track_id] = frame_idx
                    events += 1

        return events

    def _emit_zone_dwell(self, session, zone_id, enter_frame, current_frame, fps):
        dwell_ms = int((current_frame - enter_frame) / fps * 1000)
        ts = frame_to_timestamp(self.clip_start, current_frame, fps)
        seq = self.reid.increment_seq(session.track_id, self.camera_id)
        is_staff = self.staff_detector.is_staff(session.track_id)
        self._emit(StoreEvent(
            store_id=self.store_id,
            camera_id=self.camera_id,
            visitor_id=session.visitor_id,
            event_type="ZONE_DWELL",
            timestamp=ts,
            zone_id=zone_id,
            dwell_ms=dwell_ms,
            is_staff=is_staff,
            confidence=0.90,
            metadata=EventMetadata(session_seq=seq),
        ))

    def _handle_track_lost(self, track_id: int, timestamp: str, frame_idx: int) -> int:
        """Handle a track that disappeared from the frame."""
        events = 0
        # Clean up billing zone state
        self._billing_zone_tracks.discard(track_id)
        # Clean up zone state
        if track_id in self._track_zone_enter_frame:
            del self._track_zone_enter_frame[track_id]
        return events

    def _emit(self, event: StoreEvent):
        self.emitter.emit(event)


# ── Main ─────────────────────────────────────────────────────────────────────

def run_pipeline(
    clips_dir: str,
    layout_path: str,
    output_path: str,
    api_url: Optional[str] = None,
    realtime: bool = False,
):
    """
    Process all configured clips and emit events to output_path.
    """
    # Auto-select compute device — falls back to CPU for Railway / CI environments
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"
    log.info(f"Loading YOLOv8m model on device='{device}'...")
    model = YOLO(YOLO_MODEL)
    model.to(device)

    configs = build_clip_config(layout_path, clips_dir)
    if not configs:
        log.error("No clips found. Check clips_dir and store_layout.json.")
        return

    log.info(f"Found {len(configs)} clip(s) to process.")

    # Group by store for shared ReID tracker
    store_reid: dict[str, ReIDTracker] = {}

    with EventEmitter(output_path, api_url=api_url) as emitter:
        total_events = 0

        for config in configs:
            store_id = config["store_id"]
            if store_id not in store_reid:
                store_reid[store_id] = ReIDTracker(store_id)

            # Get fps from clip
            cap = cv2.VideoCapture(config["clip_path"])
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            cap.release()

            processor = CameraProcessor(
                config=config,
                emitter=emitter,
                reid_tracker=store_reid[store_id],
            )
            n = processor.process(model, fps)
            total_events += n

    log.info(f"Pipeline complete. Total events emitted: {total_events}")
    log.info(f"Output: {output_path}")
    return total_events


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apex Retail CCTV Detection Pipeline")
    parser.add_argument("--clips-dir", default="../CCTV Footage", help="Directory containing CCTV clips")
    parser.add_argument("--layout", default="data/store_layout.json", help="Path to store_layout.json")
    parser.add_argument("--output", default="data/events.jsonl", help="Output JSONL file")
    parser.add_argument("--api-url", default=None, help="API URL to POST events in real-time")
    parser.add_argument("--realtime", action="store_true", help="Simulate real-time event emission")
    args = parser.parse_args()

    run_pipeline(
        clips_dir=args.clips_dir,
        layout_path=args.layout,
        output_path=args.output,
        api_url=args.api_url,
        realtime=args.realtime,
    )
