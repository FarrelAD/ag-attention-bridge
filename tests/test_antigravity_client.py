"""Unit tests for Antigravity ConnectRPC Client, security enforcement, payload building, and error handling."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import pytest

from ag_attention_bridge.antigravity.client import AntigravityClient
from ag_attention_bridge.antigravity.errors import (
    InteractionStaleError,
    InteractionSubmissionError,
    SecurityValidationError,
    ServerConnectionError,
)
from ag_attention_bridge.antigravity.models import (
    AntigravityServer,
    PermissionScope,
    QuestionEntry,
    QuestionOption,
)


@pytest.fixture
def mock_server():
    return AntigravityServer(
        pid=1234,
        workspace_id="test_workspace",
        https_port=40753,
        csrf_token="test-csrf-token-1234",
    )


def test_security_loopback_enforcement(mock_server):
    """Verify client rejects non-loopback destinations."""
    # Localhost and 127.0.0.1 should pass
    client_local = AntigravityClient(mock_server)
    assert client_local.server.https_port == 40753

    # Remote host must be rejected
    class RemoteServer(AntigravityServer):
        @property
        def base_url(self) -> str:
            return "https://api.external.com:443"

    remote_server = RemoteServer(
        pid=1235,
        workspace_id="remote",
        https_port=443,
        csrf_token="tok",
    )

    with pytest.raises(SecurityValidationError):
        AntigravityClient(remote_server)


def test_ask_question_payload_construction():
    """Verify exact AskQuestionInteraction payload structure."""
    options = [
        QuestionOption(id="opt-a", text="Option A"),
        QuestionOption(id="opt-b", text="Option B"),
    ]
    entry_single = QuestionEntry(
        question="Which frontend framework?",
        options=options,
        is_multi_select=False,
        selected_option_ids=["opt-b"],
        write_in_response="",
        skipped=False,
    )

    payload = AntigravityClient.build_ask_question_payload(
        trajectory_id="traj-test-123",
        step_index=42,
        responses=[entry_single],
    )

    assert payload["trajectoryId"] == "traj-test-123"
    assert payload["stepIndex"] == 42
    assert "askQuestion" in payload
    ask_q = payload["askQuestion"]
    assert ask_q["cancelled"] is False
    assert len(ask_q["responses"]) == 1

    resp_0 = ask_q["responses"][0]
    assert resp_0["question"] == "Which frontend framework?"
    assert resp_0["isMultiSelect"] is False
    assert resp_0["selectedOptionIds"] == ["opt-b"]
    assert resp_0["writeInResponse"] == ""
    assert resp_0["skipped"] is False
    assert len(resp_0["options"]) == 2
    assert resp_0["options"][0] == {"id": "opt-a", "text": "Option A"}


def test_ask_question_multi_select_and_write_in():
    """Verify multi-select and write-in payload construction."""
    options = [
        QuestionOption(id="1", text="TypeScript"),
        QuestionOption(id="2", text="Python"),
        QuestionOption(id="3", text="Rust"),
    ]
    entry_multi = QuestionEntry(
        question="Which languages?",
        options=options,
        is_multi_select=True,
        selected_option_ids=["1", "3"],
        write_in_response="Go",
        skipped=False,
    )

    payload = AntigravityClient.build_ask_question_payload("t-1", 5, [entry_multi])
    r = payload["askQuestion"]["responses"][0]
    assert r["isMultiSelect"] is True
    assert r["selectedOptionIds"] == ["1", "3"]
    assert r["writeInResponse"] == "Go"


def test_permission_payload_construction():
    """Verify PermissionInteraction payload structure for Allow and Deny."""
    # 1. Allow Once
    p_allow = AntigravityClient.build_permission_payload(
        trajectory_id="t-perm",
        step_index=10,
        allow=True,
        scope=PermissionScope.PERMISSION_SCOPE_ONCE,
    )
    assert p_allow["trajectoryId"] == "t-perm"
    assert p_allow["stepIndex"] == 10
    assert p_allow["permission"] == {
        "allow": True,
        "scope": "PERMISSION_SCOPE_ONCE",
    }

    # 2. Allow Conversation
    p_conv = AntigravityClient.build_permission_payload(
        trajectory_id="t-perm",
        step_index=11,
        allow=True,
        scope=PermissionScope.PERMISSION_SCOPE_CONVERSATION,
    )
    assert p_conv["permission"]["scope"] == "PERMISSION_SCOPE_CONVERSATION"

    # 3. Deny with user instruction
    p_deny = AntigravityClient.build_permission_payload(
        trajectory_id="t-perm",
        step_index=12,
        allow=False,
        scope=PermissionScope.PERMISSION_SCOPE_ONCE,
        user_deny_instruction="User rejected command",
    )
    assert p_deny["permission"]["allow"] is False
    assert p_deny["permission"]["userDenyInstruction"] == "User rejected command"


def test_call_rpc_success(mock_server, monkeypatch):
    """Test RPC call execution, header injection, and response parsing."""
    client = AntigravityClient(mock_server)

    captured_req = {}

    class MockResponse:
        def __init__(self):
            self.data = json.dumps({"status": "success", "result": 123}).encode("utf-8")
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, *args, **kwargs):
        captured_req["url"] = req.full_url
        captured_req["headers"] = dict(req.headers)
        captured_req["data"] = json.loads(req.data.decode("utf-8"))
        return MockResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = client.call_rpc("Heartbeat", {"test": "data"})
    assert res == {"status": "success", "result": 123}
    assert "Heartbeat" in captured_req["url"]
    assert captured_req["headers"]["X-codeium-csrf-token"] == "test-csrf-token-1234"
    assert captured_req["headers"]["Content-type"] == "application/json"
    assert captured_req["data"] == {"test": "data"}


def test_stale_interaction_error_detection(mock_server, monkeypatch):
    """Verify HTTP error with 'input not registered' raises InteractionStaleError."""
    client = AntigravityClient(mock_server)

    def mock_urlopen_stale(req, *args, **kwargs):
        fp = io.BytesIO(b'{"error": "input not registered for step 15"}')
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {}, fp
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_stale)

    with pytest.raises(InteractionStaleError) as exc_info:
        client.handle_cascade_user_interaction("casc-1", {"test": 1})
    assert "stale" in str(exc_info.value).lower()


def test_find_waiting_interaction_with_retry(mock_server, monkeypatch):
    """Verify bounded retry when step is not immediately WAITING on first check."""
    client = AntigravityClient(mock_server)

    call_count = 0

    def mock_get_trajectory(cascade_id, disable_rehydration=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: step is still running
            return {
                "trajectory": {
                    "trajectoryId": "t-retry-1",
                    "steps": [{"status": "CORTEX_STEP_STATUS_RUNNING"}],
                }
            }
        else:
            # Second call: step transitioned to WAITING
            return {
                "trajectory": {
                    "trajectoryId": "t-retry-1",
                    "steps": [
                        {"status": "CORTEX_STEP_STATUS_RUNNING"},
                        {"status": "CORTEX_STEP_STATUS_WAITING", "type": "ASK_QUESTION"},
                    ],
                }
            }

    monkeypatch.setattr(client, "get_cascade_trajectory", mock_get_trajectory)

    result = client.find_waiting_interaction(
        "casc-1",
        max_retries=3,
        retry_delays=(0.01, 0.01),
    )
    assert result is not None
    traj_id, step_idx, step_data = result
    assert traj_id == "t-retry-1"
    assert step_idx == 1
    assert step_data["type"] == "ASK_QUESTION"
    assert call_count == 2
