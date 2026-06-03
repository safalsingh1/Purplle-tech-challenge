import asyncio
import os
import sys

# Add app to python path
sys.path.append(os.path.abspath("."))

from app.main import generate_mjpeg_stream

async def test_camera(cam_id):
    print(f"Testing stream for {cam_id}...")
    stream = generate_mjpeg_stream(cam_id)
    count = 0
    async for frame in stream:
        count += 1
        # frame is bytes in multipart format: b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n'
        print(f"  Received frame {count}, size={len(frame)}")
        if count >= 3:
            break

async def main():
    # Set video dir env var so it matches container environment or fallback
    os.environ["VIDEO_DIR"] = "../new resouces/all_clips"
    for cam in ["CAM_S2_ENTRY1", "CAM_S2_ENTRY2", "CAM_S2_ZONE", "CAM_S2_BILLING"]:
        try:
            await test_camera(cam)
        except Exception as e:
            print(f"  Failed for {cam}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
