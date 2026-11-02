#!/bin/sh
# Start the JARVIS laptop agent (pair once first: python -m laptop_agent pair URL).
cd "$(dirname "$0")/../JarvisAI" || exit 1
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" -m laptop_agent "$@"
