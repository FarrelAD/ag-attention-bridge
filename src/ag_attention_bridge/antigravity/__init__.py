"""Antigravity native interaction package for Ag Attention Bridge."""

from ag_attention_bridge.antigravity.client import AntigravityClient
from ag_attention_bridge.antigravity.discovery import AntigravityDiscovery
from ag_attention_bridge.antigravity.errors import (
    AntigravityError,
    InteractionStaleError,
    InteractionSubmissionError,
    SecurityValidationError,
    ServerConnectionError,
    ServerNotFoundError,
)
from ag_attention_bridge.antigravity.interaction_resolver import InteractionResolver
from ag_attention_bridge.antigravity.models import (
    AntigravityServer,
    InteractionType,
    PendingInteraction,
    PermissionScope,
    QuestionEntry,
    QuestionOption,
    SubmissionState,
)

__all__ = [
    "AntigravityClient",
    "AntigravityDiscovery",
    "AntigravityError",
    "AntigravityServer",
    "InteractionResolver",
    "InteractionStaleError",
    "InteractionSubmissionError",
    "InteractionType",
    "PendingInteraction",
    "PermissionScope",
    "QuestionEntry",
    "QuestionOption",
    "SecurityValidationError",
    "ServerConnectionError",
    "ServerNotFoundError",
    "SubmissionState",
]
