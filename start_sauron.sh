#!/bin/bash
# Sauron startup wrapper — used by LaunchAgent
cd /Users/stephen/Documents/Website/Sauron

# Load environment variables
set -a
source .env
set +a

# Ensure Homebrew binaries (ffmpeg, etc.) are in PATH
export PATH=/opt/homebrew/bin:$PATH

# Clear __pycache__ to prevent stale module issues
find sauron -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null

# ── Log rotation (10MB max, keep 2 archives) ──
rotate_log() {
    local f="$1"
    local max_bytes=10485760  # 10MB
    if [ -f "$f" ]; then
        local size
        size=$(stat -f%z "$f" 2>/dev/null || echo 0)
        if [ "$size" -gt "$max_bytes" ]; then
            [ -f "${f}.2" ] && rm -f "${f}.2"
            [ -f "${f}.1" ] && mv "${f}.1" "${f}.2"
            mv "$f" "${f}.1"
        fi
    fi
}

rotate_log logs/sauron.stderr.log
rotate_log logs/sauron.stdout.log

exec /Users/stephen/Documents/Website/Sauron/.venv/bin/python -m uvicorn sauron.main:app --host 127.0.0.1 --port 8003 --log-level info     >>logs/sauron.stdout.log 2>>logs/sauron.stderr.log
