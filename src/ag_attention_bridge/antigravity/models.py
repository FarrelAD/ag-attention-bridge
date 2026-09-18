"""Domain models for Antigravity native RPC and process state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PermissionScope(str, Enum):
    """Native Antigravity permission scopes matching exa.cortex_pb.PermissionScope."""
    PERMISSION_SCOPE_UNSPECIFIED = "PERMISSION_SCOPE_UNSPECIFIED"
    PERMISSION_SCOPE_ONCE = "PERMISSION_SCOPE_ONCE"
    PERMISSION_SCOPE_CONVERSATION = "PERMISSION_SCOPE_CONVERSATION"
    PERMISSION_SCOPE_WORKSPACE = "PERMISSION_SCOPE_WORKSPACE"
    PERMISSION_SCOPE_GLOBAL = "PERMISSION_SCOPE_GLOBAL"
    PERMISSION_SCOPE_PROJECT = "PERMISSION_SCOPE_PROJECT"


class InteractionType(str, Enum):
    """Categorization of native Antigravity interaction types."""
    ASK_QUESTION = "ask_question"
    PERMISSION = "permission"
    RUN_COMMAND = "run_command"
    FILE_PERMISSION = "file_permission"
    APPROVAL = "approval_interaction"


class InteractionState(str, Enum):
    """Lifecycle state machine for native Antigravity interaction."""
    HOOK_RECEIVED = "HOOK_RECEIVED"
    RESOLVING_NATIVE_STEP = "RESOLVING_NATIVE_STEP"
    NATIVE_WAITING_READY = "NATIVE_WAITING_READY"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    STALE = "STALE"

    # Backward compatibility alias
    PENDING = "HOOK_RECEIVED"


# Backward compatibility alias
SubmissionState = InteractionState


@dataclass
class AntigravityServer:
    """Discovered Antigravity Language Server process metadata."""
    pid: int
    workspace_id: str
    https_port: int
    csrf_token: str
    lsp_port: int | None = None
    extension_server_port: int | None = None
    workspace_path: str | None = None

    @property
    def masked_csrf_token(self) -> str:
        """Return masked CSRF token safe for logging."""
        if not self.csrf_token:
            return "[EMPTY]"
        if len(self.csrf_token) <= 8:
            return "****"
        return f"{self.csrf_token[:4]}****{self.csrf_token[-4:]}"

    @property
    def base_url(self) -> str:
        """Localhost base URL for ConnectRPC."""
        return f"https://127.0.0.1:{self.https_port}"


@dataclass
class QuestionOption:
    """A selectable option in ask_question with native option ID."""
    id: str
    text: str


@dataclass
class QuestionEntry:
    """A single question item within ask_question."""
    question: str
    options: list[QuestionOption] = field(default_factory=list)
    is_multi_select: bool = False
    selected_option_ids: list[str] = field(default_factory=list)
    write_in_response: str = ""
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to native Antigravity AskQuestionEntry dictionary."""
        return {
            "question": self.question,
            "options": [{"id": opt.id, "text": opt.text} for opt in self.options],
            "isMultiSelect": self.is_multi_select,
            "selectedOptionIds": self.selected_option_ids,
            "writeInResponse": self.write_in_response,
            "skipped": self.skipped,
        }


@dataclass
class PendingInteraction:
    """Represents a live interaction waiting for user response."""
    cascade_id: str
    trajectory_id: str
    step_index: int
    interaction_type: InteractionType
    workspace_id: str | None = None
    questions: list[QuestionEntry] = field(default_factory=list)
    permission_action: str | None = None
    permission_target: str | None = None
    permission_reason: str | None = None
    state: InteractionState = InteractionState.HOOK_RECEIVED
    error_message: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def identity(self) -> tuple[str, str, int]:
        """Unique key for deduplication and idempotency."""
        return (self.cascade_id, self.trajectory_id, self.step_index)
