#!/bin/bash
# Sauron startup wrapper — used by LaunchDaemon
cd /Users/stephen/Documents/Website/Sauron

# Load environment variables
set -a
source .env
set +a

# Ensure Homebrew binaries (ffmpeg, etc.) are in PATH
export PATH=/opt/homebrew/bin:$PATH

# Clear __pycache__ to prevent stale module issues
find sauron -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null

exec /Users/stephen/Documents/Website/Sauron/.venv/bin/python -m uvicorn sauron.main:app --host 127.0.0.1 --port 8003 --log-level info
