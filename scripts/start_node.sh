#!/bin/sh
# Start the JARVIS worker node on the dedicated device (Linux, macOS, Raspberry Pi, Git Bash).
# Settings: JARVIS_NODE_* environment variables (see jarvis/node/config.py and
# docs/architecture/MULTI_DEVICE.md). Issue a token first: python -m jarvis.node token laptop
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" -m jarvis.node serve "$@"
