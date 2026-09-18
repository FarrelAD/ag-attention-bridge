"""Comprehensive end-to-end tests for Ag Attention Bridge response flows."""

import os
import threading
import time
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from ag_attention_bridge.domain.models import RequestType
from ag_attention_bridge.ipc.client import IpcClient
from ag_attention_bridge.ipc.protocol import IpcMessage, MessageType
from ag_attention_bridge.ipc.server import IpcServer
from ag_attention_bridge.state.store import PendingInjectionStore, RequestQueue, SessionStore


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _process_events_until(predicate, max_iters=50, interval=0.02):
    """Process Qt events until predicate returns True or max iterations."""
    for _ in range(max_iters):
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _client_send(client, msg, timeout=5.0):
    """Helper to send IPC request in background thread while pumping Qt event loop."""
    result = {}

    def _worker():
        result["resp"] = client.send_and_wait(msg, timeout=timeout)

    t = threading.Thread(target=_worker)
    t.start()
    for _ in range(int(timeout * 50)):
        QCoreApplication.processEvents()
        if "resp" in result:
            break
        time.sleep(0.02)
    t.join(timeout=1.0)
    return result.get("resp")


class TestPermissionBridgeResponseFlow:
    """Verify that permission requests produce valid Antigravity hook JSON responses."""


    def test_permission_allow_returns_valid_hook_json(self, qapp, tmp_path):
        """Allow button → hook adapter receives {"decision": "allow"} immediately."""
        socket_path = tmp_path / "test-perm-allow.sock"
        queue = RequestQueue()
        sessions = SessionStore()
        injections = PendingInjectionStore()

        server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
        assert server.start() is True

        client = IpcClient(socket_path=socket_path)
        client_result = {}

        def run_client():
            msg = IpcMessage(
                type=MessageType.SUBMIT_REQUEST,
                conversation_id="conv-perm-1",
                payload={
                    "request_id": "perm-allow-1",
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "npm test", "toolSummary": "Run tests"},
                    },
                },
            )
            client_result["resp"] = client.send_and_wait(msg, timeout=5.0)

        t = threading.Thread(target=run_client)
        t.start()

        assert _process_events_until(lambda: queue.count() == 1)
        assert queue.count() == 1

        req = queue.get_active()
        assert req is not None
        assert req.request_type == RequestType.PERMISSION
        assert req.request_id == "perm-allow-1"

        # Simulate user clicking Allow
        server.resolve_request("perm-allow-1", "allow")
        _process_events_until(lambda: bool(client_result.get("resp")), max_iters=30)

        t.join(timeout=2.0)
        assert client_result.get("resp") is not None
        data = client_result["resp"]["data"]
        assert data["decision"] == "allow"
        assert "permissionOverrides" in data
        assert data["permissionOverrides"] == ["command(npm test)"]

        server.stop()

    def test_permission_deny_returns_valid_hook_json(self, qapp, tmp_path):
        """Deny button → hook adapter receives {"decision": "deny", "reason": "..."}."""
        socket_path = tmp_path / "test-perm-deny.sock"
        queue = RequestQueue()
        sessions = SessionStore()
        injections = PendingInjectionStore()

        server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
        assert server.start() is True

        client = IpcClient(socket_path=socket_path)
        client_result = {}

        def run_client():
            msg = IpcMessage(
                type=MessageType.SUBMIT_REQUEST,
                conversation_id="conv-perm-2",
                payload={
                    "request_id": "perm-deny-1",
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "rm -rf /", "toolSummary": "Dangerous command"},
                    },
                },
            )
            client_result["resp"] = client.send_and_wait(msg, timeout=5.0)

        t = threading.Thread(target=run_client)
        t.start()

        assert _process_events_until(lambda: queue.count() == 1)

        # Simulate user clicking Deny
        server.resolve_request("perm-deny-1", "deny")
        _process_events_until(lambda: bool(client_result.get("resp")), max_iters=30)

        t.join(timeout=2.0)
        assert client_result.get("resp") is not None
        data = client_result["resp"]["data"]
        assert data["decision"] == "deny"
        assert "reason" in data
        assert "Denied through Ag Attention Bridge" in data["reason"]

        server.stop()


class TestQuestionBridgeResponseFlow:
    """Verify ask_question bypasses native UI and injects answer via PreInvocation."""

    def test_question_single_select_returns_deny_and_injects_preinvocation(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr("ag_attention_bridge.ipc.server.SYNTHETIC_FALLBACK_ENABLED", True)
        socket_path = tmp_path / "test-q-single.sock"
        queue = RequestQueue()
        sessions = SessionStore()
        injections = PendingInjectionStore()

        server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
        assert server.start() is True

        client = IpcClient(socket_path=socket_path)
        client_result = {}

        def run_client():
            msg = IpcMessage(
                type=MessageType.SUBMIT_REQUEST,
                conversation_id="conv-q-1",
                payload={
                    "request_id": "q-single-1",
                    "toolCall": {
                        "name": "ask_question",
                        "args": {
                            "questions": [
                                {
                                    "question": "Which framework should we use?",
                                    "options": ["React", "Vue", "Svelte"],
                                    "is_multi_select": False,
                                }
                            ]
                        },
                    },
                },
            )
            client_result["resp"] = client.send_and_wait(msg, timeout=5.0)

        t = threading.Thread(target=run_client)
        t.start()

        assert _process_events_until(lambda: queue.count() == 1)

        req = queue.get_active()
        assert req is not None
        assert req.request_type == RequestType.QUESTION
        assert req.title == "Which framework should we use?"

        # Simulate user selecting "Vue"
        server.resolve_request("q-single-1", [{"question": "Which framework should we use?", "selected": ["Vue"]}])
        _process_events_until(lambda: bool(client_result.get("resp")), max_iters=30)

        t.join(timeout=2.0)
        assert client_result.get("resp") is not None
        data = client_result["resp"]["data"]
        # Must be deny to suppress native UI
        assert data["decision"] == "deny"
        assert "Ag Attention Bridge" in data["reason"]

        # PreInvocation hook fetches answer
        pre_inv = _client_send(
            client,
            IpcMessage(type=MessageType.GET_PENDING_INJECTION, conversation_id="conv-q-1"),
            timeout=2.0,
        )
        assert pre_inv is not None
        assert pre_inv["data"]["has_injection"] is True
        assert "Vue" in pre_inv["data"]["injectSteps"][0]["userMessage"]

        server.stop()


    def test_esc_hides_but_request_stays_pending(self, qapp, tmp_path):
        """Esc/close should NOT resolve the request — adapter keeps waiting."""
        socket_path = tmp_path / "test-q-esc.sock"
        queue = RequestQueue()
        sessions = SessionStore()
        injections = PendingInjectionStore()

        server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
        assert server.start() is True

        client = IpcClient(socket_path=socket_path)

        def run_client():
            msg = IpcMessage(
                type=MessageType.SUBMIT_REQUEST,
                conversation_id="conv-esc",
                payload={
                    "request_id": "esc-1",
                    "toolCall": {
                        "name": "ask_permission",
                        "args": {"action": "write_to_file", "target": "/tmp/test"},
                    },
                },
            )
            return client.send_and_wait(msg, timeout=3.0)

        t = threading.Thread(target=run_client)
        t.start()

        assert _process_events_until(lambda: queue.count() == 1)

        # Simulate Esc: dismiss to tray
        queue.dismiss_to_tray("esc-1")

        # Verify request is still pending
        assert queue.count() == 1
        req = queue.get_active()
        assert req is not None
        assert req.request_id == "esc-1"

        # Now resolve it
        def resolve_later():
            time.sleep(0.2)
            server.resolve_request("esc-1", "allow")

        resolve_thread = threading.Thread(target=resolve_later)
        resolve_thread.start()

        _process_events_until(lambda: queue.count() == 0, max_iters=50)

        t.join(timeout=5.0)
        resolve_thread.join(timeout=2.0)

        assert queue.count() == 0
        server.stop()

    def test_multi_request_correlation(self, qapp, tmp_path):
        """Two requests from different conversations resolve independently."""
        socket_path = tmp_path / "test-multi.sock"
        queue = RequestQueue()
        sessions = SessionStore()
        injections = PendingInjectionStore()

        server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
        assert server.start() is True

        client_a = IpcClient(socket_path=socket_path)
        client_b = IpcClient(socket_path=socket_path)
        result_a = {}
        result_b = {}

        def run_a():
            msg = IpcMessage(
                type=MessageType.SUBMIT_REQUEST,
                conversation_id="conv-A",
                payload={
                    "request_id": "req-A",
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "make build"},
                    },
                },
            )
            result_a["resp"] = client_a.send_and_wait(msg, timeout=5.0)

        def run_b():
            msg = IpcMessage(
                type=MessageType.SUBMIT_REQUEST,
                conversation_id="conv-B",
                payload={
                    "request_id": "req-B",
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "make test"},
                    },
                },
            )
            result_b["resp"] = client_b.send_and_wait(msg, timeout=5.0)

        ta = threading.Thread(target=run_a)
        tb = threading.Thread(target=run_b)
        ta.start()
        time.sleep(0.1)
        tb.start()

        assert _process_events_until(lambda: queue.count() == 2)

        # Resolve B first (out of order), then A
        server.resolve_request("req-B", "deny")
        _process_events_until(lambda: bool(result_b.get("resp")), max_iters=30)

        server.resolve_request("req-A", "allow")
        _process_events_until(lambda: bool(result_a.get("resp")), max_iters=30)

        ta.join(timeout=2.0)
        tb.join(timeout=2.0)

        # Verify responses are correctly routed
        assert result_a["resp"]["data"]["decision"] == "allow"
        assert result_a["resp"]["data"]["permissionOverrides"] == ["command(make build)"]
        assert result_b["resp"]["data"]["decision"] == "deny"
        assert "Denied through Ag Attention Bridge" in result_b["resp"]["data"]["reason"]

        server.stop()
