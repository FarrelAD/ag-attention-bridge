"""Unit tests for IPC protocol serialization and message schemas."""

import pytest

from ag_attention_bridge.ipc.protocol import (
    IpcMessage,
    IpcResponse,
    MessageType,
    decode_payload,
    encode_payload,
)


def test_encode_decode_ipc_message():
    msg = IpcMessage(
        type=MessageType.SUBMIT_REQUEST,
        conversation_id="conv-123",
        request_id="req-456",
        payload={"action": "test", "params": [1, 2, 3]},
    )

    encoded = encode_payload(msg)
    assert encoded.endswith(b"\n")

    decoded = decode_payload(encoded)
    assert decoded["version"] == "1.0"
    assert decoded["type"] == "SUBMIT_REQUEST"
    assert decoded["conversation_id"] == "conv-123"
    assert decoded["request_id"] == "req-456"
    assert decoded["payload"]["action"] == "test"
    assert decoded["payload"]["params"] == [1, 2, 3]


def test_encode_decode_ipc_response():
    resp = IpcResponse(
        reply_to="msg-uuid-1",
        status="ok",
        data={"decision": "allow"},
    )

    encoded = encode_payload(resp)
    assert encoded.endswith(b"\n")

    decoded = decode_payload(encoded)
    assert decoded["version"] == "1.0"
    assert decoded["reply_to"] == "msg-uuid-1"
    assert decoded["status"] == "ok"
    assert decoded["data"]["decision"] == "allow"
    assert decoded["error"] is None


def test_decode_invalid_input():
    with pytest.raises(ValueError):
        decode_payload("")

    with pytest.raises(ValueError):
        decode_payload("   \n\t  ")

    with pytest.raises(Exception):
        decode_payload(b"NOT_JSON\n")
