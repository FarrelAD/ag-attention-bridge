"""Qt-based Local IPC Server for Ag Attention Bridge daemon."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from ag_attention_bridge.antigravity.models import InteractionState, InteractionType
from ag_attention_bridge.config import (
    SOCKET_PATH,
    SYNTHETIC_FALLBACK_ENABLED,
    log_bridge_diagnostic,
)
from ag_attention_bridge.domain.models import (
    InteractionOption,
    InteractionRequest,
    PendingAnswerItem,
    PendingInjection,
    QuestionItem,
    RequestType,
    format_injected_message,
)
from ag_attention_bridge.ipc.protocol import (
    IpcMessage,
    IpcResponse,
    MessageType,
    decode_payload,
    encode_payload,
)
from ag_attention_bridge.state.store import PendingInjectionStore, RequestQueue, SessionStore

logger = logging.getLogger("ag_attention_bridge.ipc.server")


class IpcServer(QObject):
    """Local IPC server running on Qt event loop via QLocalServer."""

    request_received = Signal(object)  # Emits InteractionRequest
    _interaction_discovered = Signal(object, object)  # (resolved_data: dict, context_data: dict)

    def __init__(
        self,
        queue: RequestQueue,
        sessions: SessionStore,
        injections: PendingInjectionStore | None = None,
        socket_path: str | Path = SOCKET_PATH,
        resolver: Any | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.queue = queue
        self.sessions = sessions
        self.injections = injections if injections is not None else PendingInjectionStore()
        self.socket_path = str(socket_path)
        self.resolver = resolver

        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handle_new_connection)
        self._interaction_discovered.connect(self._on_interaction_discovered)

        # Map request_id -> (QLocalSocket, client_msg_id)
        self._pending_responses: dict[str, tuple[QLocalSocket, str]] = {}
        # Buffer per socket for streaming newline-delimited messages
        self._socket_buffers: dict[QLocalSocket, bytearray] = {}
        # Guard to prevent duplicate concurrent waiting checks for the same conversation
        self._checking_conversations: set[str] = set()
        self._scanning: bool = False
        self._poll_timer: Any | None = None

    def start(self) -> bool:
        """Start listening on the local socket or named pipe."""
        # On POSIX, clean up stale socket file if it exists
        if os.name != "nt" and os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError as e:
                logger.warning("Could not unlink existing socket %s: %s", self.socket_path, e)

        QLocalServer.removeServer(self.socket_path)

        # On POSIX, ensure parent directory exists with safe permissions
        if os.name != "nt":
            Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)

        if not self._server.listen(self.socket_path):
            logger.error(
                "Failed to start IPC server on %s: %s", self.socket_path, self._server.errorString()
            )
            return False

        logger.info("IPC server listening on %s", self.socket_path)
        return True

    def start_background_poller(self, interval_ms: int = 2000) -> None:
        """Start periodic background scanning across all discovered language servers."""
        from PySide6.QtCore import QTimer

        if self._poll_timer is not None:
            self._poll_timer.stop()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.poll_active_interactions)
        self._poll_timer.start(interval_ms)
        logger.info("Active Language Server poller started (interval: %dms)", interval_ms)
        self.poll_active_interactions()

    def poll_active_interactions(self) -> None:
        """Asynchronously scan all running language servers for waiting interactions."""
        if not self.resolver or self._scanning:
            return

        self._scanning = True
        import threading

        def _worker():
            try:
                if self.resolver is None:
                    return
                waiting_list = self.resolver.scan_waiting_interactions()
                for cid, resolved in waiting_list:
                    ws_path = resolved.get("workspace_path")
                    self._interaction_discovered.emit(
                        resolved,
                        {
                            "conversation_id": cid,
                            "workspace_path": ws_path,
                            "payload": {},
                        },
                    )
            except Exception as e:
                logger.debug("Background poller error: %s", e)
            finally:
                self._scanning = False

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def stop(self) -> None:
        """Shut down the IPC server and disconnect clients."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None

        for sock, _ in list(self._pending_responses.values()):
            try:
                sock.disconnectFromServer()
            except Exception:
                pass
        self._pending_responses.clear()
        self._socket_buffers.clear()

        if self._server.isListening():
            self._server.close()

        QLocalServer.removeServer(self.socket_path)
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass
        logger.info("IPC server stopped")

    def _handle_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._socket_buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(lambda s=socket: self._on_disconnected(s))

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        buffer = self._socket_buffers.get(socket)
        if buffer is None:
            buffer = bytearray()
            self._socket_buffers[socket] = buffer

        chunk = socket.readAll().data()
        buffer.extend(chunk)

        while b"\n" in buffer:
            line, _, remainder = buffer.partition(b"\n")
            buffer.clear()
            buffer.extend(remainder)

            if not line.strip():
                continue

            try:
                raw_msg = decode_payload(line)
                self._dispatch_message(socket, raw_msg)
            except Exception as e:
                logger.error("Error handling IPC message: %s", e)
                error_resp = IpcResponse(reply_to="unknown", status="error", error=str(e))
                self._send_to_socket(socket, error_resp)

    def _on_disconnected(self, socket: QLocalSocket) -> None:
        self._socket_buffers.pop(socket, None)
        # Clean up any pending response registrations pointing to this disconnected socket
        stale_keys = [k for k, (s, _) in self._pending_responses.items() if s == socket]
        for k in stale_keys:
            self._pending_responses.pop(k, None)
            logger.info("Removed pending waiting client for request %s (socket disconnected)", k)

    def _dispatch_message(self, socket: QLocalSocket, raw: dict[str, Any]) -> None:
        msg_type = raw.get("type")
        msg_id = raw.get("msg_id", "")
        conversation_id = raw.get("conversation_id", "")
        payload = raw.get("payload", {})

        if msg_type == MessageType.SUBMIT_REQUEST.value:
            self._handle_submit_request(socket, msg_id, conversation_id, payload)
        elif msg_type == MessageType.RESOLVE_REQUEST.value:
            request_id = raw.get("request_id") or payload.get("request_id")
            response_val = payload.get("response")
            self._handle_resolve_request(socket, msg_id, request_id, response_val)
        elif msg_type == MessageType.GET_QUEUE.value:
            self._handle_get_queue(socket, msg_id)
        elif msg_type == MessageType.GET_PENDING_INJECTION.value:
            self._handle_get_pending_injection(socket, msg_id, conversation_id)
        elif msg_type == MessageType.CHECK_STOP.value:
            self._handle_check_stop(socket, msg_id, conversation_id)
        elif msg_type == MessageType.DISMISS_REQUEST.value:
            request_id = raw.get("request_id") or payload.get("request_id")
            if request_id:
                self.queue.dismiss_to_tray(request_id)
            self._send_to_socket(socket, IpcResponse(reply_to=msg_id, status="ok"))
        elif msg_type == MessageType.NOTIFY_EVENT.value:
            if conversation_id:
                self.sessions.get_or_create(
                    conversation_id,
                    workspace_paths=payload.get("workspacePaths"),
                    model_name=payload.get("modelName"),
                    transcript_path=payload.get("transcriptPath"),
                )
            self._send_to_socket(socket, IpcResponse(reply_to=msg_id, status="ok"))
        elif msg_type == MessageType.CHECK_WAITING.value:
            self._handle_check_waiting(socket, msg_id, conversation_id, payload)
        else:
            self._send_to_socket(
                socket,
                IpcResponse(
                    reply_to=msg_id, status="error", error=f"Unknown message type: {msg_type}"
                ),
            )

    def _handle_check_waiting(
        self,
        socket: QLocalSocket,
        msg_id: str,
        conversation_id: str,
        payload: dict[str, Any],
    ) -> None:
        if conversation_id:
            self.sessions.get_or_create(
                conversation_id,
                workspace_paths=payload.get("workspacePaths"),
                model_name=payload.get("modelName"),
                transcript_path=payload.get("transcriptPath"),
            )
        self._send_to_socket(socket, IpcResponse(reply_to=msg_id, status="ok"))

        if not self.resolver or not conversation_id:
            return

        if conversation_id in self._checking_conversations:
            return

        self._checking_conversations.add(conversation_id)

        import threading

        ws_paths = payload.get("workspacePaths", [])
        ws_path = ws_paths[0] if ws_paths else None

        def _worker():
            try:
                if self.resolver is None:
                    return
                resolved = self.resolver.resolve_authoritative_waiting_interaction(
                    cascade_id=conversation_id,
                    workspace_path=ws_path,
                    max_retries=8,
                )
                if resolved:
                    self._interaction_discovered.emit(
                        resolved,
                        {
                            "conversation_id": conversation_id,
                            "workspace_path": ws_path,
                            "payload": payload,
                        },
                    )
            except Exception as e:
                logger.warning(
                    "Error in background check_waiting worker for %s: %s", conversation_id, e
                )
            finally:
                self._checking_conversations.discard(conversation_id)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _on_interaction_discovered(self, resolved: dict[str, Any], ctx: dict[str, Any]) -> None:
        conversation_id = ctx.get("conversation_id", "")
        ws_path = ctx.get("workspace_path") or resolved.get("workspace_path")

        trajectory_id = resolved.get("trajectory_id", "")
        step_index = resolved.get("step_index", 0)
        int_type = resolved.get("interaction_type")

        # Auto-purge any stale pending requests for this conversation from earlier steps
        for old_req in self.queue.get_pending_list():
            if (
                old_req.conversation_id == conversation_id
                and old_req.step_index is not None
                and old_req.step_index < step_index
            ):
                logger.info(
                    "Auto-purging stale pending request %s (step %d < current step %d)",
                    old_req.request_id,
                    old_req.step_index,
                    step_index,
                )
                self.queue.consume(old_req.request_id)

        # Deduplication: check if already in queue with same conversation_id & step_index
        for req in self.queue.list_all():
            if (
                req.conversation_id == conversation_id
                and req.trajectory_id == trajectory_id
                and req.step_index == step_index
            ):
                return

        request_id = f"auto-{conversation_id[:8]}-{step_index}"

        if int_type == InteractionType.ASK_QUESTION:
            req_type = RequestType.QUESTION
            native_questions = resolved.get("questions", [])
            parsed_questions: list[QuestionItem] = []
            for idx, nq in enumerate(native_questions):
                parsed_opts = [InteractionOption(id=opt.id, label=opt.text) for opt in nq.options]
                parsed_questions.append(
                    QuestionItem(
                        id=str(idx),
                        question=nq.question,
                        options=parsed_opts,
                        multi_select=nq.is_multi_select,
                        allow_custom_input=True,
                    )
                )
            if parsed_questions:
                title = (
                    parsed_questions[0].question
                    if len(parsed_questions) == 1
                    else f"Questions ({len(parsed_questions)} items)"
                )
                body = parsed_questions[0].question
                options = parsed_questions[0].options
                multi_select = parsed_questions[0].multi_select
            else:
                title = "Question from Antigravity"
                body = ""
                options = []
                multi_select = False
        else:
            req_type = RequestType.PERMISSION
            parsed_questions = []
            action = resolved.get("permission_action") or "permission"
            target = resolved.get("permission_target") or ""
            reason = resolved.get("permission_reason") or ""
            title = reason if reason else f"Permission Request: {action}"
            body = f"Target: {target}\nReason: {reason}"
            options = [
                InteractionOption(id="allow", label="Allow Once"),
                InteractionOption(id="allow_conversation", label="Always in Conversation"),
                InteractionOption(id="allow_global", label="Always Globally"),
                InteractionOption(id="deny", label="Deny"),
            ]
            multi_select = False

        interaction_req = InteractionRequest(
            request_id=request_id,
            conversation_id=conversation_id,
            request_type=req_type,
            title=title,
            body=body,
            questions=parsed_questions,
            options=options,
            multi_select=multi_select,
            workspace_path=ws_path,
            trajectory_id=trajectory_id,
            step_index=step_index,
            state=InteractionState.NATIVE_WAITING_READY,
        )

        self.queue.enqueue(interaction_req)
        logger.info(
            "Auto-discovered native %s interaction for cascade %s (step %d) enqueued as %s",
            req_type.value,
            conversation_id,
            step_index,
            request_id,
        )
        self.request_received.emit(interaction_req)

    def _handle_submit_request(
        self,
        socket: QLocalSocket,
        msg_id: str,
        conversation_id: str,
        payload: dict[str, Any],
    ) -> None:
        # Convert hook payload to InteractionRequest
        tool_call = payload.get("toolCall", {})
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})

        parsed_questions: list[QuestionItem] = []

        if tool_name == "ask_question":
            req_type = RequestType.QUESTION
            raw_questions = tool_args.get("questions", [])
            if isinstance(raw_questions, str):
                try:
                    raw_questions = json.loads(raw_questions)
                except Exception:
                    raw_questions = []
            if isinstance(raw_questions, dict):
                raw_questions = [raw_questions]

            if not raw_questions:
                # Fallback if question is passed directly in args
                raw_q = tool_args.get("question", "Question from Antigravity")
                raw_opts = tool_args.get("options", [])
                raw_questions = [{"question": raw_q, "options": raw_opts}]

            for idx, q_dict in enumerate(raw_questions):
                if not isinstance(q_dict, dict):
                    continue
                q_text = q_dict.get("question", f"Question {idx + 1}")
                raw_opts = q_dict.get("options", [])
                if isinstance(raw_opts, str):
                    try:
                        raw_opts = json.loads(raw_opts)
                    except Exception:
                        raw_opts = []
                opts = []
                for o_idx, opt in enumerate(raw_opts):
                    if isinstance(opt, dict):
                        opts.append(
                            InteractionOption(
                                id=str(opt.get("id", o_idx)), label=str(opt.get("label", opt))
                            )
                        )
                    else:
                        opts.append(InteractionOption(id=str(o_idx), label=str(opt)))
                multi_sel = bool(q_dict.get("is_multi_select", False))
                allow_custom = bool(q_dict.get("allow_custom_input", True))

                parsed_questions.append(
                    QuestionItem(
                        id=str(idx),
                        question=q_text,
                        options=opts,
                        multi_select=multi_sel,
                        allow_custom_input=allow_custom,
                    )
                )

            if parsed_questions:
                title = (
                    parsed_questions[0].question
                    if len(parsed_questions) == 1
                    else f"Questions ({len(parsed_questions)} items)"
                )
                body = parsed_questions[0].question
                options = parsed_questions[0].options
                multi_select = parsed_questions[0].multi_select
            else:
                title = "Question from Antigravity"
                body = ""
                options = []
                multi_select = False
        else:
            # Permission request (ask_permission, run_command, write_to_file, etc.)
            req_type = RequestType.PERMISSION
            if tool_name == "ask_permission":
                action = tool_args.get("action") or tool_args.get("Action", "action")
                target = tool_args.get("target") or tool_args.get("Target", "")
                reason = tool_args.get("reason") or tool_args.get("Reason", "")
            else:
                action = tool_name
                target = (
                    tool_args.get("CommandLine")
                    or tool_args.get("TargetFile")
                    or tool_args.get("Url")
                    or tool_args.get("Command")
                    or str(tool_args.get("args", tool_args))
                )
                reason = (
                    tool_args.get("toolSummary")
                    or tool_args.get("toolAction")
                    or tool_args.get("Description")
                    or f"Antigravity requested execution of {tool_name}"
                )

            title = f"Permission Request: {action}"
            body = f"Target: {target}\nReason: {reason}"
            options = [
                InteractionOption(id="allow", label="Allow"),
                InteractionOption(id="deny", label="Deny"),
            ]
            multi_select = False

        # Collect temporary permission grants for Antigravity IDE terminal sandbox
        permission_overrides: list[str] = []
        if req_type == RequestType.PERMISSION:
            cmd = tool_args.get("CommandLine") or tool_args.get("Command")
            if cmd:
                cmd_str = str(cmd).strip()
                permission_overrides.append(f"command({cmd_str})")
            target_val = (
                tool_args.get("target") or tool_args.get("Target") or tool_args.get("TargetFile")
            )
            if target_val:
                t_str = str(target_val).strip()
                act = tool_args.get("action") or tool_args.get("Action") or tool_name
                if act in ("run_command", ""):
                    permission_overrides.append(f"command({t_str})")
                else:
                    permission_overrides.append(f"{act}({t_str})")

        ws_paths = payload.get("workspacePaths", [])
        ws_path = ws_paths[0] if ws_paths else None
        step_idx = payload.get("stepIdx")

        request_id = payload.get("request_id") or msg_id

        interaction_req = InteractionRequest(
            request_id=request_id,
            conversation_id=conversation_id,
            request_type=req_type,
            title=title,
            body=body,
            questions=parsed_questions,
            options=options,
            multi_select=multi_select,
            permission_overrides=permission_overrides,
            workspace_path=ws_path,
            model_name=payload.get("modelName"),
            step_index=step_idx,
        )

        # Attempt fast resolution of live waiting step
        if self.resolver is not None:
            try:
                waiting = self.resolver.resolve_waiting_step(
                    conversation_id, workspace_path=ws_path, max_retries=1
                )
                if waiting:
                    traj_id, s_idx, _ = waiting
                    interaction_req.trajectory_id = traj_id
                    interaction_req.step_index = s_idx
            except Exception as e:
                logger.debug("Fast waiting step lookup deferred: %s", e)

        self.sessions.attach_request(conversation_id, request_id)
        enqueued = self.queue.enqueue(interaction_req)

        wait_for_response = payload.get("wait_for_response", True)

        log_bridge_diagnostic(
            request_id=request_id,
            conversation_id=conversation_id,
            hook_event="PreToolUse",
            tool_name=tool_name,
            request_state="pending" if enqueued else "deduplicated",
            ipc_state="waiting_modal" if wait_for_response else "native_trigger_enqueued",
        )

        if not wait_for_response:
            # Native Mode: Immediate non-blocking ACK
            resp = IpcResponse(
                reply_to=msg_id,
                status="ok",
                data={
                    "status": "enqueued" if enqueued else "deduplicated",
                    "request_id": request_id,
                },
            )
            self._send_to_socket(socket, resp)
            if enqueued:
                self.request_received.emit(interaction_req)
        else:
            # Legacy synchronous mode
            if enqueued:
                self._pending_responses[request_id] = (socket, msg_id)
                self.request_received.emit(interaction_req)
            else:
                resp = IpcResponse(
                    reply_to=msg_id,
                    status="ok",
                    data={"status": "deduplicated", "request_id": request_id},
                )
                self._send_to_socket(socket, resp)

    def resolve_request(self, request_id: str, response_value: Any) -> bool:
        """Resolve a request directly from UI or internal controller."""
        req = self.queue.resolve(request_id, response_value)
        if not req:
            logger.warning("Attempted to resolve unknown request %s", request_id)
            return False

        logger.info("[REQ %s] IPC future resolved with: %s", request_id, response_value)

        # Submit natively if resolver is present and interaction has not been submitted
        if self.resolver is not None:
            try:
                self.resolver.submit_interaction(
                    cascade_id=req.conversation_id,
                    trajectory_id=req.trajectory_id,
                    step_index=req.step_index,
                    is_permission=(req.request_type == RequestType.PERMISSION),
                    response_data=response_value,
                    workspace_path=req.workspace_path,
                )
            except Exception as e:
                logger.debug("Resolver submission via resolve_request: %s", e)

        # Deliver to waiting client adapter
        waiting = self._pending_responses.pop(request_id, None)
        if waiting:
            client_socket, client_msg_id = waiting
            decision_data: dict[str, Any]
            if req.request_type == RequestType.PERMISSION:
                is_allow = str(response_value).lower() in ("allow", "yes", "true")
                if is_allow:
                    decision_data = {"decision": "allow"}
                    if req.permission_overrides:
                        decision_data["permissionOverrides"] = req.permission_overrides
                else:
                    decision_data = {
                        "decision": "deny",
                        "reason": "Denied through Ag Attention Bridge",
                    }
            elif not SYNTHETIC_FALLBACK_ENABLED:
                decision_data = {
                    "decision": "allow",
                    "reason": "Ag Attention Bridge observation hook; native interaction will resolve externally.",
                }
            else:
                # For ask_question (Phase 5 legacy fallback only):
                # 1. Parse answers into PendingAnswerItems
                items: list[PendingAnswerItem] = []
                if isinstance(response_value, list):
                    for item in response_value:
                        if isinstance(item, dict):
                            q_text = item.get("question", req.title)
                            sel = item.get("selected", [])
                            if isinstance(sel, str):
                                sel = [sel]
                            items.append(PendingAnswerItem(question=q_text, selected=sel))
                        else:
                            items.append(
                                PendingAnswerItem(question=req.title, selected=[str(item)])
                            )
                elif isinstance(response_value, dict):
                    q_text = response_value.get("question", req.title)
                    sel = response_value.get("selected", [])
                    if isinstance(sel, str):
                        sel = [sel]
                    items.append(PendingAnswerItem(question=q_text, selected=sel))
                else:
                    items.append(
                        PendingAnswerItem(question=req.title, selected=[str(response_value)])
                    )

                # 2. Store pending injection for PreInvocation
                injection = PendingInjection(
                    conversation_id=req.conversation_id,
                    request_id=request_id,
                    items=items,
                )
                self.injections.store_pending(injection)

                # 3. Return PreToolUse deny to suppress Antigravity native question card
                decision_data = {
                    "decision": "deny",
                    "reason": "Question handled by Ag Attention Bridge. External user response is pending injection.",
                }

            log_bridge_diagnostic(
                request_id=request_id,
                conversation_id=req.conversation_id,
                hook_event="PreToolUse",
                tool_name="ask_question"
                if req.request_type == RequestType.QUESTION
                else "permission",
                request_state="answered",
                ui_action=str(response_value),
                ipc_state="response_transmitted",
                hook_output=decision_data,
                exit_code=0,
            )

            adapter_resp = IpcResponse(
                reply_to=client_msg_id,
                status="ok",
                data=decision_data,
            )
            self._send_to_socket(client_socket, adapter_resp)

        # Always consume the request from pending queue upon resolution
        self.queue.consume(request_id)
        return True

    def _handle_get_pending_injection(
        self,
        socket: QLocalSocket,
        msg_id: str,
        conversation_id: str,
    ) -> None:
        """Handle PreInvocation check: returns injectSteps with user answer if pending."""
        if not SYNTHETIC_FALLBACK_ENABLED:
            resp = IpcResponse(
                reply_to=msg_id,
                status="ok",
                data={"has_injection": False},
            )
            self._send_to_socket(socket, resp)
            return

        inj = self.injections.get_pending(conversation_id)
        if inj:
            user_msg = format_injected_message(inj)
            self.injections.consume_pending(conversation_id)
            log_bridge_diagnostic(
                request_id=inj.request_id,
                conversation_id=conversation_id,
                hook_event="PreInvocation",
                request_state="consumed",
                ipc_state="injected_userMessage",
                hook_output={"injectSteps": [{"userMessage": user_msg}]},
                exit_code=0,
            )
            resp = IpcResponse(
                reply_to=msg_id,
                status="ok",
                data={
                    "has_injection": True,
                    "injectSteps": [{"userMessage": user_msg}],
                },
            )
        else:
            resp = IpcResponse(
                reply_to=msg_id,
                status="ok",
                data={"has_injection": False},
            )
        self._send_to_socket(socket, resp)

    def _handle_check_stop(
        self,
        socket: QLocalSocket,
        msg_id: str,
        conversation_id: str,
    ) -> None:
        """Handle Stop hook check: continue if unconsumed answer is pending."""
        if not SYNTHETIC_FALLBACK_ENABLED:
            resp = IpcResponse(
                reply_to=msg_id,
                status="ok",
                data={},
            )
            self._send_to_socket(socket, resp)
            return

        if self.injections.should_stop_continue(conversation_id):
            log_bridge_diagnostic(
                conversation_id=conversation_id,
                hook_event="Stop",
                ipc_state="force_continue",
                hook_output={"decision": "continue"},
                exit_code=0,
            )
            resp = IpcResponse(
                reply_to=msg_id,
                status="ok",
                data={
                    "decision": "continue",
                    "reason": "An external user response from Ag Attention Bridge is pending. Continue execution so it can be injected.",
                },
            )
        else:
            resp = IpcResponse(
                reply_to=msg_id,
                status="ok",
                data={},
            )
        self._send_to_socket(socket, resp)

    def _handle_resolve_request(
        self,
        resolver_socket: QLocalSocket,
        msg_id: str,
        request_id: str,
        response_value: Any,
    ) -> None:
        ok = self.resolve_request(request_id, response_value)
        if not ok:
            self._send_to_socket(
                resolver_socket,
                IpcResponse(
                    reply_to=msg_id, status="error", error=f"Request {request_id} not found"
                ),
            )
            return

        # ACK resolver
        self._send_to_socket(
            resolver_socket,
            IpcResponse(
                reply_to=msg_id, status="ok", data={"request_id": request_id, "resolved": True}
            ),
        )

    def _handle_get_queue(self, socket: QLocalSocket, msg_id: str) -> None:
        items = []
        for req in self.queue.get_pending_list():
            items.append(
                {
                    "request_id": req.request_id,
                    "conversation_id": req.conversation_id,
                    "type": req.request_type.value,
                    "title": req.title,
                    "status": req.status.value,
                }
            )
        resp = IpcResponse(
            reply_to=msg_id,
            status="ok",
            data={"count": self.queue.count(), "items": items},
        )
        self._send_to_socket(socket, resp)

    def _send_to_socket(self, socket: QLocalSocket, message: IpcResponse | IpcMessage) -> None:
        try:
            wire_data = encode_payload(message)
            socket.write(wire_data)
            socket.flush()
        except Exception as e:
            logger.error("Failed to write to socket: %s", e)
