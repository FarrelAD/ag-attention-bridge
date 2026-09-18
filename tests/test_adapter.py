"""Tests for hook adapter and observation logging."""

import json
import time
from pathlib import Path

from ag_attention_bridge.hooks.adapter import (
    detect_event_type,
    generate_default_response,
    handle_hook,
)
from ag_attention_bridge.ipc.client import IpcClient
import pytest


@pytest.fixture(autouse=True)
def isolate_adapter_unit_tests(monkeypatch, tmp_path):
    monkeypatch.setenv("AG_ATTENTION_NO_AUTOSTART", "1")
    monkeypatch.setattr(
        "ag_attention_bridge.hooks.adapter.GLOBAL_EVENTS_LOG_PATH",
        tmp_path / "events.jsonl",
    )
    # Ensure IpcClient does not hit any real system socket
    fake_sock = tmp_path / "isolated.sock"
    monkeypatch.setattr("ag_attention_bridge.hooks.adapter.IpcClient", lambda: IpcClient(socket_path=fake_sock))


def test_detect_event_type():
    assert detect_event_type({}, hint="CustomEvent") == "CustomEvent"
    assert detect_event_type({"toolCall": {"name": "ask_question"}}) == "PreToolUse"
    assert detect_event_type({"stepIdx": 2}) == "PostToolUse"
    assert detect_event_type({"invocationNum": 1}) == "Invocation"
    assert detect_event_type({"terminationReason": "model_stop"}) == "Stop"
    assert detect_event_type({}) == "Unknown"


def test_handle_hook_pre_tool_use_ask_question(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ag_attention_bridge.hooks.adapter.get_xdg_state_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "ag_attention_bridge.hooks.adapter.GLOBAL_EVENTS_LOG_PATH",
        tmp_path / "events.jsonl",
    )

    payload = {
        "conversationId": "conv-test-123",
        "workspacePaths": [str(tmp_path)],
        "transcriptPath": str(tmp_path / "transcript.jsonl"),
        "modelName": "gemini-test",
        "toolCall": {
            "name": "ask_question",
            "args": {
                "questions": [
                    {
                        "question": "Which database would you prefer?",
                        "options": ["PostgreSQL", "SQLite"],
                    }
                ]
            },
        },
        "stepIdx": 3,
    }

    raw_input = json.dumps(payload)
    start_time = time.perf_counter()
    response, code = handle_hook(raw_input)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    assert code == 0
    assert response["decision"] == "allow"
    assert "Ag Attention Bridge observation hook" in response["reason"]
    # Fast execution check
    assert elapsed_ms < 50

    # Verify log output
    log_file = tmp_path / "events.jsonl"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["event_type"] == "PreToolUse"
    assert record["conversation_id"] == "conv-test-123"
    assert record["payload"]["toolCall"]["name"] == "ask_question"
    assert record["response"]["decision"] == "allow"


def test_handle_hook_pre_tool_use_ask_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ag_attention_bridge.hooks.adapter.GLOBAL_EVENTS_LOG_PATH",
        tmp_path / "events.jsonl",
    )

    payload = {
        "conversationId": "conv-perm-456",
        "workspacePaths": [str(tmp_path)],
        "toolCall": {
            "name": "ask_permission",
            "args": {
                "action": "run_command",
                "target": "npm run build",
                "reason": "Build package",
            },
        },
    }

    response, code = handle_hook(json.dumps(payload))
    assert code == 0
    assert response["decision"] == "allow"
    assert "Ag Attention Bridge observation hook" in response["reason"]


def test_handle_hook_post_invocation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ag_attention_bridge.hooks.adapter.GLOBAL_EVENTS_LOG_PATH",
        tmp_path / "events.jsonl",
    )

    payload = {
        "conversationId": "conv-post-inv",
        "workspacePaths": [str(tmp_path)],
        "invocationNum": 2,
        "initialNumSteps": 5,
    }

    response, code = handle_hook(json.dumps(payload), event_hint="PostInvocation")
    assert code == 0
    assert response == {}


def test_handle_hook_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ag_attention_bridge.hooks.adapter.GLOBAL_EVENTS_LOG_PATH",
        tmp_path / "events.jsonl",
    )

    payload = {
        "conversationId": "conv-stop",
        "workspacePaths": [str(tmp_path)],
        "executionNum": 1,
        "terminationReason": "model_stop",
        "fullyIdle": True,
    }

    response, code = handle_hook(json.dumps(payload))
    assert code == 0
    assert response == {}


def test_handle_hook_malformed_and_empty():
    res_empty, code_empty = handle_hook("")
    assert code_empty == 0
    assert res_empty == {}

    res_whitespace, code_ws = handle_hook("   \n\t  ")
    assert code_ws == 0
    assert res_whitespace == {}

    res_bad_json, code_bad = handle_hook("NOT_VALID_JSON{{{")
    assert code_bad == 0
    assert res_bad_json == {}
