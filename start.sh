#!/bin/bash
# Start the Sutra orchestrator
set -e

cd "$(dirname "$0")"

# Source .env if present (variables defined there become available to the
# Python servers below). Lines beginning with # are skipped.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export SUTRA_PORT=${SUTRA_PORT:-8900}
export SUTRA_WS_PORT=${SUTRA_WS_PORT:-8901}

# Pick a Python interpreter. Sutra requires 3.10+ (Continuum's spoof_tool.py
# uses PEP 604 union types that aren't valid in 3.9). Stock macOS python3
# is 3.9, so we look for newer interpreters by name first.
PYTHON=${SUTRA_PYTHON:-}
if [ -z "$PYTHON" ]; then
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver=$("$cand" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo 0)
      major=${ver%.*}; minor=${ver#*.}
      if [ "$major" -ge 3 ] 2>/dev/null && [ "$minor" -ge 10 ] 2>/dev/null; then
        PYTHON="$cand"
        break
      fi
    fi
  done
fi
if [ -z "$PYTHON" ]; then
  echo "Sutra requires Python 3.10 or newer." >&2
  echo "Install one (brew install python@3.12 / apt install python3.12) and re-run." >&2
  echo "Or set SUTRA_PYTHON=/path/to/python in your .env" >&2
  exit 1
fi
echo "Using interpreter: $PYTHON ($($PYTHON --version))"

# Ensure dependencies are installed (uses python -m pip so it works even when
# 'pip' isn't on PATH — common on stock macOS).
"$PYTHON" -c "import websockets" 2>/dev/null || {
  echo "Installing dependencies via $PYTHON -m pip ..."
  "$PYTHON" -m pip install -r requirements.txt
}

# Kill any process already on our ports
lsof -ti:$SUTRA_PORT 2>/dev/null | xargs kill 2>/dev/null || true
lsof -ti:$SUTRA_WS_PORT 2>/dev/null | xargs kill 2>/dev/null || true
sleep 1

echo "Starting Sutra Orchestrator..."
echo "  HTTP Server: http://localhost:$SUTRA_PORT"
echo "  WebSocket:   ws://localhost:$SUTRA_WS_PORT"
echo ""

# Bridge owns DB migrations. Start it first and give it a moment to finish
# init_db() before the WebSocket server connects (avoids a parallel-init race
# on first run with a fresh database).
"$PYTHON" server/bridge.py &
HTTP_PID=$!
sleep 1
"$PYTHON" server/ws_server.py &
WS_PID=$!

trap "echo 'Shutting down...'; kill $HTTP_PID $WS_PID 2>/dev/null; exit" INT TERM

echo "Press Ctrl+C to stop"
echo ""

wait
