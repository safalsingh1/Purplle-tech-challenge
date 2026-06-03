# PROMPT: Generate comprehensive mock unit tests for pipeline/detect.py including build_clip_config, CameraProcessor entry camera crossing, floor/billing camera zone events, billing queue depth events, track lost events, process frame loop, and run_pipeline orchestration.
# CHANGES MADE: Integrated with pytest, used unittest.mock to mock cv2.VideoCapture, supervision, and YOLO. Verified emissions and state changes directly.

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np

# Add pipeline dir to path
sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

from detect import CameraProcessor, build_clip_config, run_pipeline
from emit import StoreEvent, EventMetadata, EventEmitter
from tracker import ReIDTracker

# Sample layout config for test
MOCK_LAYOUT = {
    "stores": {
        "STORE_BLR_002": {
            "name": "Apex Retail Bengaluru Central",
            "city": "Bengaluru",
            "open_hours": { "start": "10:00", "end": "21:00" },
            "cameras": {
                "CAM_ENTRY_01": {
                    "clip_file": "CAM 3.mp4",
                    "type": "entry_exit",
                    "description": "Main entry/exit threshold camera",
                    "entry_line_y_ratio": 0.55,
                    "zones": {
                        "ENTRY_THRESHOLD": {
                            "polygon": [[0.0, 0.45], [1.0, 0.45], [1.0, 0.65], [0.0, 0.65]],
                            "sku_zone": None,
                            "is_entry_zone": True
                        }
                    }
                },
                "CAM_FLOOR_01": {
                    "clip_file": "CAM 2.mp4",
                    "type": "main_floor",
                    "description": "Main floor zone coverage camera",
                    "zones": {
                        "SKINCARE": {
                            "polygon": [[0.0, 0.0], [0.45, 0.0], [0.45, 0.55], [0.0, 0.55]],
                            "sku_zone": "MOISTURISER"
                        }
                    }
                },
                "CAM_BILLING_01": {
                    "clip_file": "CAM 1.mp4",
                    "type": "billing",
                    "description": "Billing counter area camera",
                    "zones": {
                        "BILLING_QUEUE": {
                            "polygon": [[0.1, 0.45], [0.9, 0.45], [0.9, 1.0], [0.1, 1.0]],
                            "sku_zone": None,
                            "is_billing_queue": True
                        }
                    }
                }
            }
        }
    }
}


def test_build_clip_config(tmp_path):
    # Create mock video clip
    clip_dir = tmp_path / "CCTV Footage"
    clip_dir.mkdir()
    (clip_dir / "CAM 3.mp4").write_text("dummy") # exists
    (clip_dir / "CAM 2.mp4").write_text("dummy") # exists
    # CAM 1.mp4 does not exist, so it will be skipped
    
    with patch("detect.load_layout", return_value=MOCK_LAYOUT):
        configs = build_clip_config("dummy_layout.json", str(clip_dir))
        assert len(configs) == 2
        assert configs[0]["store_id"] == "STORE_BLR_002"
        assert configs[0]["camera_id"] == "CAM_ENTRY_01"


def test_camera_processor_entry_crossing():
    config = {
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "clip_start": "2026-03-03T14:00:00Z",
        "layout": MOCK_LAYOUT,
        "cam_data": MOCK_LAYOUT["stores"]["STORE_BLR_002"]["cameras"]["CAM_ENTRY_01"],
    }
    emitter = MagicMock()
    reid = ReIDTracker("STORE_BLR_002")
    
    processor = CameraProcessor(config, emitter, reid)
    
    # 1. Cross downward (inbound) -> ENTRY
    processor._track_centroids[1] = [(0.5, 0.40), (0.5, 0.40)]
    session, is_new, is_reentry = reid.get_or_create_session(
        track_id=1,
        camera_id="CAM_ENTRY_01",
        frame_idx=10,
        timestamp_s=1.0,
        appearance_hash="abc",
    )
    
    events = processor._handle_entry_camera(
        track_id=1,
        cx=0.5,
        cy=0.60,
        timestamp="2026-03-03T14:00:01Z",
        frame_idx=30,
        fps=30.0,
        session=session,
        is_new=is_new,
        is_reentry=is_reentry,
        is_staff=False,
        conf=0.95
    )
    
    assert events == 1
    emitter.emit.assert_called_once()
    emitted_event = emitter.emit.call_args[0][0]
    assert emitted_event.event_type == "ENTRY"
    assert emitted_event.visitor_id == session.visitor_id
    
    # 2. Cross upward (outbound) -> EXIT
    emitter.reset_mock()
    processor._track_centroids[1] = [(0.5, 0.60), (0.5, 0.60)]
    events2 = processor._handle_entry_camera(
        track_id=1,
        cx=0.5,
        cy=0.40,
        timestamp="2026-03-03T14:00:02Z",
        frame_idx=60,
        fps=30.0,
        session=session,
        is_new=False,
        is_reentry=False,
        is_staff=False,
        conf=0.95
    )
    assert events2 == 1
    emitter.emit.assert_called_once()
    emitted_event2 = emitter.emit.call_args[0][0]
    assert emitted_event2.event_type == "EXIT"


def test_camera_processor_zone_events():
    config = {
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_FLOOR_01",
        "clip_start": "2026-03-03T14:00:00Z",
        "layout": MOCK_LAYOUT,
        "cam_data": MOCK_LAYOUT["stores"]["STORE_BLR_002"]["cameras"]["CAM_FLOOR_01"],
    }
    emitter = MagicMock()
    reid = ReIDTracker("STORE_BLR_002")
    processor = CameraProcessor(config, emitter, reid)
    
    # Mock staff detector
    processor.staff_detector = MagicMock()
    processor.staff_detector.is_staff.return_value = False
    
    session, _, _ = reid.get_or_create_session(
        track_id=2, camera_id="CAM_FLOOR_01", frame_idx=0, timestamp_s=0.0, appearance_hash="xyz"
    )
    
    # 1. ZONE_ENTER
    events = processor._handle_zone_camera(
        track_id=2, cx=0.2, cy=0.2,
        timestamp="2026-03-03T14:00:00Z", frame_idx=0, fps=30.0,
        session=session, is_staff=False, conf=0.90
    )
    assert events == 1
    assert emitter.emit.call_count == 1
    assert emitter.emit.call_args[0][0].event_type == "ZONE_ENTER"
    assert emitter.emit.call_args[0][0].zone_id == "SKINCARE"
    
    # 2. Same zone - no event
    emitter.reset_mock()
    events_same = processor._handle_zone_camera(
        track_id=2, cx=0.2, cy=0.2,
        timestamp="2026-03-03T14:00:05Z", frame_idx=150, fps=30.0,
        session=session, is_staff=False, conf=0.90
    )
    assert events_same == 0
    
    # 3. ZONE_DWELL
    events_dwell = processor._handle_zone_camera(
        track_id=2, cx=0.2, cy=0.2,
        timestamp="2026-03-03T14:00:35Z", frame_idx=1050, fps=30.0,
        session=session, is_staff=False, conf=0.90
    )
    assert events_dwell == 1
    assert emitter.emit.call_args[0][0].event_type == "ZONE_DWELL"
    assert emitter.emit.call_args[0][0].dwell_ms == 35000
    
    # 4. ZONE_EXIT
    emitter.reset_mock()
    events_exit = processor._handle_zone_camera(
        track_id=2, cx=0.8, cy=0.8,
        timestamp="2026-03-03T14:00:40Z", frame_idx=1200, fps=30.0,
        session=session, is_staff=False, conf=0.90
    )
    assert events_exit == 1
    assert emitter.emit.call_args[0][0].event_type == "ZONE_EXIT"
    assert emitter.emit.call_args[0][0].dwell_ms == 40000


def test_camera_processor_billing_queue():
    config = {
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_BILLING_01",
        "clip_start": "2026-03-03T14:00:00Z",
        "layout": MOCK_LAYOUT,
        "cam_data": MOCK_LAYOUT["stores"]["STORE_BLR_002"]["cameras"]["CAM_BILLING_01"],
    }
    emitter = MagicMock()
    reid = ReIDTracker("STORE_BLR_002")
    processor = CameraProcessor(config, emitter, reid)
    processor.staff_detector = MagicMock()
    processor.staff_detector.is_staff.return_value = False
    
    # 1. Visitor 1 joins -> ZONE_ENTER
    s1, _, _ = reid.get_or_create_session(1, "CAM_BILLING_01", 0, 0.0, "a")
    ev1 = processor._handle_zone_camera(1, 0.5, 0.6, "2026-03-03T14:00:00Z", 0, 30.0, s1, False, 0.9)
    assert ev1 == 1
    assert emitter.emit.call_args[0][0].event_type == "ZONE_ENTER"
    
    # 2. Visitor 2 joins -> ZONE_ENTER
    s2, _, _ = reid.get_or_create_session(2, "CAM_BILLING_01", 0, 0.0, "b")
    ev2 = processor._handle_zone_camera(2, 0.5, 0.6, "2026-03-03T14:00:00Z", 0, 30.0, s2, False, 0.9)
    assert ev2 == 1
    
    # 3. Visitor 3 joins -> exceeds threshold (2) -> BILLING_QUEUE_JOIN
    s3, _, _ = reid.get_or_create_session(3, "CAM_BILLING_01", 0, 0.0, "c")
    ev3 = processor._handle_zone_camera(3, 0.5, 0.6, "2026-03-03T14:00:00Z", 0, 30.0, s3, False, 0.9)
    assert ev3 == 1
    assert emitter.emit.call_args[0][0].event_type == "BILLING_QUEUE_JOIN"
    assert emitter.emit.call_args[0][0].metadata.queue_depth == 3
    
    # 4. Visitor 3 leaves queue -> BILLING_QUEUE_ABANDON
    emitter.reset_mock()
    ev_abandon = processor._handle_zone_camera(3, 0.95, 0.95, "2026-03-03T14:00:10Z", 300, 30.0, s3, False, 0.9)
    assert ev_abandon == 2
    emitted = [args[0][0].event_type for args in emitter.emit.call_args_list]
    assert "ZONE_EXIT" in emitted
    assert "BILLING_QUEUE_ABANDON" in emitted


def test_handle_track_lost():
    config = {
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_BILLING_01",
        "clip_start": "2026-03-03T14:00:00Z",
        "layout": MOCK_LAYOUT,
        "cam_data": MOCK_LAYOUT["stores"]["STORE_BLR_002"]["cameras"]["CAM_BILLING_01"],
    }
    emitter = MagicMock()
    reid = ReIDTracker("STORE_BLR_002")
    processor = CameraProcessor(config, emitter, reid)
    
    processor._track_zone_enter_frame[5] = ("BILLING_QUEUE", 10)
    processor._billing_zone_tracks.add(5)
    
    events = processor._handle_track_lost(5, "2026-03-03T14:00:05Z", 150)
    assert events == 0
    assert 5 not in processor._billing_zone_tracks
    assert 5 not in processor._track_zone_enter_frame


def test_camera_processor_process():
    config = {
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "clip_start": "2026-03-03T14:00:00Z",
        "layout": MOCK_LAYOUT,
        "clip_path": "dummy_clip.mp4",
        "cam_data": MOCK_LAYOUT["stores"]["STORE_BLR_002"]["cameras"]["CAM_ENTRY_01"],
    }
    emitter = MagicMock()
    reid = ReIDTracker("STORE_BLR_002")
    processor = CameraProcessor(config, emitter, reid)

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 3
    mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mock_cap.read.side_effect = [
        (True, mock_frame),
        (True, mock_frame),
        (False, None)
    ]
    
    mock_model = MagicMock()
    mock_result = MagicMock()
    mock_model.return_value = [mock_result]
    
    mock_detections = MagicMock()
    mock_detections.__len__.return_value = 1
    
    mock_tracks = MagicMock()
    mock_tracks.tracker_id = [1]
    mock_tracks.xyxy = [[100, 100, 200, 200]]
    mock_tracks.confidence = [0.95]
    mock_tracks.__len__.return_value = 1
    
    with patch("cv2.VideoCapture", return_value=mock_cap), \
         patch("supervision.Detections.from_ultralytics", return_value=mock_detections), \
         patch("supervision.ByteTrack.update_with_detections", return_value=mock_tracks):
             
        n = processor.process(mock_model, 30.0)
        assert n >= 0
        assert mock_cap.release.called


def test_run_pipeline(tmp_path):
    clip_dir = tmp_path / "CCTV Footage"
    clip_dir.mkdir()
    (clip_dir / "CAM 3.mp4").write_text("dummy")
    
    mock_cap = MagicMock()
    mock_cap.get.return_value = 30.0
    
    mock_processor = MagicMock()
    mock_processor.process.return_value = 5
    
    with patch("detect.load_layout", return_value=MOCK_LAYOUT), \
         patch("cv2.VideoCapture", return_value=mock_cap), \
         patch("detect.CameraProcessor", return_value=mock_processor), \
         patch("detect.YOLO") as mock_yolo_class:
             
        mock_yolo_instance = MagicMock()
        mock_yolo_class.return_value = mock_yolo_instance
        
        n_events = run_pipeline(str(clip_dir), "dummy_layout.json", str(tmp_path / "out.jsonl"))
        assert n_events == 5
