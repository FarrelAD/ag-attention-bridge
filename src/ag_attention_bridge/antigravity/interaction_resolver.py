"""Unified submission controller and state machine for Antigravity native interactions."""

from __future__ import annotations

import logging
import threading
from typing import Any

from ag_attention_bridge.antigravity.client import AntigravityClient
from ag_attention_bridge.antigravity.discovery import AntigravityDiscovery
from ag_attention_bridge.antigravity.errors import (
    InteractionStaleError,
    InteractionSubmissionError,
    ServerNotFoundError,
)
from ag_attention_bridge.antigravity.models import (
    PermissionScope,
    QuestionEntry,
    QuestionOption,
    SubmissionState,
)

logger = logging.getLogger("ag_attention_bridge.antigravity.resolver")


class InteractionResolver:
    """Manages interaction submission lifecycle and idempotency guards."""

    def __init__(
        self,
        discovery: AntigravityDiscovery | None = None,
    ) -> None:
        self.discovery = discovery if discovery is not None else AntigravityDiscovery()
        self._lock = threading.Lock()
        # Map (cascade_id, trajectory_id, step_index) -> SubmissionState
        self._state_map: dict[tuple[str, str, int], SubmissionState] = {}
        # Client cache keyed by pid
        self._client_cache: dict[int, AntigravityClient] = {}
        # Authoritative active client per cascade_id
        self._active_cascade_client: dict[str, AntigravityClient] = {}

    def get_state(self, cascade_id: str, trajectory_id: str, step_index: int) -> SubmissionState:
        """Get the current submission state for an interaction."""
        with self._lock:
            return self._state_map.get(
                (cascade_id, trajectory_id, step_index), SubmissionState.HOOK_RECEIVED
            )

    def _get_client_for_workspace(self, workspace_path: str | None = None) -> AntigravityClient:
        """Locate or reuse AntigravityClient for the target workspace."""
        server = None
        if workspace_path:
            server = self.discovery.find_server_for_workspace(workspace_path)

        if server is None:
            servers = self.discovery.discover_servers()
            if not servers:
                raise ServerNotFoundError("No running Antigravity Language Server found.")
            server = servers[0]

        if server.pid in self._client_cache:
            return self._client_cache[server.pid]

        client = AntigravityClient(server)
        self._client_cache[server.pid] = client
        return client

    def _get_client_for_cascade(
        self, cascade_id: str, workspace_path: str | None = None
    ) -> AntigravityClient:
        """Locate the exact AntigravityClient that hosts the given cascade/conversation.

        When multiple Language Server processes exist (across multiple workspace windows,
        or after server restarts), multiple servers might contain cached snapshots of cascade_id.
        This method evaluates all candidate servers and selects the authoritative server hosting
        the freshest trajectory (highest step count and/or active uncompleted waiting step).
        """
        with self._lock:
            cached_client = self._active_cascade_client.get(cascade_id)
            if cached_client is not None:
                return cached_client

        candidates: list[tuple[int, bool, AntigravityClient]] = []

        try:
            servers = self.discovery.discover_servers()
            for s in servers:
                try:
                    with self._lock:
                        if s.pid in self._client_cache:
                            c = self._client_cache[s.pid]
                        else:
                            c = AntigravityClient(s)
                            self._client_cache[s.pid] = c

                    traj = c.get_cascade_trajectory(cascade_id)
                    t_obj = traj.get("trajectory", {})
                    if t_obj.get("cascadeId") == cascade_id:
                        steps = t_obj.get("steps", [])
                        step_count = len(steps)
                        has_waiting = False
                        if steps:
                            for st in steps[-5:]:
                                if not st.get("completedInteractions") and (
                                    st.get("requestedInteraction")
                                    or "WAITING" in str(st.get("status", ""))
                                ):
                                    has_waiting = True
                                    break
                        candidates.append((step_count, has_waiting, c))
                except Exception:
                    continue
        except Exception:
            pass

        if candidates:
            # Sort order: server with active waiting step first, then highest step count
            candidates.sort(key=lambda item: (item[1], item[0]), reverse=True)
            winner = candidates[0][2]
            with self._lock:
                self._active_cascade_client[cascade_id] = winner
            return winner

        return self._get_client_for_workspace(workspace_path)

    def invalidate_client_cache(self, pid: int | None = None) -> None:
        """Invalidate cached clients on restart or disconnect."""
        with self._lock:
            if pid is not None:
                self._client_cache.pop(pid, None)
                # Also remove any active cascade mapping pointing to this pid
                stale_cascades = [
                    cid
                    for cid, client in self._active_cascade_client.items()
                    if client.server.pid == pid
                ]
                for cid in stale_cascades:
                    self._active_cascade_client.pop(cid, None)
            else:
                self._client_cache.clear()
                self._active_cascade_client.clear()

    def resolve_waiting_step(
        self,
        cascade_id: str,
        workspace_path: str | None = None,
        max_retries: int = 10,
    ) -> tuple[str, int, dict[str, Any]] | None:
        """Attempt to locate the live waiting trajectory step for a cascade."""
        try:
            client = self._get_client_for_cascade(cascade_id, workspace_path)
            res = client.find_waiting_interaction(cascade_id, max_retries=max_retries)
            if res is None:
                # If waiting step was not found on the cached client, clear the mapping so next call re-evaluates
                with self._lock:
                    self._active_cascade_client.pop(cascade_id, None)
            return res
        except Exception as e:
            with self._lock:
                self._active_cascade_client.pop(cascade_id, None)
            logger.warning("Failed to resolve waiting step for %s: %s", cascade_id, e)
            return None

    def resolve_authoritative_waiting_interaction(
        self,
        cascade_id: str,
        workspace_path: str | None = None,
        max_retries: int = 10,
    ) -> dict[str, Any] | None:
        """Fetch authoritative native options/parameters directly from language server WAITING step."""
        from ag_attention_bridge.antigravity.models import InteractionType, QuestionOption
        from ag_attention_bridge.config import log_native_diagnostic

        waiting = self.resolve_waiting_step(
            cascade_id, workspace_path=workspace_path, max_retries=max_retries
        )
        if not waiting:
            log_native_diagnostic("WAITING_STEP_NOT_FOUND", conversation_id=cascade_id)
            return None

        trajectory_id, step_index, step_data = waiting

        req_int = (
            step_data.get("requestedInteraction") or step_data.get("requested_interaction") or {}
        )
        ask_q = (
            req_int.get("askQuestion")
            or req_int.get("ask_question")
            or step_data.get("askQuestion")
            or step_data.get("ask_question")
        )

        if not ask_q:
            # Check metadata.toolCall
            meta_tc = step_data.get("metadata", {}).get("toolCall", {})
            if meta_tc.get("name") in ("ask_question", "default_api:ask_question"):
                import json

                args = meta_tc.get("argumentsJson")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                elif not isinstance(args, dict):
                    args = meta_tc.get("args") or {}
                if isinstance(args, dict) and "questions" in args:
                    ask_q = args

        if not ask_q:
            # Check plannerResponse.toolCalls
            pr = step_data.get("plannerResponse", {})
            for tc in pr.get("toolCalls", []):
                if tc.get("name") in ("ask_question", "default_api:ask_question"):
                    import json

                    args = tc.get("argumentsJson")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    elif not isinstance(args, dict):
                        args = tc.get("args") or {}
                    if isinstance(args, dict) and "questions" in args:
                        ask_q = args
                        break

        if not ask_q and "generic" in step_data:
            import json

            g_args = step_data.get("generic", {}).get("args", {})
            if isinstance(g_args, str):
                try:
                    g_args = json.loads(g_args)
                except Exception:
                    g_args = {}
            if "questions" in g_args:
                ask_q = g_args

        perm = (
            req_int.get("permission")
            or req_int.get("runCommand")
            or req_int.get("filePermission")
            or step_data.get("permission")
            or step_data.get("runCommand")
            or step_data.get("filePermission")
        )

        if ask_q:
            raw_questions = ask_q.get("questions", [])
            parsed_questions: list[QuestionEntry] = []
            for q_dict in raw_questions:
                q_text = q_dict.get("question", "") or q_dict.get("Question", "")
                raw_opts = q_dict.get("options", []) or q_dict.get("Options", [])
                opts: list[QuestionOption] = []
                for opt_idx, opt in enumerate(raw_opts):
                    if isinstance(opt, dict) and "id" in opt:
                        opt_id = str(opt["id"])
                        opt_text = str(opt.get("text") or opt.get("label") or "")
                        opts.append(QuestionOption(id=opt_id, text=opt_text))
                    elif isinstance(opt, dict):
                        opt_id = str(opt.get("id") or opt.get("Id") or str(opt_idx + 1))
                        opt_text = str(opt.get("text") or opt.get("Text") or opt.get("label") or "")
                        opts.append(QuestionOption(id=opt_id, text=opt_text))
                    else:
                        # String option: Antigravity wDi() maps index to "1", "2", "3", ...
                        opts.append(QuestionOption(id=str(opt_idx + 1), text=str(opt)))

                is_multi = bool(
                    q_dict.get("isMultiSelect")
                    or q_dict.get("is_multi_select")
                    or q_dict.get("IsMultiSelect")
                )
                # Default selection is the first native option ID
                default_selected = [opts[0].id] if opts and not is_multi else []
                parsed_questions.append(
                    QuestionEntry(
                        question=q_text,
                        options=opts,
                        is_multi_select=is_multi,
                        selected_option_ids=default_selected,
                        write_in_response="",
                        skipped=False,
                    )
                )

            opt_ids = [o.id for q in parsed_questions for o in q.options]
            log_native_diagnostic(
                "NATIVE_READY",
                conversation_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                interaction_type="ask_question",
                selected_option_ids=opt_ids,
            )

            return {
                "trajectory_id": trajectory_id,
                "step_index": step_index,
                "interaction_type": InteractionType.ASK_QUESTION,
                "questions": parsed_questions,
            }
        else:
            perm_dict = perm if isinstance(perm, dict) else {}
            res_dict = (
                perm_dict.get("resource", {}) if isinstance(perm_dict.get("resource"), dict) else {}
            )
            action = res_dict.get("action") or (
                "run_command" if "runCommand" in step_data else "permission"
            )
            target = res_dict.get("target") or step_data.get("runCommand", {}).get(
                "commandLine", ""
            )
            if not target:
                meta_tc = step_data.get("metadata", {}).get("toolCall", {})
                args_raw = meta_tc.get("argumentsJson")
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                        target = (
                            args.get("CommandLine")
                            or args.get("TargetFile")
                            or args.get("Command")
                            or ""
                        )
                    except Exception:
                        pass
                elif isinstance(args_raw, dict):
                    target = args_raw.get("CommandLine") or args_raw.get("TargetFile") or ""
            reason = (
                perm_dict.get("actionDescription")
                or step_data.get("metadata", {}).get("toolSummary")
                or step_data.get("metadata", {}).get("toolAction")
                or f"Antigravity requested execution of {action}"
            )
            suggested_pattern = perm_dict.get("suggestedPersistPattern", "")

            log_native_diagnostic(
                "NATIVE_READY",
                conversation_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                interaction_type="permission",
                extra=f"action={action} target={target[:60]}",
            )
            return {
                "trajectory_id": trajectory_id,
                "step_index": step_index,
                "interaction_type": InteractionType.PERMISSION,
                "permission_action": action,
                "permission_target": target,
                "permission_reason": reason,
                "suggested_pattern": suggested_pattern,
            }

    def scan_waiting_interactions(self) -> list[tuple[str, dict[str, Any]]]:
        """Scan all running language servers for cascades needing attention and resolve waiting steps.

        Returns a list of (cascade_id, resolved_interaction_dict).
        """
        results: list[tuple[str, dict[str, Any]]] = []
        try:
            servers = self.discovery.discover_servers()
        except Exception as e:
            logger.debug("Error discovering servers during scan: %s", e)
            return results

        for server in servers:
            try:
                with self._lock:
                    if server.pid in self._client_cache:
                        client = self._client_cache[server.pid]
                    else:
                        client = AntigravityClient(server, timeout=3.0)
                        self._client_cache[server.pid] = client

                convs = client.search_conversations()
                for conv in convs:
                    if conv.get("needsAttention"):
                        cid = conv.get("cascadeId")
                        if cid:
                            resolved = self.resolve_authoritative_waiting_interaction(
                                cid, max_retries=2
                            )
                            if resolved:
                                ws_name = (
                                    conv.get("workspaceName")
                                    or conv.get("worktreeRoot")
                                    or (client.server.workspace_path if client.server else None)
                                )
                                resolved["workspace_path"] = ws_name
                                results.append((cid, resolved))
            except Exception as e:
                logger.debug("Error scanning server PID %d: %s", server.pid, e)
                continue

        return results

    def submit_question_response(
        self,
        cascade_id: str,
        trajectory_id: str,
        step_index: int,
        responses: list[QuestionEntry],
        workspace_path: str | None = None,
    ) -> bool:
        """Submit native response for an ask_question interaction."""
        from ag_attention_bridge.config import log_native_diagnostic

        key = (cascade_id, trajectory_id, step_index)

        with self._lock:
            current_state = self._state_map.get(key, SubmissionState.HOOK_RECEIVED)
            if current_state in (SubmissionState.SUBMITTING, SubmissionState.SUBMITTED):
                logger.warning(
                    "Duplicate submission ignored for %s (current state: %s)", key, current_state
                )
                return False
            self._state_map[key] = SubmissionState.SUBMITTING

        client = self._get_client_for_cascade(cascade_id, workspace_path)
        payload = client.build_ask_question_payload(trajectory_id, step_index, responses)

        all_selected_ids = []
        for r in responses:
            all_selected_ids.extend(r.selected_option_ids)

        log_native_diagnostic(
            "RPC_REQUEST",
            conversation_id=cascade_id,
            trajectory_id=trajectory_id,
            step_index=step_index,
            interaction_type="ask_question",
            selected_option_ids=all_selected_ids,
        )

        try:
            client.handle_cascade_user_interaction(cascade_id, payload)
            with self._lock:
                self._state_map[key] = SubmissionState.SUBMITTED

            log_native_diagnostic(
                "RPC_SUCCESS",
                conversation_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                interaction_type="ask_question",
                selected_option_ids=all_selected_ids,
                http_status=200,
            )
            return True
        except InteractionStaleError as e:
            with self._lock:
                self._state_map[key] = SubmissionState.STALE
            log_native_diagnostic(
                "STALE",
                conversation_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                extra=str(e),
            )
            raise
        except Exception as e:
            with self._lock:
                self._state_map[key] = SubmissionState.FAILED
            log_native_diagnostic(
                "RPC_FAILURE",
                conversation_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                extra=str(e),
            )
            raise InteractionSubmissionError(f"Submission failed for {key}: {e}") from e

    def submit_permission_decision(
        self,
        cascade_id: str,
        trajectory_id: str,
        step_index: int,
        allow: bool,
        scope: PermissionScope = PermissionScope.PERMISSION_SCOPE_ONCE,
        user_deny_instruction: str = "",
        workspace_path: str | None = None,
    ) -> bool:
        """Submit native decision for a permission interaction."""
        from ag_attention_bridge.config import log_native_diagnostic

        key = (cascade_id, trajectory_id, step_index)

        with self._lock:
            current_state = self._state_map.get(key, SubmissionState.HOOK_RECEIVED)
            if current_state in (SubmissionState.SUBMITTING, SubmissionState.SUBMITTED):
                logger.warning(
                    "Duplicate submission ignored for %s (current state: %s)", key, current_state
                )
                return False
            self._state_map[key] = SubmissionState.SUBMITTING

        client = self._get_client_for_cascade(cascade_id, workspace_path)
        payload = client.build_permission_payload(
            trajectory_id,
            step_index,
            allow=allow,
            scope=scope,
            user_deny_instruction=user_deny_instruction,
        )

        log_native_diagnostic(
            "RPC_REQUEST",
            conversation_id=cascade_id,
            trajectory_id=trajectory_id,
            step_index=step_index,
            interaction_type="permission",
            extra=f"allow={allow} scope={scope}",
        )

        try:
            client.handle_cascade_user_interaction(cascade_id, payload)
            with self._lock:
                self._state_map[key] = SubmissionState.SUBMITTED

            log_native_diagnostic(
                "RPC_SUCCESS",
                conversation_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                interaction_type="permission",
                http_status=200,
                extra=f"allow={allow}",
            )
            return True
        except InteractionStaleError as e:
            with self._lock:
                self._state_map[key] = SubmissionState.STALE
            log_native_diagnostic(
                "STALE",
                conversation_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                extra=str(e),
            )
            raise
        except Exception as e:
            with self._lock:
                self._state_map[key] = SubmissionState.FAILED
            log_native_diagnostic(
                "RPC_FAILURE",
                conversation_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                extra=str(e),
            )
            raise InteractionSubmissionError(f"Permission submission failed for {key}: {e}") from e

    def submit_interaction(
        self,
        cascade_id: str,
        trajectory_id: str | None,
        step_index: int | None,
        is_permission: bool,
        response_data: Any,
        workspace_path: str | None = None,
    ) -> bool:
        """Unified submission method called by UI, button handlers, shortcuts, or automation rules."""
        from ag_attention_bridge.config import log_native_diagnostic

        log_native_diagnostic(
            "ENTER_SUBMIT",
            conversation_id=cascade_id,
            trajectory_id=trajectory_id,
            step_index=step_index,
            interaction_type="permission" if is_permission else "ask_question",
        )

        # Auto-resolve trajectory_id and step_index if not supplied
        if not trajectory_id or step_index is None:
            resolved = self.resolve_authoritative_waiting_interaction(
                cascade_id, workspace_path=workspace_path, max_retries=6
            )
            if resolved:
                trajectory_id = resolved["trajectory_id"]
                step_index = resolved["step_index"]
            else:
                raise InteractionSubmissionError(
                    f"Cannot submit interaction for cascade {cascade_id}: no active waiting step found in trajectory."
                )

        if is_permission:
            allow = True
            scope = PermissionScope.PERMISSION_SCOPE_ONCE
            user_deny = ""
            if isinstance(response_data, dict):
                allow = bool(response_data.get("allow", True))
                scope_val = response_data.get("scope", PermissionScope.PERMISSION_SCOPE_ONCE)
                scope = PermissionScope(scope_val) if isinstance(scope_val, str) else scope_val
                user_deny = response_data.get("userDenyInstruction", "")
            elif isinstance(response_data, str):
                allow = response_data.lower() in ("allow", "yes", "true")
            elif isinstance(response_data, bool):
                allow = response_data

            return self.submit_permission_decision(
                cascade_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                allow=allow,
                scope=scope,
                user_deny_instruction=user_deny,
                workspace_path=workspace_path,
            )
        else:
            entries: list[QuestionEntry] = []
            if isinstance(response_data, list):
                for item in response_data:
                    if isinstance(item, QuestionEntry):
                        entries.append(item)
                    elif isinstance(item, dict):
                        # Convert dict to QuestionEntry
                        raw_options = item.get("options") or []
                        raw_selected = (
                            item.get("selectedOptionIds") or item.get("selected_option_ids") or []
                        )
                        entries.append(
                            QuestionEntry(
                                question=item.get("question", ""),
                                options=[
                                    QuestionOption(
                                        id=str(o.get("id", idx)),
                                        text=str(o.get("text", o.get("label", ""))),
                                    )
                                    for idx, o in enumerate(raw_options)
                                ],
                                is_multi_select=bool(
                                    item.get("isMultiSelect", item.get("is_multi_select", False))
                                ),
                                selected_option_ids=[str(sid) for sid in raw_selected],
                                write_in_response=str(
                                    item.get("writeInResponse", item.get("write_in_response", ""))
                                ),
                                skipped=bool(item.get("skipped", False)),
                            )
                        )
            return self.submit_question_response(
                cascade_id=cascade_id,
                trajectory_id=trajectory_id,
                step_index=step_index,
                responses=entries,
                workspace_path=workspace_path,
            )
