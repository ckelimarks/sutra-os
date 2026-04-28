#!/bin/bash
# Sutra Phase 1 — Ralph Loop Runner
# Runs Haiku agents in a loop. Each iteration reads PROMPT.md + TASK.md, completes one task, commits, exits.

set -e

SUTRA_DIR="/Users/christopherk.marks/Downloads/personal-os-main/Projects/prototypes/sutra-build"
PHASE_DIR="$SUTRA_DIR/phase-1"
PROMPT_FILE="$PHASE_DIR/PROMPT.md"
TASK_FILE="$PHASE_DIR/TASK.md"
LOG_FILE="$PHASE_DIR/ralph.log"
MAX_ITERATIONS=20

# Build instance uses ports 8910/8911 to avoid conflict with main sutra on 8900/8901
export SUTRA_PORT=8910
export SUTRA_WS_PORT=8911

cd "$SUTRA_DIR"

# Check prerequisites
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: PROMPT.md not found at $PROMPT_FILE"
    exit 1
fi

if [ ! -f "$TASK_FILE" ]; then
    echo "ERROR: TASK.md not found at $TASK_FILE"
    exit 1
fi

# Ensure build server is running on 8910
if ! curl -s http://localhost:8910/api/health > /dev/null 2>&1; then
    echo "WARNING: Sutra-build server not running on 8910. Starting it..."
    ./start.sh &
    sleep 3
fi

echo "=== Ralph Loop Started: $(date) ===" | tee -a "$LOG_FILE"
echo "Max iterations: $MAX_ITERATIONS" | tee -a "$LOG_FILE"

for i in $(seq 1 $MAX_ITERATIONS); do
    echo "" | tee -a "$LOG_FILE"
    echo "--- Iteration $i / $MAX_ITERATIONS: $(date) ---" | tee -a "$LOG_FILE"

    # Check if all tasks done
    if ! grep -q '^\- \[ \]' "$TASK_FILE"; then
        echo "✓ All tasks complete!" | tee -a "$LOG_FILE"
        break
    fi

    # Show current unchecked task
    NEXT_TASK=$(grep -m 1 '^\- \[ \]' "$TASK_FILE" | head -c 100)
    echo "Next task: $NEXT_TASK" | tee -a "$LOG_FILE"

    # Launch Haiku agent in bypass-permissions mode
    # --print for non-interactive
    # --model haiku for cheap iterations
    # --permission-mode bypassPermissions for YOLO sandbox

    PROMPT=$(cat "$PROMPT_FILE")

    claude \
        --print \
        --model haiku \
        --permission-mode bypassPermissions \
        --append-system-prompt "$PROMPT" \
        "Read phase-1/TASK.md and complete the first unchecked task. Follow PHASE-1-PLAN.md for the full spec. Commit your work and exit." \
        2>&1 | tee -a "$LOG_FILE"

    # Short delay between iterations
    sleep 3
done

echo "" | tee -a "$LOG_FILE"
echo "=== Ralph Loop Finished: $(date) ===" | tee -a "$LOG_FILE"

# Summary
COMPLETED=$(grep -c '^\- \[x\]' "$TASK_FILE" || echo 0)
REMAINING=$(grep -c '^\- \[ \]' "$TASK_FILE" || echo 0)
echo "Completed: $COMPLETED / $(($COMPLETED + $REMAINING))" | tee -a "$LOG_FILE"
