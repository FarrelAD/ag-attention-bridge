"""IPC protocol definitions and message serialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from typing import Any
import uuid

PROTOCOL_VERSION = "1.0"


class MessageType(str, Enum):
    SUBMIT_REQUEST = "SUBMIT_REQUEST"
    RESOLVE_REQUEST = "RESOLVE_REQUEST"
    GET_QUEUE = "GET_QUEUE"
    DISMISS_REQUEST = "DISMISS_REQUEST"
    NOTIFY_EVENT = "NOTIFY_EVENT"
    GET_PENDING_INJECTION = "GET_PENDING_INJECTION"
    CHECK_STOP = "CHECK_STOP"
    ACK = "ACK"
    ERROR = "ERROR"



@dataclass
class IpcMessage:
    type: MessageType
    conversation_id: str | None = None
    request_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "msg_id": self.msg_id,
            "type": self.type.value if isinstance(self.type, MessageType) else str(self.type),
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "payload": self.payload,
        }


@dataclass
class IpcResponse:
    reply_to: str
    status: str = "ok"  # "ok" or "error"
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    version: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "reply_to": self.reply_to,
            "status": self.status,
            "data": self.data,
            "error": self.error,
        }


def encode_payload(data: dict[str, Any] | IpcMessage | IpcResponse) -> bytes:
    """Serialize a message or dict to newline-terminated JSON bytes."""
    if hasattr(data, "to_dict"):
        obj = data.to_dict()
    else:
        obj = data
    return json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"


def decode_payload(line: str | bytes) -> dict[str, Any]:
    """Parse a single line of JSON into a dict."""
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    line = line.strip()
    if not line:
        raise ValueError("Empty message received")
    return json.loads(line)
