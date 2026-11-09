#!/bin/sh
# Start the JARVIS hub (works on Windows via Git Bash, Linux, macOS, Raspberry Pi).
# Settings: environment variables or JARVIS_HUB_CONFIG (see jarvis/hub/config.py).
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" -m jarvis.hub "$@"
