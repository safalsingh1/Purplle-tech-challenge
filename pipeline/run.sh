#!/usr/bin/env bash
# run.sh — One-command detection pipeline runner
#
# Usage (from store-intelligence/ directory):
#   bash pipeline/run.sh
#   bash pipeline/run.sh --api-url http://localhost:8000
#   CLIPS_DIR="/path/to/CCTV Footage" bash pipeline/run.sh
#
# Environment variables:
#   CLIPS_DIR   — path to CCTV clip directory (default: ../CCTV Footage)
#   API_URL     — if set, POSTs events to API in real-time
#   REALTIME    — if set to "1", simulates real-time playback pace

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLIPS_DIR="${CLIPS_DIR:-$SCRIPT_DIR/../CCTV Footage}"
LAYOUT="$SCRIPT_DIR/data/store_layout.json"
OUTPUT="$SCRIPT_DIR/data/events.jsonl"
API_URL="${API_URL:-}"
REALTIME="${REALTIME:-}"

echo "=== Apex Retail Detection Pipeline ==="
echo "Clips dir : $CLIPS_DIR"
echo "Layout    : $LAYOUT"
echo "Output    : $OUTPUT"
if [ -n "$API_URL" ]; then
  echo "API URL   : $API_URL (events will be POSTed live)"
fi

# Clear previous output
> "$OUTPUT"

cd "$SCRIPT_DIR/pipeline"

ARGS=(
  --clips-dir "$CLIPS_DIR"
  --layout    "$LAYOUT"
  --output    "$OUTPUT"
)
if [ -n "$API_URL" ]; then
  ARGS+=(--api-url "$API_URL")
fi
if [ -n "$REALTIME" ]; then
  ARGS+=(--realtime)
fi

python detect.py "${ARGS[@]}"

echo ""
echo "✓ Events written to: $OUTPUT"
echo "✓ Event count: $(wc -l < "$OUTPUT" | tr -d ' ')"
