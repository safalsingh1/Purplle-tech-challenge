"""
staff_detector.py — Identifies store staff from CCTV detections.

Strategy: Two complementary signals
  1. COLOUR HEURISTIC: Staff wear uniforms — consistent HSV hue in the
     torso region of the bounding box. We cluster observed dominant hues
     across all tracks and flag any track whose hue distribution closely
     matches the most common "static" hue cluster (staff stand in place
     more than customers).

  2. PRESENCE DURATION HEURISTIC: Any person whose track spans > 70% of
     the clip duration is almost certainly staff, not a customer.

We avoid training a separate classifier since we don't have labelled data.
"""

import numpy as np
import cv2
from collections import defaultdict
from typing import Optional


class StaffDetector:
    """
    Accumulates colour histograms per track_id and uses presence duration
    + dominant colour to classify staff vs customer.
    """

    # HSV ranges for common retail uniform colours
    # (staff often wear solid-colour polo shirts / vests)
    # We fall back to duration heuristic when colour is ambiguous.
    STAFF_HUE_RANGES = [
        (0, 15),    # red
        (165, 180), # red (wrap-around)
        (100, 130), # blue
        (35, 75),   # green / olive
        (0, 180),   # will be refined dynamically
    ]

    def __init__(self, clip_total_frames: int, staff_duration_ratio: float = 0.65):
        """
        clip_total_frames: total number of frames in the clip.
        staff_duration_ratio: tracks spanning > this fraction of total frames → staff.
        """
        self.clip_total_frames = clip_total_frames
        self.staff_duration_ratio = staff_duration_ratio

        # Per-track data
        self._track_first_frame: dict[int, int] = {}
        self._track_last_frame: dict[int, int] = {}
        self._track_hue_hist: dict[int, np.ndarray] = {}

        # Dynamically discovered staff hue (updated after first pass)
        self._staff_hue_cluster: Optional[tuple[int, int]] = None
        self._confirmed_staff: set[int] = set()

    def update(self, track_id: int, frame_idx: int, frame: np.ndarray, bbox_xyxy: np.ndarray) -> None:
        """Update tracker stats for this track at this frame."""
        x1, y1, x2, y2 = map(int, bbox_xyxy)

        # Record presence span
        if track_id not in self._track_first_frame:
            self._track_first_frame[track_id] = frame_idx
        self._track_last_frame[track_id] = frame_idx

        # Sample colour from torso region (top 25%–55% of bbox height)
        h = y2 - y1
        torso_y1 = y1 + int(h * 0.25)
        torso_y2 = y1 + int(h * 0.55)
        torso_y1 = max(0, torso_y1)
        torso_y2 = min(frame.shape[0], torso_y2)
        x1 = max(0, x1)
        x2 = min(frame.shape[1], x2)

        if torso_y2 <= torso_y1 or x2 <= x1:
            return

        roi = frame[torso_y1:torso_y2, x1:x2]
        if roi.size == 0:
            return

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0], None, [18], [0, 180])
        hist = hist.flatten()

        if track_id in self._track_hue_hist:
            self._track_hue_hist[track_id] += hist
        else:
            self._track_hue_hist[track_id] = hist

    def is_staff(self, track_id: int) -> bool:
        """Return True if the track is classified as staff."""
        if track_id in self._confirmed_staff:
            return True

        # Duration heuristic
        first = self._track_first_frame.get(track_id, 0)
        last = self._track_last_frame.get(track_id, 0)
        duration_ratio = (last - first + 1) / max(self.clip_total_frames, 1)
        if duration_ratio >= self.staff_duration_ratio:
            self._confirmed_staff.add(track_id)
            return True

        # Colour heuristic (only if we've identified a staff hue cluster)
        if self._staff_hue_cluster and track_id in self._track_hue_hist:
            hue_low, hue_high = self._staff_hue_cluster
            hist = self._track_hue_hist[track_id]
            bin_low = int(hue_low / 10)
            bin_high = int(hue_high / 10)
            cluster_mass = hist[bin_low:bin_high + 1].sum()
            total_mass = hist.sum()
            if total_mass > 0 and cluster_mass / total_mass > 0.55:
                self._confirmed_staff.add(track_id)
                return True

        return False

    def finalize(self) -> None:
        """
        After processing all frames: identify the dominant staff hue cluster
        by finding the most common hue among long-duration tracks.
        """
        long_tracks = [
            tid for tid, first in self._track_first_frame.items()
            if (self._track_last_frame.get(tid, 0) - first + 1) / max(self.clip_total_frames, 1) >= 0.3
        ]
        if not long_tracks:
            return

        # Aggregate hue histograms from long-duration tracks
        combined = np.zeros(18, dtype=np.float32)
        for tid in long_tracks:
            if tid in self._track_hue_hist:
                combined += self._track_hue_hist[tid]

        if combined.sum() == 0:
            return

        dominant_bin = int(np.argmax(combined))
        hue_center = dominant_bin * 10 + 5
        self._staff_hue_cluster = (max(0, hue_center - 15), min(180, hue_center + 15))

    def get_confidence(self, track_id: int) -> float:
        """Return confidence score that this track is correctly classified."""
        first = self._track_first_frame.get(track_id, 0)
        last = self._track_last_frame.get(track_id, 0)
        duration_ratio = (last - first + 1) / max(self.clip_total_frames, 1)

        if duration_ratio >= self.staff_duration_ratio:
            # High confidence from duration
            return min(0.97, 0.80 + duration_ratio * 0.2)

        # Medium confidence from colour
        if self._staff_hue_cluster and track_id in self._track_hue_hist:
            hist = self._track_hue_hist[track_id]
            total = hist.sum()
            if total > 0:
                hue_low, hue_high = self._staff_hue_cluster
                bin_low = int(hue_low / 10)
                bin_high = int(hue_high / 10)
                mass = hist[bin_low:bin_high + 1].sum()
                return float(min(0.92, 0.5 + mass / total))

        return 0.75  # base confidence
