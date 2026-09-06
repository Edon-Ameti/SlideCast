#!/bin/sh
# Starts SlideCast on macOS. The Windows equivalent is run.bat.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo
  echo "  Python 3 was not found. Run ./setup.sh first."
  echo
  exit 1
fi

echo
echo "  Starting SlideCast. Leave this window open while you use it."
echo "  Press Ctrl+C here to stop."
echo
exec python3 serve.py
