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
