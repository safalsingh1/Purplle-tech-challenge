"""
run_pipeline.py — Windows-friendly detection pipeline runner.

Usage (from store-intelligence directory):
  python run_pipeline.py
  python run_pipeline.py --api-url http://localhost:8000
  python run_pipeline.py --clips-dir "C:/path/to/CCTV Footage"
"""

import sys
import argparse
import os
from pathlib import Path

# Add pipeline to path
sys.path.insert(0, str(Path(__file__).parent / "pipeline"))

from detect import run_pipeline

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apex Retail Detection Pipeline Runner")
    parser.add_argument(
        "--clips-dir",
        default=str(Path(__file__).parent.parent / "CCTV Footage"),
        help="Directory containing CCTV clip files (default: ../CCTV Footage)"
    )
    parser.add_argument(
        "--layout",
        default="data/store_layout.json",
        help="Path to store_layout.json"
    )
    parser.add_argument(
        "--output",
        default="data/events.jsonl",
        help="Output JSONL file path"
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="API URL to POST events in real-time (e.g. http://localhost:8000)"
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Simulate real-time playback speed"
    )
    args = parser.parse_args()

    # Ensure output directory exists
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    print(f"Clips dir: {args.clips_dir}")
    print(f"Layout:    {args.layout}")
    print(f"Output:    {args.output}")
    if args.api_url:
        print(f"API URL:   {args.api_url}")

    n = run_pipeline(
        clips_dir=args.clips_dir,
        layout_path=args.layout,
        output_path=args.output,
        api_url=args.api_url,
        realtime=args.realtime,
    )
    print(f"\nDone. {n} events written to {args.output}")
