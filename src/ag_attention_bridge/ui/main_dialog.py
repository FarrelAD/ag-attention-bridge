"""Main interaction modal dialog for Ag Attention Bridge."""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ag_attention_bridge.antigravity.models import (
    InteractionState,
    InteractionType,
    PermissionScope,
)
from ag_attention_bridge.domain.models import (
    InteractionOption,
    InteractionRequest,
    QuestionItem,
    RequestType,
)
from ag_attention_bridge.ui.permission_view import PermissionView
from ag_attention_bridge.ui.question_view import QuestionView
from ag_attention_bridge.ui.theme import apply_theme

logger = logging.getLogger("ag_attention_bridge.ui.modal")


class InteractionModal(QDialog):
    """Premium always-on-top desktop modal dialog for user interaction requests."""

    # Signals
    resolved = Signal(str, object)  # (request_id, response_value)
    dismissed = Signal(str)  # (request_id) - hidden to tray without resolution
    native_step_resolved = Signal(str, object)  # (request_id, resolved_data_or_None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_request: InteractionRequest | None = None
        self._content_widget: QWidget | None = None
        self.resolver: Any = None

        self._setup_window()
        self._setup_layout()
        self.native_step_resolved.connect(self._on_native_step_resolved)
        apply_theme(self)

    def _setup_window(self) -> None:
        self.setWindowTitle("Ag Attention Bridge")
        self.setObjectName("AgAttentionBridgeModal")

        # Frameless always-on-top window like Antigravity IDE modal
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setFixedWidth(720)
        self.setMinimumHeight(280)

    def _setup_layout(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(6, 6, 6, 6)
        outer_layout.setSpacing(0)

        # Main floating card container
        self.container_frame = QFrame(self)
        self.container_frame.setObjectName("ModalContainer")
        container_layout = QVBoxLayout(self.container_frame)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # 1. Header
        self.header_frame = QFrame(self.container_frame)
        self.header_frame.setObjectName("HeaderFrame")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(18, 14, 18, 14)
        header_layout.setSpacing(10)

        # Brand Icon / Title
        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        lbl_title = QLabel("Ag Attention Bridge", self.header_frame)
        lbl_title.setObjectName("HeaderTitle")
        title_row.addWidget(lbl_title)

        self.lbl_project_badge = QLabel("", self.header_frame)
        self.lbl_project_badge.setObjectName("ProjectBadge")
        self.lbl_project_badge.setVisible(False)
        title_row.addWidget(self.lbl_project_badge)

        self.badge_count = QLabel("1 of 1", self.header_frame)
        self.badge_count.setObjectName("BadgeCount")
        title_row.addWidget(self.badge_count)
        title_row.addStretch()

        brand_col.addLayout(title_row)

        self.lbl_subtitle = QLabel("Antigravity Companion", self.header_frame)
        self.lbl_subtitle.setObjectName("HeaderSubtitle")
        brand_col.addWidget(self.lbl_subtitle)

        header_layout.addLayout(brand_col)
        header_layout.addStretch()

        # Close / Hide button
        self.btn_close = QPushButton("✕", self.header_frame)
        self.btn_close.setObjectName("HeaderCloseBtn")
        self.btn_close.setToolTip("Hide to system tray (Esc)")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide_to_tray)
        header_layout.addWidget(self.btn_close)

        container_layout.addWidget(self.header_frame)

        # 2. Scrollable Body
        self.scroll_area = QScrollArea(self.container_frame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_container = QWidget(self.scroll_area)
        self.scroll_container.setObjectName("CentralContainer")
        self.body_layout = QVBoxLayout(self.scroll_container)
        self.body_layout.setContentsMargins(20, 16, 20, 16)
        self.body_layout.setSpacing(14)
        self.scroll_area.setWidget(self.scroll_container)

        container_layout.addWidget(self.scroll_area, 1)

        # 3. Footer Action Bar
        self.footer_frame = QFrame(self.container_frame)
        self.footer_frame.setObjectName("FooterFrame")
        self.footer_layout = QHBoxLayout(self.footer_frame)
        self.footer_layout.setContentsMargins(16, 12, 16, 14)
        self.footer_layout.setSpacing(6)

        # Dismiss Button (Left)
        self.btn_dismiss = QPushButton("Hide (Esc)", self.footer_frame)
        self.btn_dismiss.setObjectName("BtnDismiss")
        self.btn_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dismiss.clicked.connect(self.hide_to_tray)
        self.footer_layout.addWidget(self.btn_dismiss)

        self.lbl_status = QLabel("", self.footer_frame)
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 500;")
        self.footer_layout.addWidget(self.lbl_status)

        self.footer_layout.addStretch()

        # Dynamic Action Buttons Container (Right)
        self.btn_deny = QPushButton("Deny", self.footer_frame)
        self.btn_deny.setObjectName("BtnDeny")
        self.btn_deny.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_deny.clicked.connect(self._on_deny_clicked)
        self.footer_layout.addWidget(self.btn_deny)

        self.btn_allow_global = QPushButton("Always Globally", self.footer_frame)
        self.btn_allow_global.setObjectName("BtnAllowGlobal")
        self.btn_allow_global.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_allow_global.clicked.connect(self._on_allow_global_clicked)
        self.footer_layout.addWidget(self.btn_allow_global)

        self.btn_allow_conversation = QPushButton("Allow Conversation", self.footer_frame)
        self.btn_allow_conversation.setObjectName("BtnAllowConversation")
        self.btn_allow_conversation.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_allow_conversation.clicked.connect(self._on_allow_conversation_clicked)
        self.footer_layout.addWidget(self.btn_allow_conversation)

        self.btn_submit = QPushButton("Submit (Enter)", self.footer_frame)
        self.btn_submit.setObjectName("BtnSubmit")
        self.btn_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_submit.clicked.connect(self._on_submit_clicked)
        self.footer_layout.addWidget(self.btn_submit)

        container_layout.addWidget(self.footer_frame)
        outer_layout.addWidget(self.container_frame)

    def set_resolver(self, resolver: Any) -> None:
        """Attach native InteractionResolver."""
        self.resolver = resolver

    def _render_content(self, request: InteractionRequest) -> None:
        """Render question or permission widgets into the scroll area."""
        if self._content_widget:
            self.body_layout.removeWidget(self._content_widget)
            self._content_widget.deleteLater()
            self._content_widget = None

        if request.request_type == RequestType.PERMISSION:
            self._content_widget = PermissionView(request, self.scroll_container)
            self.btn_deny.setVisible(True)
            self.btn_deny.setText("Deny (4)")
            self.btn_allow_global.setVisible(True)
            self.btn_allow_global.setText("Always Globally (3)")
            self.btn_allow_conversation.setVisible(True)
            self.btn_allow_conversation.setText("Always in Conv (2)")
            self.btn_submit.setObjectName("BtnAllow")
            self.btn_submit.setText("Allow Once (1 / ↵)")
            self.btn_submit.setDefault(True)
            apply_theme(self)
        else:
            self._content_widget = QuestionView(request, self.scroll_container)
            self.btn_deny.setVisible(False)
            self.btn_allow_conversation.setVisible(False)
            self.btn_allow_global.setVisible(False)
            self.btn_submit.setObjectName("BtnSubmit")
            self.btn_submit.setText("Submit (Enter)")
            self.btn_submit.setDefault(True)
            apply_theme(self)

        self.body_layout.addWidget(self._content_widget)

    def load_request(
        self,
        request: InteractionRequest,
        queue_index: int = 1,
        queue_total: int = 1,
    ) -> None:
        """Present the given request in the modal and initiate native step resolution."""
        self.current_request = request
        self.lbl_status.setText("")

        # Update project badge
        ws = request.workspace_path
        project_name = Path(ws).name if ws else ""
        if project_name:
            self.lbl_project_badge.setText(f"📁 {project_name}")
            self.lbl_project_badge.setToolTip(ws or "")
            self.lbl_project_badge.setVisible(True)
        else:
            self.lbl_project_badge.setVisible(False)

        # Update header badge
        self.badge_count.setText(f"{queue_index} of {queue_total}")

        # Subtitle metadata (Project, Session, Model)
        sub_parts: list[str] = []
        if project_name:
            sub_parts.append(f"Project: {project_name}")
        sub_parts.append(f"Session: {request.conversation_id[:8]}...")
        if getattr(request, "model_name", None):
            sub_parts.append(f"Model: {request.model_name}")

        self.lbl_subtitle.setText(" • ".join(sub_parts))

        # Initial render based on hook trigger arguments
        self._render_content(request)
        self._loaded_timestamp = time.monotonic()
        self.adjustSize()

        # Handle native resolution & Enter guard state machine
        if getattr(self, "resolver", None) is not None:
            if request.state == InteractionState.NATIVE_WAITING_READY:
                self._set_buttons_enabled(True)
                self.lbl_status.setText("")
                if request.request_type == RequestType.PERMISSION:
                    self.btn_submit.setFocus()
                elif hasattr(self._content_widget, "set_initial_focus"):
                    self._content_widget.set_initial_focus()
                else:
                    self.btn_submit.setFocus()
            else:
                request.state = InteractionState.RESOLVING_NATIVE_STEP
                self._set_buttons_enabled(False)
                self.btn_dismiss.setEnabled(True)
                self.btn_close.setEnabled(True)
                self.lbl_status.setText("Resolving native interaction...")
                self._start_resolving_native_step(request)
        else:
            # Standalone mode without resolver attached (e.g. headless unit tests)
            request.state = InteractionState.NATIVE_WAITING_READY
            self._set_buttons_enabled(True)
            if request.request_type == RequestType.PERMISSION:
                self.btn_submit.setFocus()
            elif hasattr(self._content_widget, "set_initial_focus"):
                self._content_widget.set_initial_focus()
            else:
                self.btn_submit.setFocus()

    def _start_resolving_native_step(self, request: InteractionRequest) -> None:
        """Asynchronously resolve the authoritative WAITING step using progressive retries."""
        import threading

        def _worker(req_id: str, cascade_id: str, ws_path: str | None) -> None:
            try:
                res = self.resolver.resolve_authoritative_waiting_interaction(
                    cascade_id=cascade_id,
                    workspace_path=ws_path,
                    max_retries=10,
                )
                self.native_step_resolved.emit(req_id, res)
            except Exception as e:
                logger.warning("Failed in background resolution worker: %s", e)
                self.native_step_resolved.emit(req_id, None)

        t = threading.Thread(
            target=_worker,
            args=(request.request_id, request.conversation_id, request.workspace_path),
            daemon=True,
        )
        t.start()

    def _on_native_step_resolved(self, req_id: str, resolved_data: Any) -> None:
        """Main thread callback when background resolution finishes."""
        if not self.current_request or self.current_request.request_id != req_id:
            return

        if not resolved_data:
            self.current_request.state = InteractionState.FAILED
            self.lbl_status.setText("Waiting step not found. Press Submit to retry.")
            self.btn_submit.setEnabled(True)
            self.btn_deny.setEnabled(True)
            self.btn_allow_conversation.setEnabled(True)
            return

        self.current_request.trajectory_id = resolved_data.get("trajectory_id")
        self.current_request.step_index = resolved_data.get("step_index")

        if resolved_data.get("interaction_type") == InteractionType.ASK_QUESTION:
            native_questions = resolved_data.get("questions", [])
            if native_questions:
                updated_items = []
                for idx, nq in enumerate(native_questions):
                    native_opts = [
                        InteractionOption(id=opt.id, label=opt.text)
                        for opt in nq.options
                    ]
                    updated_items.append(
                        QuestionItem(
                            id=str(idx),
                            question=nq.question,
                            options=native_opts,
                            multi_select=nq.is_multi_select,
                            allow_custom_input=True,
                        )
                    )
                self.current_request.questions = updated_items
                if updated_items:
                    self.current_request.options = updated_items[0].options
                    self.current_request.multi_select = updated_items[0].multi_select

                # Re-render with authoritative native options!
                self._render_content(self.current_request)

        self.current_request.state = InteractionState.NATIVE_WAITING_READY
        self.lbl_status.setText("")
        self._set_buttons_enabled(True)

        if self.current_request.request_type == RequestType.PERMISSION:
            self.btn_submit.setFocus()
        elif hasattr(self._content_widget, "set_initial_focus"):
            self._content_widget.set_initial_focus()
        else:
            self.btn_submit.setFocus()

    def hide_to_tray(self) -> None:
        """Hide modal to tray without resolving the pending request."""
        logger.info("Modal hidden to tray by user (request remains pending)")
        if self.current_request:
            self.dismissed.emit(self.current_request.request_id)
        self.hide()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.btn_submit.setEnabled(enabled)
        self.btn_deny.setEnabled(enabled)
        self.btn_allow_conversation.setEnabled(enabled)
        self.btn_allow_global.setEnabled(enabled)
        self.btn_dismiss.setEnabled(enabled)
        self.btn_close.setEnabled(enabled)

    def submit_current_interaction(
        self,
        action_type: str = "submit",
        permission_scope: Any = None,
    ) -> None:
        """Unified submission controller for buttons, keys, and shortcuts."""
        interaction = self.current_request
        if not interaction:
            return

        # STRICT REQUIREMENT: Enter/Submit only accepted on NATIVE_WAITING_READY
        if interaction.state != InteractionState.NATIVE_WAITING_READY:
            logger.warning("Ignoring submit: native interaction is not ready (state: %s)", interaction.state)
            if interaction.state == InteractionState.FAILED:
                # Retry on Enter if in FAILED state
                interaction.state = InteractionState.RESOLVING_NATIVE_STEP
                self._set_buttons_enabled(False)
                self.btn_dismiss.setEnabled(True)
                self.btn_close.setEnabled(True)
                self.lbl_status.setText("Retrying native interaction resolution...")
                self._start_resolving_native_step(interaction)
            return

        interaction.state = InteractionState.SUBMITTING
        self._set_buttons_enabled(False)
        self.lbl_status.setText("Submitting...")

        req = interaction
        req_id = req.request_id
        is_perm = req.request_type == RequestType.PERMISSION

        # Native resolution if resolver is attached
        if getattr(self, "resolver", None) is not None:
            try:
                from ag_attention_bridge.antigravity.errors import InteractionStaleError
                from ag_attention_bridge.antigravity.models import PermissionScope

                scope = permission_scope or PermissionScope.PERMISSION_SCOPE_ONCE
                if is_perm:
                    allow = action_type != "deny"
                    self.resolver.submit_interaction(
                        cascade_id=req.conversation_id,
                        trajectory_id=req.trajectory_id,
                        step_index=req.step_index,
                        is_permission=True,
                        response_data={"allow": allow, "scope": scope},
                        workspace_path=req.workspace_path,
                    )
                    resp_val = "allow" if allow else "deny"
                else:
                    entries = (
                        self._content_widget.get_native_question_entries()
                        if isinstance(self._content_widget, QuestionView)
                        else []
                    )
                    self.resolver.submit_interaction(
                        cascade_id=req.conversation_id,
                        trajectory_id=req.trajectory_id,
                        step_index=req.step_index,
                        is_permission=False,
                        response_data=entries,
                        workspace_path=req.workspace_path,
                    )
                    resp_val = (
                        self._content_widget.get_answer()
                        if isinstance(self._content_widget, QuestionView)
                        else "acknowledged"
                    )

                interaction.state = InteractionState.SUBMITTED
                self.lbl_status.setText("Done")
                self.resolved.emit(req_id, resp_val)
                return

            except Exception as e:
                from ag_attention_bridge.antigravity.errors import InteractionStaleError
                if isinstance(e, InteractionStaleError):
                    interaction.state = InteractionState.STALE
                    self.lbl_status.setText("Interaction is stale or already answered.")
                    self.btn_dismiss.setEnabled(True)
                    self.btn_close.setEnabled(True)
                    # Auto-dismiss stale item after short delay
                    return
                else:
                    interaction.state = InteractionState.FAILED
                    self.lbl_status.setText(f"Failed: {e}")
                    self._set_buttons_enabled(True)
                    return

        # Fallback / standalone mode without resolver attached
        if is_perm:
            val = "deny" if action_type == "deny" else "allow"
        else:
            val = (
                self._content_widget.get_answer()
                if isinstance(self._content_widget, QuestionView)
                else "acknowledged"
            )

        interaction.state = InteractionState.SUBMITTED
        self.resolved.emit(req_id, val)

    def _on_submit_clicked(self) -> None:
        self.submit_current_interaction(action_type="submit")

    def _on_deny_clicked(self) -> None:
        self.submit_current_interaction(action_type="deny")

    def _on_allow_conversation_clicked(self) -> None:
        from ag_attention_bridge.antigravity.models import PermissionScope
        self.submit_current_interaction(
            action_type="allow",
            permission_scope=PermissionScope.PERMISSION_SCOPE_CONVERSATION,
        )

    def _on_allow_global_clicked(self) -> None:
        from ag_attention_bridge.antigravity.models import PermissionScope
        self.submit_current_interaction(
            action_type="allow",
            permission_scope=PermissionScope.PERMISSION_SCOPE_GLOBAL,
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard navigation: Esc hides; 1-9 shortcuts; Left/Right arrow; Enter submits."""
        if event.key() == Qt.Key.Key_Escape:
            # STRICT RULE: Esc NEVER rejects or resolves. It hides to tray.
            self.hide_to_tray()
            event.accept()
            return

        # Permission 1, 2, 3, 4 shortcuts and Left/Right arrow navigation
        if self.current_request and self.current_request.request_type == RequestType.PERMISSION:
            if event.key() == Qt.Key.Key_1:
                self._on_submit_clicked()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_2:
                self._on_allow_conversation_clicked()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_3:
                self._on_allow_global_clicked()
                event.accept()
                return
            elif event.key() in (Qt.Key.Key_4, Qt.Key.Key_D):
                self._on_deny_clicked()
                event.accept()
                return

            if event.key() == Qt.Key.Key_Left:
                if self.btn_submit.hasFocus():
                    self.btn_allow_conversation.setFocus()
                elif self.btn_allow_conversation.hasFocus():
                    self.btn_allow_global.setFocus()
                elif self.btn_allow_global.hasFocus():
                    self.btn_deny.setFocus()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Right:
                if self.btn_deny.hasFocus():
                    self.btn_allow_global.setFocus()
                elif self.btn_allow_global.hasFocus():
                    self.btn_allow_conversation.setFocus()
                elif self.btn_allow_conversation.hasFocus():
                    self.btn_submit.setFocus()
                event.accept()
                return

        # 1-9 direct option selection for questions
        if (
            self.current_request
            and self.current_request.request_type == RequestType.QUESTION
            and isinstance(self._content_widget, QuestionView)
        ):
            key = event.key()
            if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
                num = key - Qt.Key.Key_0
                if self._content_widget.handle_number_shortcut(num):
                    event.accept()
                    return

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Debounce rapid Enter presses across queued requests
            if time.monotonic() - getattr(self, "_loaded_timestamp", 0.0) < 0.2:
                event.accept()
                return

            if self.current_request and self.current_request.request_type == RequestType.PERMISSION:
                if self.btn_deny.hasFocus():
                    self._on_deny_clicked()
                elif self.btn_allow_global.hasFocus():
                    self._on_allow_global_clicked()
                elif self.btn_allow_conversation.hasFocus():
                    self._on_allow_conversation_clicked()
                else:
                    self.submit_current_interaction(action_type="allow")
            else:
                self.submit_current_interaction(action_type="submit")
            event.accept()
            return

        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Allow dragging the frameless window by clicking anywhere in the header."""
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 65:
            handle = self.windowHandle()
            if handle:
                handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """STRICT RULE: Window close button NEVER denies. It hides to tray."""
        event.ignore()
        self.hide_to_tray()
