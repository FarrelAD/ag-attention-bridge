#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ADAPTER="$REPO_ROOT/scripts/hook-adapter.sh"
SOCKET_PATH="${XDG_RUNTIME_DIR:-/tmp/ag-bridge-$UID}/ag-attention-bridge.sock"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python3"
DAEMON_LOG="/tmp/ag-daemon-test.log"

echo "=== Testing Phase 2 Live IPC & Tray Queue ==="

# 1. Ensure any previous instance is killed
pkill -f "ag_attention_bridge.app" 2>/dev/null || true
rm -f "$SOCKET_PATH"

# 2. Start daemon in background
echo -n "1. Starting Ag Attention Bridge daemon in background... "
QT_QPA_PLATFORM=offscreen "$PYTHON_BIN" -m ag_attention_bridge.app > "$DAEMON_LOG" 2>&1 &
DAEMON_PID=$!

# Cleanup on exit
cleanup() {
    kill -TERM "$DAEMON_PID" 2>/dev/null || true
    wait "$DAEMON_PID" 2>/dev/null || true
    rm -f "$SOCKET_PATH"
}
trap cleanup EXIT

# Wait for socket to become ready (up to 5 seconds)
for i in {1..50}; do
    if [ -S "$SOCKET_PATH" ]; then
        break
    fi
    sleep 0.1
done

if [ ! -S "$SOCKET_PATH" ]; then
    echo "FAILED: Socket $SOCKET_PATH did not appear" >&2
    cat "$DAEMON_LOG" >&2
    exit 1
fi
echo "OK (PID: $DAEMON_PID, Socket: $SOCKET_PATH)"

# 3. Test submitting a request via hook-adapter.sh in background
echo -n "2. Submitting synthetic ask_permission via hook-adapter.sh... "
ADAPTER_OUT="/tmp/adapter-test-out.json"
rm -f "$ADAPTER_OUT"

cat <<EOF | "$ADAPTER" --event PreToolUse > "$ADAPTER_OUT" 2>&1 &
{
  "conversationId": "live-phase2-session",
  "workspacePaths": ["$REPO_ROOT"],
  "modelName": "gemini-3.8-flash",
  "stepIdx": 1,
  "toolCall": {
    "name": "ask_permission",
    "args": {
      "action": "run_command",
      "target": "git push origin main",
      "reason": "Push changes"
    }
  }
}
EOF
ADAPTER_PID=$!

# Give daemon a moment to process the connection
sleep 0.5

# 4. Query queue status using Python IPC client
echo -n "3. Querying daemon queue via IPC... "
QUEUE_INFO=$("$PYTHON_BIN" - <<EOF
from ag_attention_bridge.ipc.client import IpcClient
from ag_attention_bridge.ipc.protocol import IpcMessage, MessageType
import json, sys

client = IpcClient()
resp = client.send_and_wait(IpcMessage(type=MessageType.GET_QUEUE), timeout=2.0)
if resp and resp.get("status") == "ok":
    data = resp.get("data", {})
    count = data.get("count", 0)
    items = data.get("items", [])
    req_id = items[0]["request_id"] if items else ""
    print(f"{count}|{req_id}")
    sys.exit(0)
sys.exit(1)
EOF
)

COUNT=$(echo "$QUEUE_INFO" | cut -d'|' -f1)
REQ_ID=$(echo "$QUEUE_INFO" | cut -d'|' -f2)

if [ "$COUNT" -ne 1 ]; then
    echo "FAILED: Expected queue count 1, got $COUNT" >&2
    exit 1
fi
echo "OK (Queue count: $COUNT, Request ID: $REQ_ID)"

# 5. Resolve the request via IPC
echo -n "4. Resolving request $REQ_ID with 'allow'... "
RESOLVE_OK=$("$PYTHON_BIN" - <<EOF
from ag_attention_bridge.ipc.client import IpcClient
from ag_attention_bridge.ipc.protocol import IpcMessage, MessageType
import sys

client = IpcClient()
resp = client.send_and_wait(
    IpcMessage(
        type=MessageType.RESOLVE_REQUEST,
        request_id="$REQ_ID",
        payload={"response": "allow"}
    ),
    timeout=2.0
)
if resp and resp.get("status") == "ok":
    sys.exit(0)
sys.exit(1)
EOF
)
echo "OK"

# 6. Wait for adapter process to complete and verify stdout
echo -n "5. Verifying hook-adapter stdout received decision... "
wait "$ADAPTER_PID"
ADAPTER_RESULT=$(cat "$ADAPTER_OUT")
echo "STDOUT: $ADAPTER_RESULT"

if [[ "$ADAPTER_RESULT" != *'"decision": "allow"'* && "$ADAPTER_RESULT" != *'"decision":"allow"'* ]]; then
    echo "FAILED: Expected decision allow in adapter output" >&2
    exit 1
fi
echo "OK"

# 7. Check queue is now 0
echo -n "6. Verifying queue is empty after resolution... "
REMAINING_COUNT=$("$PYTHON_BIN" - <<EOF
from ag_attention_bridge.ipc.client import IpcClient
from ag_attention_bridge.ipc.protocol import IpcMessage, MessageType
client = IpcClient()
resp = client.send_and_wait(IpcMessage(type=MessageType.GET_QUEUE), timeout=2.0)
print(resp.get("data", {}).get("count", -1))
EOF
)
if [ "$REMAINING_COUNT" -ne 0 ]; then
    echo "FAILED: Expected queue count 0, got $REMAINING_COUNT" >&2
    exit 1
fi
echo "OK ($REMAINING_COUNT pending)"

# 8. Test graceful fallback when daemon is terminated and autostart disabled
echo -n "7. Terminating daemon and testing graceful offline fallback (autostart disabled)... "
kill -TERM "$DAEMON_PID" 2>/dev/null || true
wait "$DAEMON_PID" 2>/dev/null || true
rm -f "$SOCKET_PATH"

FALLBACK_RESP=$(cat <<EOF | AG_ATTENTION_NO_AUTOSTART=1 "$ADAPTER" --event PreToolUse
{
  "conversationId": "offline-session",
  "workspacePaths": ["$REPO_ROOT"],
  "toolCall": {
    "name": "ask_question",
    "args": {
      "questions": [{"question": "Fallback check?"}]
    }
  }
}
EOF
)
echo "FALLBACK STDOUT: $FALLBACK_RESP"
if [[ "$FALLBACK_RESP" != *'"decision": "ask"'* && "$FALLBACK_RESP" != *'"decision":"ask"'* ]]; then
    echo "FAILED: Expected fallback decision ask" >&2
    exit 1
fi
echo "OK"

# 9. Test on-demand auto-start
echo -n "8. Testing on-demand auto-start when daemon is offline... "
AUTOSTART_OK=$("$PYTHON_BIN" - <<EOF
from ag_attention_bridge.ipc.client import IpcClient
from ag_attention_bridge.hooks.adapter import ensure_daemon_running
import sys

client = IpcClient()
ok = ensure_daemon_running(client, timeout=4.0)
sys.exit(0 if ok else 1)
EOF
)
echo "OK (Daemon auto-spawned successfully)"

echo ""
echo "=== Phase 2 Live IPC & Tray Queue Tests ALL PASSED ==="
