#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ADAPTER="$REPO_ROOT/scripts/hook-adapter.sh"
LOG_FILE="$REPO_ROOT/.agents/logs/events.jsonl"

echo "=== Testing Live Hook Adapter Pipes ==="

# Clean local test log
mkdir -p "$REPO_ROOT/.agents/logs"
> "$LOG_FILE"

# 1. PreToolUse: ask_question
echo -n "1. Testing PreToolUse (ask_question)... "
RESP1=$(cat <<EOF | "$ADAPTER" --event PreToolUse
{
  "conversationId": "test-live-session-001",
  "workspacePaths": ["$REPO_ROOT"],
  "transcriptPath": "$REPO_ROOT/.agents/logs/transcript.jsonl",
  "modelName": "gemini-3.8-flash",
  "stepIdx": 1,
  "toolCall": {
    "name": "ask_question",
    "args": {
      "questions": [
        {
          "question": "Which backend should we choose?",
          "options": ["FastAPI", "Go", "Rust"]
        }
      ]
    }
  }
}
EOF
)
echo "STDOUT: $RESP1"
if [[ "$RESP1" != *'"decision"'* ]]; then
    echo "FAILED: unexpected response for ask_question" >&2
    exit 1
fi

# 2. PreToolUse: ask_permission
echo -n "2. Testing PreToolUse (ask_permission)... "
RESP2=$(cat <<EOF | "$ADAPTER" --event PreToolUse
{
  "conversationId": "test-live-session-001",
  "workspacePaths": ["$REPO_ROOT"],
  "transcriptPath": "$REPO_ROOT/.agents/logs/transcript.jsonl",
  "modelName": "gemini-3.8-flash",
  "stepIdx": 2,
  "toolCall": {
    "name": "ask_permission",
    "args": {
      "action": "run_command",
      "target": "rm -rf build/",
      "reason": "Clean build directory"
    }
  }
}
EOF
)
echo "STDOUT: $RESP2"
if [[ "$RESP2" != *'"decision"'* ]]; then
    echo "FAILED: unexpected response for ask_permission" >&2
    exit 1
fi

# 3. PostInvocation
echo -n "3. Testing PostInvocation... "
RESP3=$(cat <<EOF | "$ADAPTER" --event PostInvocation
{
  "conversationId": "test-live-session-001",
  "workspacePaths": ["$REPO_ROOT"],
  "invocationNum": 1,
  "initialNumSteps": 3
}
EOF
)
echo "STDOUT: $RESP3"
if [[ "$RESP3" != "{}" ]]; then
    echo "FAILED: unexpected response for PostInvocation" >&2
    exit 1
fi

# 4. Stop
echo -n "4. Testing Stop... "
RESP4=$(cat <<EOF | "$ADAPTER" --event Stop
{
  "conversationId": "test-live-session-001",
  "workspacePaths": ["$REPO_ROOT"],
  "executionNum": 1,
  "terminationReason": "model_stop",
  "fullyIdle": true
}
EOF
)
echo "STDOUT: $RESP4"
if [[ "$RESP4" != "{}" ]]; then
    echo "FAILED: unexpected response for Stop" >&2
    exit 1
fi

# 5. Verify observation logs
echo -n "5. Verifying observation log in $LOG_FILE... "
RECORD_COUNT=$(wc -l < "$LOG_FILE")
if [ "$RECORD_COUNT" -ne 4 ]; then
    echo "FAILED: expected 4 records, found $RECORD_COUNT" >&2
    exit 1
fi
echo "OK ($RECORD_COUNT events recorded)"

echo ""
echo "=== All Live Hook Adapter Pipe Tests PASSED ==="
