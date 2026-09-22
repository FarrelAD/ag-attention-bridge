"""Unit tests for Phase 5 & 6 Question Bridge (ask_question) bypass and PreInvocation injection."""

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


def test_question_bridge_bypass_and_preinvocation_injection(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("ag_attention_bridge.ipc.server.SYNTHETIC_FALLBACK_ENABLED", True)
    socket_path = tmp_path / "test-q-bridge.sock"
    queue = RequestQueue()
    sessions = SessionStore()
    injections = PendingInjectionStore()

    server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
    assert server.start() is True

    client = IpcClient(socket_path=socket_path)
    client_result = {}

    # 1. Step 1: PreToolUse for ask_question
    def run_pre_tool():
        msg = IpcMessage(
            type=MessageType.SUBMIT_REQUEST,
            conversation_id="conv-q-1",
            payload={
                "request_id": "q-req-1",
                "toolCall": {
                    "name": "ask_question",
                    "args": {
                        "questions": [
                            {
                                "question": "Which architecture pattern should we use?",
                                "options": ["Clean Architecture", "Monolith"],
                                "is_multi_select": False,
                            }
                        ]
                    },
                },
            },
        )
        client_result["resp"] = client.send_and_wait(msg, timeout=5.0)

    t = threading.Thread(target=run_pre_tool)
    t.start()

    assert _process_events_until(lambda: queue.count() == 1)

    req = queue.get_active()
    assert req is not None
    assert req.request_type == RequestType.QUESTION
    assert req.title == "Which architecture pattern should we use?"

    # Resolve with answer
    server.resolve_request(
        "q-req-1",
        [
            {
                "question": "Which architecture pattern should we use?",
                "selected": ["Clean Architecture"],
            }
        ],
    )
    _process_events_until(lambda: bool(client_result.get("resp")), max_iters=30)

    t.join(timeout=2.0)
    assert client_result.get("resp") is not None
    data = client_result["resp"]["data"]
    # PreToolUse returns deny to suppress native UI
    assert data["decision"] == "deny"
    assert "Ag Attention Bridge" in data["reason"]

    # 2. Step 2: PreInvocation hook retrieves injected user message
    pre_inv_msg = IpcMessage(
        type=MessageType.GET_PENDING_INJECTION,
        conversation_id="conv-q-1",
    )
    pre_inv_resp = _client_send(client, pre_inv_msg, timeout=2.0)
    assert pre_inv_resp is not None
    assert pre_inv_resp["status"] == "ok"
    inj_data = pre_inv_resp["data"]
    assert inj_data.get("has_injection") is True
    assert "injectSteps" in inj_data
    user_msg = inj_data["injectSteps"][0]["userMessage"]
    assert "Clean Architecture" in user_msg
    assert "The user answered the previous question through Ag Attention Bridge" in user_msg

    # 3. Step 3: Second PreInvocation hook sees no pending injection (consumed)
    second_resp = _client_send(client, pre_inv_msg, timeout=2.0)
    assert second_resp is not None
    assert second_resp["data"].get("has_injection") is False

    server.stop()


def test_question_bridge_multi_questions_and_stop_continuation(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("ag_attention_bridge.ipc.server.SYNTHETIC_FALLBACK_ENABLED", True)
    socket_path = tmp_path / "test-q-multi.sock"
    queue = RequestQueue()
    sessions = SessionStore()
    injections = PendingInjectionStore()

    server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
    assert server.start() is True

    client = IpcClient(socket_path=socket_path)
    client_result = {}

    def run_pre_tool():
        msg = IpcMessage(
            type=MessageType.SUBMIT_REQUEST,
            conversation_id="conv-q-multi",
            payload={
                "request_id": "q-req-multi",
                "toolCall": {
                    "name": "ask_question",
                    "args": {
                        "questions": [
                            {"question": "Framework?", "options": ["React", "Vue"]},
                            {
                                "question": "Features?",
                                "options": ["API", "Database"],
                                "is_multi_select": True,
                            },
                        ]
                    },
                },
            },
        )
        client_result["resp"] = client.send_and_wait(msg, timeout=5.0)

    t = threading.Thread(target=run_pre_tool)
    t.start()

    assert _process_events_until(lambda: queue.count() == 1)

    # Resolve with answers to both questions
    server.resolve_request(
        "q-req-multi",
        [
            {"question": "Framework?", "selected": ["Vue"]},
            {"question": "Features?", "selected": ["API", "Database"]},
        ],
    )
    _process_events_until(lambda: bool(client_result.get("resp")), max_iters=30)
    t.join(timeout=2.0)

    # Check Stop hook continuation while answer is pending
    stop_msg = IpcMessage(
        type=MessageType.CHECK_STOP,
        conversation_id="conv-q-multi",
    )
    stop_resp = _client_send(client, stop_msg, timeout=2.0)
    assert stop_resp is not None
    assert stop_resp["data"].get("decision") == "continue"

    # PreInvocation fetches and consumes
    pre_inv_msg = IpcMessage(
        type=MessageType.GET_PENDING_INJECTION,
        conversation_id="conv-q-multi",
    )
    pre_inv_resp = _client_send(client, pre_inv_msg, timeout=2.0)
    assert pre_inv_resp is not None
    user_msg = pre_inv_resp["data"]["injectSteps"][0]["userMessage"]
    assert "1. Framework?" in user_msg
    assert "Answer: Vue" in user_msg
    assert "2. Features?" in user_msg
    assert "- API" in user_msg
    assert "- Database" in user_msg

    # Now Stop hook returns empty dict (no unconsumed answer)
    stop_resp2 = _client_send(client, stop_msg, timeout=2.0)
    assert stop_resp2 is not None
    assert stop_resp2["data"].get("decision") is None

    server.stop()
