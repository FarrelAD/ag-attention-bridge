"""End-to-end integration test verifying the native Antigravity interaction pathway."""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from ag_attention_bridge.antigravity.client import AntigravityClient
from ag_attention_bridge.antigravity.interaction_resolver import InteractionResolver
from ag_attention_bridge.antigravity.models import (
    AntigravityServer,
    SubmissionState,
)
from ag_attention_bridge.domain.models import (
    InteractionOption,
    InteractionRequest,
    QuestionItem,
    RequestType,
)
from ag_attention_bridge.hooks.adapter import handle_hook
from ag_attention_bridge.ipc.client import IpcClient
from ag_attention_bridge.ipc.server import IpcServer
from ag_attention_bridge.state.store import PendingInjectionStore, RequestQueue, SessionStore
from ag_attention_bridge.ui.main_dialog import InteractionModal


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


def test_e2e_native_ask_question_flow(qapp, tmp_path, monkeypatch):
    """Verify entire native flow for ask_question without synthetic userMessage turns."""
    socket_path = tmp_path / "native_e2e.sock"
    queue = RequestQueue()
    sessions = SessionStore()
    injections = PendingInjectionStore()

    # Mock RPC client and discovery
    rpc_calls = []

    class MockConnectRpcClient:
        def __init__(self, server):
            self.server = server

        def build_ask_question_payload(self, trajectory_id, step_index, responses, cancelled=False):
            return AntigravityClient.build_ask_question_payload(
                trajectory_id, step_index, responses, cancelled
            )

        def handle_cascade_user_interaction(self, cascade_id, payload):
            rpc_calls.append((cascade_id, payload))
            return {"status": "ok"}

        def find_waiting_interaction(self, cascade_id, max_retries=5, retry_delays=None):
            return (
                "traj-e2e-123",
                42,
                {
                    "status": "CORTEX_STEP_STATUS_WAITING",
                    "type": "CORTEX_STEP_TYPE_ASK_QUESTION",
                    "askQuestion": {
                        "questions": [
                            {
                                "question": "Which database do you prefer?",
                                "options": [
                                    {"id": "opt-1", "text": "PostgreSQL"},
                                    {"id": "opt-2", "text": "SQLite"},
                                ],
                            }
                        ]
                    },
                },
            )

    mock_server = AntigravityServer(
        pid=123, workspace_id="ws_e2e", https_port=4000, csrf_token="tok"
    )

    class MockDiscovery:
        def discover_servers(self, force=False):
            return [mock_server]

        def find_server_for_workspace(self, path):
            return mock_server

    resolver = InteractionResolver(discovery=MockDiscovery())
    resolver._client_cache[123] = MockConnectRpcClient(mock_server)

    server = IpcServer(
        queue, sessions, injections=injections, socket_path=socket_path, resolver=resolver
    )
    assert server.start() is True

    modal = InteractionModal()
    modal.set_resolver(resolver)

    # 1. Antigravity emits PreToolUse hook for ask_question
    raw_payload = {
        "conversationId": "cascade-e2e-1",
        "workspacePaths": ["/home/user/project"],
        "stepIdx": 42,
        "toolCall": {
            "name": "ask_question",
            "args": {
                "questions": [
                    {
                        "question": "Which database do you prefer?",
                        "options": [
                            {"id": "opt-1", "label": "PostgreSQL"},
                            {"id": "opt-2", "label": "SQLite"},
                        ],
                    }
                ]
            },
        },
    }

    client = IpcClient(socket_path=socket_path)

    # Ensure synthetic fallback is disabled (default)
    monkeypatch.setenv("AG_ATTENTION_SYNTHETIC_FALLBACK", "0")

    hook_res = {}

    def _run_hook():
        hook_resp, hook_code = handle_hook(
            json.dumps(raw_payload),
            "PreToolUse",
            ipc_client=client,
            auto_start=False,
        )
        hook_res["resp"] = hook_resp
        hook_res["code"] = hook_code

    t = threading.Thread(target=_run_hook)
    t.start()

    # 2. Wait for daemon to enqueue request and resolve waiting step
    assert _process_events_until(lambda: queue.count() == 1)
    t.join(timeout=2.0)

    # Critical Assertion: Hook MUST NOT deny ask_question! It must return allow observation hook!
    assert hook_res["code"] == 0
    assert hook_res["resp"]["decision"] == "allow"
    assert "Ag Attention Bridge observation hook" in hook_res["resp"]["reason"]

    req = queue.get_active()
    assert req is not None
    assert req.conversation_id == "cascade-e2e-1"

    # 3. Present in Modal
    modal.load_request(req)
    assert modal.isVisible() is False  # Offscreen
    assert modal.lbl_project_badge.text() == "📁 project"
    assert "Project: project" in modal.lbl_subtitle.text()
    assert "cascade-" in modal.lbl_subtitle.text()

    # Wait for background native resolution to reach NATIVE_WAITING_READY
    from ag_attention_bridge.antigravity.models import InteractionState

    assert _process_events_until(lambda: req.state == InteractionState.NATIVE_WAITING_READY)
    assert req.trajectory_id == "traj-e2e-123"
    assert req.step_index == 42

    # 4. User selects option [2] (SQLite) and presses Enter
    # Wait for initial load debounce
    time.sleep(0.25)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    key_2 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier, "2")
    modal.keyPressEvent(key_2)

    # Press Enter
    key_enter = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
    )
    modal.keyPressEvent(key_enter)

    # 5. Verify HandleCascadeUserInteraction was called with exact native options!
    assert len(rpc_calls) == 1
    call_cascade_id, call_payload = rpc_calls[0]
    assert call_cascade_id == "cascade-e2e-1"
    assert call_payload["trajectoryId"] == "traj-e2e-123"
    assert call_payload["stepIndex"] == 42

    resp_0 = call_payload["askQuestion"]["responses"][0]
    assert resp_0["question"] == "Which database do you prefer?"
    assert resp_0["selectedOptionIds"] == ["opt-2"]
    assert resp_0["writeInResponse"] == ""

    # 6. Verify submission state is SUBMITTED and duplicate submit is blocked
    assert resolver.get_state("cascade-e2e-1", "traj-e2e-123", 42) == SubmissionState.SUBMITTED
    assert resolver.submit_question_response("cascade-e2e-1", "traj-e2e-123", 42, []) is False

    # 7. Verify NO synthetic injection exists in PendingInjectionStore
    assert injections.get_pending("cascade-e2e-1") is None

    server.stop()


def test_enter_guard_and_authoritative_option_ids(qapp):
    """Verify Enter guard blocks submit until NATIVE_WAITING_READY and uses native option IDs."""
    from ag_attention_bridge.antigravity.models import InteractionState

    rpc_calls = []

    class MockConnectRpcClient:
        def __init__(self):
            pass

        def build_ask_question_payload(self, trajectory_id, step_index, responses, cancelled=False):
            return AntigravityClient.build_ask_question_payload(
                trajectory_id, step_index, responses, cancelled
            )

        def handle_cascade_user_interaction(self, cascade_id, payload):
            rpc_calls.append((cascade_id, payload))
            return {"status": "ok"}

        def find_waiting_interaction(self, cascade_id, max_retries=5, retry_delays=None):
            # Authoritative server-side option IDs (e.g. "backend-go-456")
            return (
                "traj-guard-1",
                10,
                {
                    "status": "CORTEX_STEP_STATUS_WAITING",
                    "type": "CORTEX_STEP_TYPE_ASK_QUESTION",
                    "askQuestion": {
                        "questions": [
                            {
                                "question": "Which backend?",
                                "options": [
                                    {"id": "backend-fastapi-123", "text": "FastAPI"},
                                    {"id": "backend-go-456", "text": "Go"},
                                    {"id": "backend-rust-789", "text": "Rust"},
                                ],
                            }
                        ]
                    },
                },
            )

    mock_server = AntigravityServer(
        pid=999, workspace_id="ws_guard", https_port=4000, csrf_token="tok"
    )

    class MockDiscovery:
        def discover_servers(self, force=False):
            return [mock_server]

        def find_server_for_workspace(self, path):
            return mock_server

    resolver = InteractionResolver(discovery=MockDiscovery())
    resolver._client_cache[999] = MockConnectRpcClient()

    modal = InteractionModal()
    modal.set_resolver(resolver)

    # Trigger request with raw hook arguments (IDs are different/placeholder "0", "1", "2")
    req = InteractionRequest(
        request_id="req-guard-test",
        conversation_id="cascade-guard-1",
        request_type=RequestType.QUESTION,
        title="Which backend?",
        body="Which backend?",
        questions=[
            QuestionItem(
                id="0",
                question="Which backend?",
                options=[
                    InteractionOption(id="placeholder-0", label="FastAPI"),
                    InteractionOption(id="placeholder-1", label="Go"),
                    InteractionOption(id="placeholder-2", label="Rust"),
                ],
            )
        ],
        state=InteractionState.RESOLVING_NATIVE_STEP,
    )

    # 1. Guard check: submit while RESOLVING_NATIVE_STEP must be ignored!
    modal.current_request = req
    modal.submit_current_interaction(action_type="submit")
    assert len(rpc_calls) == 0  # Blocked by Enter guard!

    # 2. Now load request properly to trigger background resolution
    modal.load_request(req)
    assert _process_events_until(lambda: req.state == InteractionState.NATIVE_WAITING_READY)
    assert req.state == InteractionState.NATIVE_WAITING_READY
    assert req.trajectory_id == "traj-guard-1"
    assert req.step_index == 10

    # 3. Select Go (option 2) and press Enter
    modal._content_widget._sections[0].select_by_number(2)
    modal.submit_current_interaction(action_type="submit")

    # 4. Verify RPC call received the authoritative native option ID "backend-go-456"
    assert len(rpc_calls) == 1
    call_cascade_id, call_payload = rpc_calls[0]
    assert call_cascade_id == "cascade-guard-1"
    assert call_payload["trajectoryId"] == "traj-guard-1"
    assert call_payload["stepIndex"] == 10

    resp_0 = call_payload["askQuestion"]["responses"][0]
    assert resp_0["question"] == "Which backend?"
    assert resp_0["selectedOptionIds"] == ["backend-go-456"]
    assert req.state == InteractionState.SUBMITTED
