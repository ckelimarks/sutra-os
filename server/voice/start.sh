#!/bin/bash
# Start the Sutra voice client
cd "$(dirname "$0")/../.."
source .env 2>/dev/null  # load API keys if present
python3 -m server.voice.voice_client "$@"
