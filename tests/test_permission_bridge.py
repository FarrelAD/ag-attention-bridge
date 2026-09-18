"""Unit tests for Phase 4 Permission Bridge resolution."""

import os
import threading
import time
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from ag_attention_bridge.ipc.client import IpcClient
from ag_attention_bridge.ipc.protocol import IpcMessage, MessageType
from ag_attention_bridge.ipc.server import IpcServer
from ag_attention_bridge.state.store import RequestQueue, SessionStore


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_permission_bridge_allow_and_deny(qapp, tmp_path):
    socket_path = tmp_path / "test-perm-bridge.sock"
    queue = RequestQueue()
    sessions = SessionStore()

    server = IpcServer(queue, sessions, socket_path=socket_path)
    assert server.start() is True

    client = IpcClient(socket_path=socket_path)

    # 1. Test Allow
    allow_result = {}

    def run_allow():
        msg = IpcMessage(
            type=MessageType.SUBMIT_REQUEST,
            conversation_id="conv-perm-1",
            payload={
                "request_id": "perm-req-allow",
                "toolCall": {
                    "name": "ask_permission",
                    "args": {"action": "write_to_file", "target": "/tmp/test.py"},
                },
            },
        )
        allow_result["resp"] = client.send_and_wait(msg, timeout=5.0)

    t1 = threading.Thread(target=run_allow)
    t1.start()

    for _ in range(50):
        QCoreApplication.processEvents()
        if queue.count() == 1:
            break
        time.sleep(0.02)

    assert queue.count() == 1
    # Resolve allow directly via server
    server.resolve_request("perm-req-allow", "allow")

    for _ in range(20):
        QCoreApplication.processEvents()
        time.sleep(0.02)

    t1.join(timeout=2.0)
    assert allow_result.get("resp") is not None
    assert allow_result["resp"]["data"]["decision"] == "allow"
    assert allow_result["resp"]["data"].get("permissionOverrides") == ["write_to_file(/tmp/test.py)"]

    # 2. Test Deny
    deny_result = {}

    def run_deny():
        msg = IpcMessage(
            type=MessageType.SUBMIT_REQUEST,
            conversation_id="conv-perm-1",
            payload={
                "request_id": "perm-req-deny",
                "toolCall": {
                    "name": "ask_permission",
                    "args": {"action": "run_command", "target": "rm -rf /"},
                },
            },
        )
        deny_result["resp"] = client.send_and_wait(msg, timeout=5.0)

    t2 = threading.Thread(target=run_deny)
    t2.start()

    for _ in range(50):
        QCoreApplication.processEvents()
        if queue.count() == 1:
            break
        time.sleep(0.02)

    assert queue.count() == 1
    server.resolve_request("perm-req-deny", "deny")

    for _ in range(20):
        QCoreApplication.processEvents()
        time.sleep(0.02)

    t2.join(timeout=2.0)
    assert deny_result.get("resp") is not None
    assert deny_result["resp"]["status"] == "ok"
    data = deny_result["resp"]["data"]
    assert data["decision"] == "deny"
    assert "reason" in data
    assert "denied" in data["reason"].lower()

    server.stop()


def test_auto_discovery_check_waiting_permission(qapp, tmp_path):
    """Verify CHECK_WAITING triggers background discovery and enqueues PERMISSION interaction."""
    from ag_attention_bridge.antigravity.models import InteractionType, PermissionScope
    from ag_attention_bridge.domain.models import RequestType

    socket_path = tmp_path / "test-check-waiting.sock"
    queue = RequestQueue()
    sessions = SessionStore()

    class MockResolver:
        def resolve_authoritative_waiting_interaction(self, cascade_id, workspace_path=None, max_retries=6):
            return {
                "trajectory_id": "traj-perm-auto-1",
                "step_index": 18,
                "interaction_type": InteractionType.PERMISSION,
                "permission_action": "run_command",
                "permission_target": 'find /home/mashupsoat/Project -name "*.tex" 2>/dev/null',
                "permission_reason": "Allow finding all tex files?",
            }

    server = IpcServer(queue, sessions, socket_path=socket_path, resolver=MockResolver())
    assert server.start() is True

    client = IpcClient(socket_path=socket_path)

    # Send CHECK_WAITING notification as if from PostInvocation hook
    msg = IpcMessage(
        type=MessageType.CHECK_WAITING,
        conversation_id="conv-auto-perm-1",
        payload={"workspacePaths": ["/home/mashupsoat/Project/polinema-logbook-ai-tools"]},
    )
    
    t = threading.Thread(target=lambda: client.send_and_wait(msg, timeout=5.0))
    t.start()

    # Wait for background worker to discover and emit to Qt main thread
    for _ in range(50):
        QCoreApplication.processEvents()
        if queue.count() == 1:
            break
        time.sleep(0.02)

    t.join(timeout=2.0)

    assert queue.count() == 1
    req = queue.get_active()
    assert req is not None
    assert req.request_type == RequestType.PERMISSION
    assert req.conversation_id == "conv-auto-perm-1"
    assert req.trajectory_id == "traj-perm-auto-1"
    assert req.step_index == 18
    assert "find /home/mashupsoat/Project" in req.body
    assert "Allow finding all tex files?" in req.title

    # Test that resolving an auto-discovered request unconditionally consumes it
    assert server.resolve_request(req.request_id, "allow") is True
    assert queue.count() == 0

    server.stop()


def test_auto_purge_stale_step_in_same_conversation(qapp, tmp_path):
    """Verify that when a newer step interaction arrives for the same conversation, older steps are purged."""
    from ag_attention_bridge.antigravity.models import InteractionType
    from ag_attention_bridge.domain.models import InteractionRequest, RequestType

    socket_path = tmp_path / "test-stale-purge.sock"
    queue = RequestQueue()
    sessions = SessionStore()

    server = IpcServer(queue, sessions, socket_path=socket_path)
    assert server.start() is True

    # 1. Enqueue older step (e.g. step 154)
    old_req = InteractionRequest(
        request_id="auto-conv-purge-154",
        conversation_id="conv-purge",
        request_type=RequestType.PERMISSION,
        title="Old Step 154",
        body="discover",
        step_index=154,
    )
    queue.enqueue(old_req)
    assert queue.count() == 1

    # 2. Simulate discovery of newer step 157 for the same conversation
    resolved_newer = {
        "trajectory_id": "traj-purge-1",
        "step_index": 157,
        "interaction_type": InteractionType.PERMISSION,
        "permission_action": "run_command",
        "permission_target": "prepare",
        "permission_reason": "Prepare month",
    }
    server._on_interaction_discovered(
        resolved_newer,
        {"conversation_id": "conv-purge", "workspace_path": "/tmp"},
    )

    # Old step 154 must have been purged, leaving only step 157 in queue (count == 1, not 2!)
    assert queue.count() == 1
    active = queue.get_active()
    assert active is not None
    assert active.step_index == 157
    assert active.title == "Prepare month"

    server.stop()

