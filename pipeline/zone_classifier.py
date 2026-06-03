"""
zone_classifier.py — Maps bounding box coordinates to named store zones.

Uses polygon containment tests from store_layout.json definitions.
Zones are defined as normalized [0,1] polygon coordinates relative
to each camera frame size.
"""

import json
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class ZoneInfo:
    zone_id: str
    sku_zone: Optional[str]
    is_entry_zone: bool = False
    is_billing: bool = False
    is_billing_queue: bool = False


def _point_in_polygon(px: float, py: float, polygon: list[list[float]]) -> bool:
    """Ray-casting algorithm for point-in-polygon test."""
    n = len(polygon)
    inside = False
    x, y = px, py
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


class ZoneClassifier:
    """
    Classifies a normalised bounding-box centroid into a zone for a given camera.
    """

    def __init__(self, store_layout: dict, store_id: str, camera_id: str):
        self.zones: list[tuple[list[list[float]], ZoneInfo]] = []
        store = store_layout["stores"][store_id]
        cam = store["cameras"][camera_id]

        for zone_name, zone_def in cam.get("zones", {}).items():
            info = ZoneInfo(
                zone_id=zone_name,
                sku_zone=zone_def.get("sku_zone"),
                is_entry_zone=zone_def.get("is_entry_zone", False),
                is_billing=zone_def.get("is_billing", False),
                is_billing_queue=zone_def.get("is_billing_queue", False),
            )
            self.zones.append((zone_def["polygon"], info))

        # Entry line for direction detection (only for entry cameras)
        self.entry_line_y_ratio: Optional[float] = cam.get("entry_line_y_ratio")
        self.cam_type: str = cam.get("type", "unknown")

    def classify(self, cx_norm: float, cy_norm: float) -> Optional[ZoneInfo]:
        """Return the ZoneInfo for the normalised centroid (cx, cy), or None."""
        for polygon, info in self.zones:
            if _point_in_polygon(cx_norm, cy_norm, polygon):
                return info
        return None

    def is_entry_camera(self) -> bool:
        return self.cam_type == "entry_exit"

    def is_billing_camera(self) -> bool:
        return self.cam_type == "billing"


def load_layout(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
