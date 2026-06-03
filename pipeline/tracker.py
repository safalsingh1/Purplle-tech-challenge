"""
tracker.py — Re-ID and cross-camera visitor deduplication.

Tracks visitor sessions across:
  1. Same camera: ByteTrack handles continuous IDs natively.
  2. Cross-camera: time-window matching with appearance similarity.
  3. Re-entry: same visitor leaving and returning within session timeout.

Design rationale:
  - We avoid heavy OSNet/torchreid Re-ID models because our clips are short
    (<3 min) and the same camera tracks are already robust with ByteTrack.
  - Cross-camera re-ID uses (appearance_hash, time_window) matching:
    appearance_hash = top-K dominant HSV bins. This is lightweight and
    works well for retail CCTV where people wear distinct clothing.
  - Re-entry window: 10 minutes (600 seconds). Anyone who exits and
    re-enters within that window is flagged REENTRY, not counted as new.
"""

import time
import hashlib
import numpy as np
import cv2
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict


@dataclass
class VisitorSession:
    visitor_id: str
    store_id: str
    track_id: int
    camera_id: str
    first_seen_frame: int
    last_seen_frame: int
    last_seen_timestamp: float   # unix epoch float
    has_exited: bool = False
    exit_timestamp: Optional[float] = None
    appearance_hash: Optional[str] = None
    session_seq: int = 0          # running event count for this visitor
    current_zone: Optional[str] = None
    zone_enter_frame: Optional[int] = None


class ReIDTracker:
    """
    Manages visitor sessions across cameras with re-entry detection.
    """

    REENTRY_TIMEOUT_S = 600   # 10 minutes — same person re-entering counts as re-entry
    CROSS_CAM_WINDOW_S = 30   # cross-camera match must occur within this window (2-min clips)

    def __init__(self, store_id: str):
        self.store_id = store_id
        # track_id → VisitorSession (per camera)
        self._active: dict[tuple[str, int], VisitorSession] = {}
        # visitor_id → VisitorSession (historical, for re-entry detection)
        self._exited: dict[str, VisitorSession] = {}
        # appearance_hash → VisitorSession (for cross-camera matching)
        self._appearance_pool: dict[str, VisitorSession] = {}

    def get_or_create_session(
        self,
        track_id: int,
        camera_id: str,
        frame_idx: int,
        timestamp_s: float,
        appearance_hash: Optional[str] = None,
    ) -> tuple[VisitorSession, bool, bool]:
        """
        Returns (session, is_new_entry, is_reentry).
        """
        key = (camera_id, track_id)

        # Already tracking this track
        if key in self._active:
            session = self._active[key]
            session.last_seen_frame = frame_idx
            session.last_seen_timestamp = timestamp_s
            if appearance_hash and not session.appearance_hash:
                session.appearance_hash = appearance_hash
            return session, False, False

        # New track on this camera — check for cross-camera or re-entry match
        matched_session = self._find_match(appearance_hash, timestamp_s, camera_id)

        if matched_session and matched_session.has_exited:
            # Re-entry: same person came back
            matched_session.has_exited = False
            matched_session.exit_timestamp = None
            matched_session.camera_id = camera_id
            matched_session.track_id = track_id
            matched_session.last_seen_frame = frame_idx
            matched_session.last_seen_timestamp = timestamp_s
            self._active[key] = matched_session
            if matched_session.visitor_id in self._exited:
                del self._exited[matched_session.visitor_id]
            return matched_session, False, True  # is_reentry=True

        if matched_session and not matched_session.has_exited:
            # Cross-camera continuation: same person seen on different camera
            matched_session.camera_id = camera_id
            matched_session.track_id = track_id
            matched_session.last_seen_frame = frame_idx
            matched_session.last_seen_timestamp = timestamp_s
            self._active[key] = matched_session
            return matched_session, False, False

        # Brand new visitor
        from emit import make_visitor_id
        visitor_id = make_visitor_id(track_id, f"{self.store_id}_{camera_id}_{frame_idx}")
        session = VisitorSession(
            visitor_id=visitor_id,
            store_id=self.store_id,
            track_id=track_id,
            camera_id=camera_id,
            first_seen_frame=frame_idx,
            last_seen_frame=frame_idx,
            last_seen_timestamp=timestamp_s,
            appearance_hash=appearance_hash,
        )
        self._active[key] = session
        if appearance_hash:
            self._appearance_pool[appearance_hash] = session
        return session, True, False  # is_new_entry=True

    def mark_exited(self, track_id: int, camera_id: str, timestamp_s: float) -> Optional[VisitorSession]:
        """Mark a tracked person as having exited. Returns the session."""
        key = (camera_id, track_id)
        session = self._active.pop(key, None)
        if session:
            session.has_exited = True
            session.exit_timestamp = timestamp_s
            self._exited[session.visitor_id] = session
        return session

    def _find_match(
        self,
        appearance_hash: Optional[str],
        timestamp_s: float,
        camera_id: str,
    ) -> Optional[VisitorSession]:
        """Try to find an existing session matching this appearance + time window."""
        if not appearance_hash:
            return None

        # Direct hash match
        if appearance_hash in self._appearance_pool:
            candidate = self._appearance_pool[appearance_hash]
            time_diff = abs(timestamp_s - candidate.last_seen_timestamp)
            if time_diff <= self.CROSS_CAM_WINDOW_S:
                return candidate

        # Check exited sessions for re-entry
        for vid, session in list(self._exited.items()):
            if session.appearance_hash == appearance_hash:
                time_since_exit = timestamp_s - (session.exit_timestamp or 0)
                if 0 < time_since_exit <= self.REENTRY_TIMEOUT_S:
                    return session

        return None

    def get_session(self, track_id: int, camera_id: str) -> Optional[VisitorSession]:
        return self._active.get((camera_id, track_id))

    def increment_seq(self, track_id: int, camera_id: str) -> int:
        session = self.get_session(track_id, camera_id)
        if session:
            session.session_seq += 1
            return session.session_seq
        return 0


def compute_appearance_hash(frame: np.ndarray, bbox_xyxy: np.ndarray) -> str:
    """
    Compute a stable appearance hash from the person's torso region.

    Production improvements over the naive full-bbox hue-only hash:
      - Crops only the middle 20–80% of the bounding box height (torso region).
        This avoids head/hair colour (changes with lighting) and feet/floor noise.
      - Uses both Hue (8 bins) AND Saturation (4 bins) to distinguish between
        people in similar-hued but differently-saturated clothing (e.g. light blue
        vs dark navy — same hue bin, very different saturation).
      - Returns top-4 H bins + top-2 S bins as a compact string signature.

    This reduces false-positive cross-camera matches caused by clothing colour
    collisions in the original 4-hue-bin-only approach.
    """
    x1, y1, x2, y2 = map(int, bbox_xyxy)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
    if x2 <= x1 or y2 <= y1:
        return "unknown"

    # Crop torso: middle 20%–80% of bbox height (skip head and feet)
    h_bbox = y2 - y1
    torso_y1 = y1 + int(h_bbox * 0.20)
    torso_y2 = y1 + int(h_bbox * 0.80)
    roi = frame[torso_y1:torso_y2, x1:x2]
    if roi.size == 0:
        return "unknown"

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # 8-bin Hue histogram (dominant colour)
    h_hist = cv2.calcHist([hsv], [0], None, [8], [0, 180]).flatten()
    # 4-bin Saturation histogram (separates grey/neutral vs vivid colours)
    s_hist = cv2.calcHist([hsv], [1], None, [4], [0, 256]).flatten()

    top4_h = np.argsort(h_hist)[-4:][::-1]
    top2_s = np.argsort(s_hist)[-2:][::-1]
    signature = (
        "h" + "_".join(str(b) for b in sorted(top4_h))
        + "_s" + "_".join(str(b) for b in sorted(top2_s))
    )
    return signature
