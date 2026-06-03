import cv2
import os
import glob

clips_dir = "../new resouces/all_clips"
if not os.path.exists(clips_dir):
    clips_dir = "new resouces/all_clips"

print(f"Inspecting videos in: {clips_dir}")
for path in glob.glob(os.path.join(clips_dir, "*.mp4")):
    cap = cv2.VideoCapture(path)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0
        print(f"File: {os.path.basename(path)}")
        print(f"  Resolution: {w}x{h}")
        print(f"  FPS: {fps}")
        print(f"  Frame count: {frame_count}")
        print(f"  Duration: {duration:.2f}s ({duration/60:.2f}m)")
        cap.release()
    else:
        print(f"Could not open: {path}")
