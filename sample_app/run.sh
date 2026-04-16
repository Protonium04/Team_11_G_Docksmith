#!/bin/bash
# run.sh — Build and run the sample app
# Run this from the project root: bash sample_app/run.sh

set -e
cd "$(dirname "$0")/.."

echo "=== Building sample_app ==="
python3 -m docksmith build -t sampleapp:latest sample_app

echo ""
echo "=== Running sample_app ==="
python3 -m docksmith run sampleapp:latest

echo ""
echo "=== Running with env override ==="
python3 -m docksmith run -e GREETING=Namaste sampleapp:latest
