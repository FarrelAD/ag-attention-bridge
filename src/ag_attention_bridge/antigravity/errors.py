"""Custom exceptions for Antigravity native interaction bridge."""

from __future__ import annotations


class AntigravityError(Exception):
    """Base exception for all Antigravity bridge operations."""


class ServerNotFoundError(AntigravityError):
    """Raised when no matching Antigravity Language Server process is found."""


class ServerConnectionError(AntigravityError):
    """Raised when communication with Language Server localhost HTTPS fails."""


class InteractionStaleError(AntigravityError):
    """Raised when an interaction is no longer waiting or already resolved."""


class InteractionSubmissionError(AntigravityError):
    """Raised when submitting an interaction fails."""


class SecurityValidationError(AntigravityError):
    """Raised when a security constraint is violated (e.g. non-localhost target)."""
