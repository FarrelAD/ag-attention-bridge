"""State management, SessionStore, and Interaction RequestQueue."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
from typing import Any, Callable

from ag_attention_bridge.domain.models import (
    InteractionOption,
    InteractionRequest,
    RequestStatus,
    RequestType,
)

logger = logging.getLogger("ag_attention_bridge.state")


@dataclass
class ConversationSession:
    conversation_id: str
    workspace_paths: list[str] = field(default_factory=list)
    transcript_path: str | None = None
    model_name: str | None = None
    created_at: str | None = None
    requests: list[str] = field(default_factory=list)  # request_ids


class RequestQueue:
    """In-memory FIFO queue for pending user interaction requests."""

    def __init__(
        self,
        on_count_changed: Callable[[int], None] | None = None,
        on_request_added: Callable[[InteractionRequest], None] | None = None,
    ) -> None:
        self._pending: list[InteractionRequest] = []
        self._all_requests: dict[str, InteractionRequest] = {}
        self._payload_fingerprints: set[str] = set()
        self._on_count_changed = on_count_changed
        self._on_request_added = on_request_added

    def _generate_fingerprint(self, req: InteractionRequest) -> str:
        """Create a deterministic fingerprint for request deduplication."""
        options_repr = [(opt.id, opt.label) for opt in req.options]
        raw = f"{req.conversation_id}:{req.request_type.value}:{req.title}:{req.body}:{options_repr}:{req.multi_select}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def enqueue(self, request: InteractionRequest) -> bool:
        """Add request to queue if not already present or duplicated.

        Returns True if enqueued as new, False if deduplicated.
        """
        if request.request_id in self._all_requests:
            logger.info("Request %s already exists in store", request.request_id)
            return False

        fp = self._generate_fingerprint(request)
        if fp in self._payload_fingerprints:
            logger.info("Request %s deduplicated (matching fingerprint)", request.request_id)
            return False

        self._payload_fingerprints.add(fp)
        self._all_requests[request.request_id] = request
        self._pending.append(request)

        logger.info("Enqueued request %s (queue size: %d)", request.request_id, len(self._pending))

        self._notify_count()
        if self._on_request_added:
            self._on_request_added(request)

        return True

    def get_active(self) -> InteractionRequest | None:
        """Return the current front-of-queue pending request without removing it."""
        for req in self._pending:
            if req.status in (RequestStatus.PENDING, RequestStatus.PRESENTED):
                return req
        return None

    def get_by_id(self, request_id: str) -> InteractionRequest | None:
        return self._all_requests.get(request_id)

    def get_pending_list(self) -> list[InteractionRequest]:
        return list(self._pending)

    def list_all(self) -> list[InteractionRequest]:
        """Return all historical and active requests."""
        return list(self._all_requests.values())

    def count(self) -> int:
        """Return number of unresolved pending requests."""
        return len(self._pending)

    def resolve(self, request_id: str, response_value: Any) -> InteractionRequest | None:
        """Record user answer/decision for a request. Request remains until consumed."""
        req = self._all_requests.get(request_id)
        if not req:
            logger.warning("Attempted to resolve unknown request %s", request_id)
            return None

        req.status = RequestStatus.ANSWERED
        req.response_value = response_value
        logger.info("Resolved request %s with response: %s", request_id, response_value)
        return req

    def consume(self, request_id: str) -> InteractionRequest | None:
        """Mark request as consumed after emission and remove from pending queue."""
        req = self._all_requests.get(request_id)
        if not req:
            return None

        req.status = RequestStatus.CONSUMED
        if req in self._pending:
            self._pending.remove(req)

        # Release fingerprint for future requests if needed
        fp = self._generate_fingerprint(req)
        self._payload_fingerprints.discard(fp)

        logger.info("Consumed request %s (remaining pending: %d)", request_id, len(self._pending))
        self._notify_count()
        return req

    def dismiss_to_tray(self, request_id: str) -> None:
        """Handle Esc or window close: leaves request pending in queue."""
        req = self._all_requests.get(request_id)
        if req and req in self._pending:
            logger.info("Request %s dismissed to tray, remains pending", request_id)
            # Retain in pending queue, keep count unchanged

    def _notify_count(self) -> None:
        if self._on_count_changed:
            self._on_count_changed(len(self._pending))


class SessionStore:
    """Manages active Antigravity conversations keyed by conversationId."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def get_or_create(
        self,
        conversation_id: str,
        workspace_paths: list[str] | None = None,
        model_name: str | None = None,
        transcript_path: str | None = None,
    ) -> ConversationSession:
        if conversation_id not in self._sessions:
            self._sessions[conversation_id] = ConversationSession(
                conversation_id=conversation_id,
                workspace_paths=workspace_paths or [],
                model_name=model_name,
                transcript_path=transcript_path,
            )
        else:
            session = self._sessions[conversation_id]
            if workspace_paths and not session.workspace_paths:
                session.workspace_paths = workspace_paths
            if model_name and not session.model_name:
                session.model_name = model_name
            if transcript_path and not session.transcript_path:
                session.transcript_path = transcript_path

        return self._sessions[conversation_id]

    def get(self, conversation_id: str) -> ConversationSession | None:
        return self._sessions.get(conversation_id)

    def attach_request(self, conversation_id: str, request_id: str) -> None:
        session = self.get_or_create(conversation_id)
        if request_id not in session.requests:
            session.requests.append(request_id)


class PendingInjectionStore:
    """Stores external user answers awaiting PreInvocation injection into Antigravity."""

    def __init__(self) -> None:
        # conversation_id -> list[PendingInjection]
        self._injections: dict[str, list[Any]] = {}

    def store_pending(self, injection: Any) -> None:
        conv_id = injection.conversation_id
        if conv_id not in self._injections:
            self._injections[conv_id] = []
        self._injections[conv_id].append(injection)
        logger.info("Stored pending injection for conversation %s (req %s)", conv_id, injection.request_id)

    def get_pending(self, conversation_id: str) -> Any | None:
        from ag_attention_bridge.domain.models import InjectionStatus
        for inj in self._injections.get(conversation_id, []):
            if inj.status == InjectionStatus.PENDING_INJECTION:
                return inj
        return None

    def consume_pending(self, conversation_id: str) -> Any | None:
        from ag_attention_bridge.domain.models import InjectionStatus
        inj = self.get_pending(conversation_id)
        if inj:
            inj.status = InjectionStatus.CONSUMED
            logger.info("Marked injection consumed for conversation %s (req %s)", conversation_id, inj.request_id)
            return inj
        return None

    def should_stop_continue(self, conversation_id: str, max_continuations: int = 3) -> bool:
        """Check if unconsumed answer is pending and within continuation guard limit."""
        inj = self.get_pending(conversation_id)
        if not inj:
            return False

        if inj.continuation_count < max_continuations:
            inj.continuation_count += 1
            logger.info(
                "Stop continue triggered for conversation %s (attempt %d/%d)",
                conversation_id,
                inj.continuation_count,
                max_continuations,
            )
            return True

        logger.warning(
            "Stop continuation limit reached (%d) for conversation %s; halting continuation loop",
            max_continuations,
            conversation_id,
        )
        return False

