#!/usr/bin/env bash
# run.sh
# One command to process all clips -> events
# Usage: ./run.sh [path/to/cctv_clips_directory]

set -e

CLIP_DIR="${1:-./data/clips}"

if [ ! -d "$CLIP_DIR" ]; then
  echo "Error: Directory '$CLIP_DIR' does not exist."
  echo "Usage: ./run.sh [path/to/cctv_clips_directory]"
  exit 1
fi

echo "=========================================="
echo "Starting Apex Retail CV Pipeline"
echo "Processing clips in: $CLIP_DIR"
echo "=========================================="

# Ensure dependencies are installed
pip install -r requirements.txt > /dev/null 2>&1 || true

# Run the pipeline
python run_pipeline.py --clips-dir "$CLIP_DIR"

echo "=========================================="
echo "Pipeline execution complete."
echo "Output saved to: data/events.jsonl"
echo "=========================================="
