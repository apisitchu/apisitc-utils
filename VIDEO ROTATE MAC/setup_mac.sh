#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================="
echo "Video Rotate - macOS Setup"
echo "============================================="

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 not found."
  echo "Install Python first: https://www.python.org/downloads/macos/"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "ffmpeg not found. Installing via Homebrew..."
    brew install ffmpeg
  else
    echo "[ERROR] ffmpeg not found and Homebrew is not installed."
    echo "Install Homebrew from https://brew.sh then run: brew install ffmpeg"
    exit 1
  fi
fi

echo
echo "Running self-check..."
python3 -m py_compile video_rotator.py
python3 video_rotator.py --help >/dev/null
python3 video_rotator.py --input . --direction right >/dev/null

echo
echo "[OK] Setup complete."
echo "You can now run: ./run_rotate.sh"
