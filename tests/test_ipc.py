"""Integration tests for IPC client and Qt-based IPC server."""

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


def test_ipc_server_lifecycle(qapp, tmp_path):
    socket_path = tmp_path / "test-bridge.sock"
    queue = RequestQueue()
    sessions = SessionStore()

    server = IpcServer(queue, sessions, socket_path=socket_path)
    assert server.start() is True
    assert socket_path.exists()

    client = IpcClient(socket_path=socket_path)
    assert client.is_available() is True

    server.stop()
    assert client.is_available() is False


def test_ipc_submit_and_resolve_roundtrip(qapp, tmp_path):
    socket_path = tmp_path / "test-bridge-roundtrip.sock"
    queue = RequestQueue()
    sessions = SessionStore()

    server = IpcServer(queue, sessions, socket_path=socket_path)
    assert server.start() is True

    client = IpcClient(socket_path=socket_path)
    client_result = {}

    def run_client():
        msg = IpcMessage(
            type=MessageType.SUBMIT_REQUEST,
            conversation_id="conv-integration-1",
            payload={
                "request_id": "req-integration-1",
                "toolCall": {
                    "name": "ask_permission",
                    "args": {
                        "action": "run_command",
                        "target": "make test",
                        "reason": "Test suite",
                    },
                },
            },
        )
        resp = client.send_and_wait(msg, timeout=5.0)
        client_result["response"] = resp

    t = threading.Thread(target=run_client)
    t.start()

    # Process Qt events until request is received
    for _ in range(50):
        QCoreApplication.processEvents()
        if queue.count() == 1:
            break
        time.sleep(0.05)

    assert queue.count() == 1
    req = queue.get_active()
    assert req is not None
    assert req.request_id == "req-integration-1"

    # Simulate UI or CLI resolver answering in a separate client thread
    resolver_result = {}

    def run_resolver():
        resolver = IpcClient(socket_path=socket_path)
        resolve_msg = IpcMessage(
            type=MessageType.RESOLVE_REQUEST,
            request_id="req-integration-1",
            payload={"response": "allow"},
        )
        resolver_result["response"] = resolver.send_and_wait(resolve_msg, timeout=5.0)

    t2 = threading.Thread(target=run_resolver)
    t2.start()

    # Process events so server processes both the resolver and adapter sockets
    for _ in range(60):
        QCoreApplication.processEvents()
        if not t.is_alive() and not t2.is_alive():
            break
        time.sleep(0.05)

    t.join(timeout=3.0)
    t2.join(timeout=3.0)

    resolve_resp = resolver_result.get("response")
    assert resolve_resp is not None
    assert resolve_resp.get("status") == "ok"

    # Verify adapter client received the decision
    assert "response" in client_result
    assert client_result["response"] is not None
    assert client_result["response"]["status"] == "ok"
    assert client_result["response"]["data"]["decision"] == "allow"

    # Verify request consumed from queue
    assert queue.count() == 0

    server.stop()
