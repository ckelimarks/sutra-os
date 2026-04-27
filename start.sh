#!/bin/bash
# Start the Sutra orchestrator

cd "$(dirname "$0")"

export SUTRA_PORT=${SUTRA_PORT:-8900}
export SUTRA_WS_PORT=${SUTRA_WS_PORT:-8901}

# Check for dependencies
python3 -c "import websockets" 2>/dev/null || {
    echo "Installing websockets..."
    pip install websockets
}

# Kill any existing Sutra servers (not agent-chat on 8890)
lsof -ti:$SUTRA_PORT | xargs kill 2>/dev/null
lsof -ti:$SUTRA_WS_PORT | xargs kill 2>/dev/null
sleep 1

echo "Starting Sutra Orchestrator..."
echo "  HTTP Server: http://localhost:$SUTRA_PORT"
echo "  WebSocket:   ws://localhost:$SUTRA_WS_PORT"
echo ""

# Start HTTP server in background
python3 server/bridge.py &
HTTP_PID=$!

# Start WebSocket server in background
python3 server/ws_server.py &
WS_PID=$!

# Handle Ctrl+C
trap "echo 'Shutting down...'; kill $HTTP_PID $WS_PID 2>/dev/null; exit" INT TERM

echo "Press Ctrl+C to stop"
echo ""

# Wait for either to exit
wait
