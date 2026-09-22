"""Explicit phase-by-phase verification tests for Ag Attention Bridge architecture."""

import json
import os
import threading
import time
from typing import Any

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from ag_attention_bridge.domain.models import (
    PendingAnswerItem,
    PendingInjection,
    RequestType,
    format_injected_message,
)
from ag_attention_bridge.hooks.adapter import handle_hook
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


def test_phase1_controlled_run_command_allow(qapp, tmp_path, monkeypatch):
    """Phase 1: PreToolUse for run_command returns decision: allow."""
    monkeypatch.setattr("ag_attention_bridge.hooks.adapter.SYNTHETIC_FALLBACK_ENABLED", True)
    socket_path = tmp_path / "phase1.sock"
    queue = RequestQueue()
    sessions = SessionStore()
    injections = PendingInjectionStore()
    server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
    assert server.start() is True

    client = IpcClient(socket_path=socket_path)
    raw_payload = {
        "conversationId": "conv-p1",
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "echo AG_BRIDGE_TEST"},
        },
    }

    resp_container = {}

    def _run_hook():
        # Handle hook directly using adapter
        resp, code = handle_hook(
            json.dumps(raw_payload), "PreToolUse", ipc_client=client, auto_start=False
        )
        resp_container["response"] = resp
        resp_container["code"] = code

    t = threading.Thread(target=_run_hook)
    t.start()

    assert _process_events_until(lambda: queue.count() == 1)
    req = queue.get_active()
    assert req is not None
    assert req.request_id is not None

    # Resolve Allow
    server.resolve_request(req.request_id, "allow")
    _process_events_until(lambda: "response" in resp_container)
    t.join(timeout=2.0)

    assert resp_container["code"] == 0
    resp = resp_container["response"]
    assert resp["decision"] == "allow"
    assert "command(echo AG_BRIDGE_TEST)" in resp["permissionOverrides"]

    server.stop()


def test_phase2_real_tools_interception(qapp, tmp_path):
    """Phase 2: Intercept write_to_file, replace_file_content, read_url_content."""
    socket_path = tmp_path / "phase2.sock"
    queue = RequestQueue()
    sessions = SessionStore()
    injections = PendingInjectionStore()
    server = IpcServer(queue, sessions, injections=injections, socket_path=socket_path)
    assert server.start() is True

    client = IpcClient(socket_path=socket_path)

    tools_to_test = [
        ("write_to_file", {"TargetFile": "/path/to/file.py", "Description": "Write file"}),
        ("replace_file_content", {"TargetFile": "/path/to/file.py", "Instruction": "Edit code"}),
        ("read_url_content", {"Url": "https://example.com", "Description": "Fetch docs"}),
    ]

    for tool_name, tool_args in tools_to_test:
        req_id = f"req-{tool_name}"
        msg = IpcMessage(
            type=MessageType.SUBMIT_REQUEST,
            conversation_id="conv-p2",
            payload={
                "request_id": req_id,
                "toolCall": {"name": tool_name, "args": tool_args},
            },
        )
        res_box: dict[str, Any] = {}

        def _send(m=msg, box=res_box):
            box["resp"] = client.send_and_wait(m, timeout=5.0)

        t = threading.Thread(target=_send)
        t.start()

        _process_events_until(lambda: queue.count() == 1)
        req = queue.get_active()
        assert req is not None
        assert req.request_type == RequestType.PERMISSION

        server.resolve_request(req_id, "allow")
        _process_events_until(lambda b=res_box: "resp" in b)
        t.join(timeout=2.0)

        assert res_box["resp"]["data"]["decision"] == "allow"

    server.stop()


def test_phase6_7_8_injected_message_formatting():
    """Phase 6, 7, 8: Injected message structure for single, multi, and freeform."""
    # 1. Single question
    inj1 = PendingInjection(
        conversation_id="c1",
        request_id="r1",
        items=[PendingAnswerItem(question="Framework?", selected=["Vue"])],
    )
    msg1 = format_injected_message(inj1)
    assert "The user answered the previous question through Ag Attention Bridge:" in msg1
    assert "Framework?" in msg1
    assert "Answer: Vue" in msg1
    assert "Continue using this answer." in msg1

    # 2. Multi questions
    inj2 = PendingInjection(
        conversation_id="c2",
        request_id="r2",
        items=[
            PendingAnswerItem(question="Framework?", selected=["Vue"]),
            PendingAnswerItem(question="Features?", selected=["API", "Database"]),
        ],
    )
    msg2 = format_injected_message(inj2)
    assert "1. Framework?" in msg2
    assert "Answer: Vue" in msg2
    assert "2. Features?" in msg2
    assert "- API" in msg2
    assert "- Database" in msg2

    # 3. Freeform write-in
    inj3 = PendingInjection(
        conversation_id="c3",
        request_id="r3",
        items=[PendingAnswerItem(question="Specify custom port:", selected=["8080"])],
    )
    msg3 = format_injected_message(inj3)
    assert "Specify custom port:" in msg3
    assert "Answer: 8080" in msg3


def test_phase9_stop_continuation_guard():
    """Phase 9: Stop continuation guard terminates after max iterations (3)."""
    store = PendingInjectionStore()
    inj = PendingInjection(
        conversation_id="conv-guard",
        request_id="req-guard",
        items=[PendingAnswerItem(question="Q", selected=["A"])],
    )
    store.store_pending(inj)

    # 1st, 2nd, 3rd checks return True
    assert store.should_stop_continue("conv-guard", max_continuations=3) is True
    assert store.should_stop_continue("conv-guard", max_continuations=3) is True
    assert store.should_stop_continue("conv-guard", max_continuations=3) is True

    # 4th check returns False to prevent infinite loop
    assert store.should_stop_continue("conv-guard", max_continuations=3) is False
