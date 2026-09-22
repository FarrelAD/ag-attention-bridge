"""ConnectRPC client for communicating directly with Antigravity LanguageServerService."""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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
)

logger = logging.getLogger("ag_attention_bridge.antigravity.client")

# Optional path to local self-signed certificate bundled with Antigravity IDE
BUNDLED_CERT_CANDIDATES = [
    Path(
        "/home/mashupsoat/development/clones/Antigravity IDE/resources/app/extensions/antigravity/dist/languageServer/cert.pem"
    ),
    Path.home() / ".config/antigravity-ide/cert.pem",
]


class AntigravityClient:
    """HTTP/ConnectRPC client communicating over localhost HTTPS with LanguageServerService."""

    def __init__(
        self,
        server: AntigravityServer,
        timeout: float = 10.0,
    ) -> None:
        self.server = server
        self.timeout = timeout
        self._validate_security(server)
        self._ssl_context = self._create_ssl_context()

    def _validate_security(self, server: AntigravityServer) -> None:
        """Enforce strict security: only 127.0.0.1 or localhost destinations are permitted."""
        parsed = urllib.parse.urlparse(server.base_url)
        host = parsed.hostname
        if host not in ("127.0.0.1", "localhost"):
            raise SecurityValidationError(
                f"Target host '{host}' is prohibited. Only localhost is allowed."
            )

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create TLS context tailored for the language server's self-signed certificate."""
        for cert_path in BUNDLED_CERT_CANDIDATES:
            if cert_path.exists():
                try:
                    ctx = ssl.create_default_context(cafile=str(cert_path))
                    ctx.check_hostname = False
                    return ctx
                except Exception as e:
                    logger.warning("Could not load cert from %s: %s", cert_path, e)

        # Fallback for loopback localhost connection
        ctx = ssl._create_unverified_context()
        ctx.check_hostname = False
        return ctx

    def call_rpc(self, method: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a unary ConnectRPC call against LanguageServerService."""
        url = f"{self.server.base_url}/exa.language_server_pb.LanguageServerService/{method}"
        payload_bytes = json.dumps(data or {}).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "x-codeium-csrf-token": self.server.csrf_token,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                req, context=self._ssl_context, timeout=self.timeout
            ) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {}
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.warning("RPC %s failed with HTTP %d: %s", method, e.code, body)
            # Detect stale interaction signals from Go language server
            if (
                "input not registered" in body
                or "run state not found" in body
                or "step not found" in body
            ):
                raise InteractionStaleError(f"Interaction is stale: {body}") from e
            raise InteractionSubmissionError(
                f"RPC {method} failed with code {e.code}: {body}"
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.error("Connection error to %s: %s", url, e)
            raise ServerConnectionError(f"Failed to connect to Language Server: {e}") from e

    def heartbeat(self) -> dict[str, Any]:
        """Verify server responsiveness."""
        return self.call_rpc("Heartbeat")

    def get_cascade_trajectory(
        self, cascade_id: str, disable_rehydration: bool = False
    ) -> dict[str, Any]:
        """Retrieve full trajectory for a conversation."""
        return self.call_rpc(
            "GetCascadeTrajectory",
            {
                "cascadeId": cascade_id,
                "disableRehydration": disable_rehydration,
            },
        )

    def get_cascade_trajectory_steps(
        self, cascade_id: str, step_offset: int = 0
    ) -> list[dict[str, Any]]:
        """Retrieve slice of steps starting from step_offset."""
        res = self.call_rpc(
            "GetCascadeTrajectorySteps",
            {
                "cascadeId": cascade_id,
                "stepOffset": step_offset,
            },
        )
        return res.get("steps", [])

    def search_conversations(self, query: str = "") -> list[dict[str, Any]]:
        """List active and historical conversations in this workspace."""
        res = self.call_rpc("SearchConversations", {"query": query})
        return res.get("results", [])

    def handle_cascade_user_interaction(
        self, cascade_id: str, interaction: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit native user interaction response directly to Antigravity."""
        return self.call_rpc(
            "HandleCascadeUserInteraction",
            {
                "cascadeId": cascade_id,
                "interaction": interaction,
            },
        )

    def find_waiting_interaction(
        self,
        cascade_id: str,
        max_retries: int = 10,
        retry_delays: tuple[float, ...] = (0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.2, 1.5, 2.0),
    ) -> tuple[str, int, dict[str, Any]] | None:
        """Query trajectory and locate any active step with status == WAITING.

        Implements bounded progressive retries (up to ~7.5s) to handle latency
        between observation hook completion and language server creating the WAITING step.
        """
        import time

        for attempt in range(max_retries):
            try:
                traj_resp = self.get_cascade_trajectory(cascade_id)
                traj = traj_resp.get("trajectory", {})
                trajectory_id = traj.get("trajectoryId", "")
                steps = traj.get("steps", [])

                # Search in reverse for the active uncompleted step awaiting user interaction.
                # In Antigravity, an interaction step (e.g. ASK_QUESTION or RUN_COMMAND) has
                # requestedInteraction and has NOT yet been fulfilled (completedInteractions is absent/empty).
                for idx in reversed(range(len(steps))):
                    step = steps[idx]
                    status = str(step.get("status", ""))
                    has_completed = bool(step.get("completedInteractions"))
                    if has_completed:
                        # Skip steps that have already been answered/completed
                        continue

                    has_requested = (
                        "requestedInteraction" in step or "requested_interaction" in step
                    )
                    step_type = str(step.get("type", ""))

                    # 1. Match active uncompleted step with requestedInteraction (authoritative)
                    if has_requested:
                        from ag_attention_bridge.config import log_native_diagnostic

                        log_native_diagnostic(
                            "WAITING_STEP_FOUND",
                            conversation_id=cascade_id,
                            trajectory_id=trajectory_id,
                            step_index=idx,
                            extra=f"attempt={attempt + 1} (requestedInteraction present, type={step_type})",
                        )
                        return trajectory_id, idx, step

                    # 2. Match active uncompleted step in WAITING status (e.g. permission prompts)
                    if "WAITING" in status:
                        from ag_attention_bridge.config import log_native_diagnostic

                        log_native_diagnostic(
                            "WAITING_STEP_FOUND",
                            conversation_id=cascade_id,
                            trajectory_id=trajectory_id,
                            step_index=idx,
                            extra=f"attempt={attempt + 1} (status={status}, type={step_type})",
                        )
                        return trajectory_id, idx, step
            except Exception as e:
                logger.debug("Attempt %d checking waiting interaction failed: %s", attempt + 1, e)

            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])

        return None

    @staticmethod
    def build_ask_question_payload(
        trajectory_id: str,
        step_index: int,
        responses: list[QuestionEntry],
        cancelled: bool = False,
    ) -> dict[str, Any]:
        """Build native AskQuestionInteraction payload for HandleCascadeUserInteraction."""
        return {
            "trajectoryId": trajectory_id,
            "stepIndex": step_index,
            "askQuestion": {
                "responses": [r.to_dict() for r in responses],
                "cancelled": cancelled,
            },
        }

    @staticmethod
    def build_permission_payload(
        trajectory_id: str,
        step_index: int,
        allow: bool,
        scope: PermissionScope = PermissionScope.PERMISSION_SCOPE_ONCE,
        user_deny_instruction: str = "",
    ) -> dict[str, Any]:
        """Build native PermissionInteraction payload for HandleCascadeUserInteraction."""
        perm_dict: dict[str, Any] = {
            "allow": allow,
            "scope": scope.value if isinstance(scope, PermissionScope) else str(scope),
        }
        if not allow and user_deny_instruction:
            perm_dict["userDenyInstruction"] = user_deny_instruction

        return {
            "trajectoryId": trajectory_id,
            "stepIndex": step_index,
            "permission": perm_dict,
        }
