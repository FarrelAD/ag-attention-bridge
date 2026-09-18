"""Domain models and value objects for Ag Attention Bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RequestType(str, Enum):
    QUESTION = "question"
    PERMISSION = "permission"


class RequestStatus(str, Enum):
    RECEIVED = "received"
    PENDING = "pending"
    PRESENTED = "presented"
    ANSWERED = "answered"
    CONSUMED = "consumed"


class ToolDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    FORCE_ASK = "force_ask"


@dataclass
class HookCommonContext:
    conversation_id: str
    workspace_paths: list[str] = field(default_factory=list)
    transcript_path: str | None = None
    artifact_directory_path: str | None = None
    model_name: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HookCommonContext:
        return cls(
            conversation_id=str(data.get("conversationId", "")),
            workspace_paths=[str(p) for p in data.get("workspacePaths", [])],
            transcript_path=data.get("transcriptPath"),
            artifact_directory_path=data.get("artifactDirectoryPath"),
            model_name=data.get("modelName"),
        )


@dataclass
class HookEventRecord:
    event_type: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    pid: int = 0
    context: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "pid": self.pid,
            "context": self.context,
            "payload": self.payload,
            "response": self.response,
        }


@dataclass
class InteractionOption:
    id: str
    label: str
    description: str | None = None


@dataclass
class QuestionItem:
    id: str
    question: str
    options: list[InteractionOption] = field(default_factory=list)
    multi_select: bool = False
    allow_custom_input: bool = True


class InjectionStatus(str, Enum):
    PENDING_INJECTION = "pending_injection"
    CONSUMED = "consumed"


@dataclass
class PendingAnswerItem:
    question: str
    selected: list[str] = field(default_factory=list)


@dataclass
class PendingInjection:
    conversation_id: str
    request_id: str
    status: InjectionStatus = InjectionStatus.PENDING_INJECTION
    items: list[PendingAnswerItem] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    continuation_count: int = 0


def format_injected_message(injection: PendingInjection) -> str:
    """Format user answers into a clean instruction message for PreInvocation (Phases 6, 7, 8)."""
    if not injection.items:
        return "The user acknowledged through Ag Attention Bridge. Continue execution."

    if len(injection.items) == 1:
        item = injection.items[0]
        if len(item.selected) == 1:
            ans_str = item.selected[0]
        elif len(item.selected) > 1:
            ans_str = "\n" + "\n".join(f"- {s}" for s in item.selected)
        else:
            ans_str = "None"

        return (
            f"The user answered the previous question through Ag Attention Bridge:\n\n"
            f"{item.question}\n"
            f"Answer: {ans_str}\n\n"
            f"Continue using this answer. Do not ask the same question again."
        )

    lines = ["The user answered through Ag Attention Bridge:\n"]
    for idx, item in enumerate(injection.items, 1):
        lines.append(f"{idx}. {item.question}")
        if len(item.selected) == 1:
            lines.append(f"   Answer: {item.selected[0]}\n")
        elif len(item.selected) > 1:
            lines.append("   Answer:")
            for s in item.selected:
                lines.append(f"   - {s}")
            lines.append("")
        else:
            lines.append("   Answer: None\n")

    lines.append("Continue using these answers.\nDo not repeat these questions.")
    return "\n".join(lines).strip()


@dataclass
class InteractionRequest:
    request_id: str
    conversation_id: str
    request_type: RequestType
    title: str
    body: str
    questions: list[QuestionItem] = field(default_factory=list)
    options: list[InteractionOption] = field(default_factory=list)
    multi_select: bool = False
    allow_custom_input: bool = True
    context_user_message: str | None = None
    context_agent_message: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: RequestStatus = RequestStatus.PENDING
    response_value: Any = None
    permission_overrides: list[str] = field(default_factory=list)
    trajectory_id: str | None = None
    step_index: int | None = None
    workspace_path: str | None = None
    model_name: str | None = None
    state: Any = None

    def __post_init__(self) -> None:
        if self.state is None:
            from ag_attention_bridge.antigravity.models import InteractionState
            self.state = InteractionState.HOOK_RECEIVED

    @property
    def interaction_state(self) -> Any:
        return self.state

    @interaction_state.setter
    def interaction_state(self, val: Any) -> None:
        self.state = val

