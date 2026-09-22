"""Permission view component for ask_permission interactions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ag_attention_bridge.domain.models import InteractionRequest


class PermissionView(QWidget):
    """Widget presenting structured permission request details (Action, Target, Reason)."""

    def __init__(self, request: InteractionRequest, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.request = request
        self._action_name = "action"
        self._target_text = ""
        self._reason_text = ""

        self._parse_details()
        self._setup_ui()

    def _parse_details(self) -> None:
        """Extract action, target, and reason from request body or title."""
        # Body format: "Target: ... \nReason: ..."
        lines = self.request.body.splitlines()
        target_lines = []
        reason_lines = []
        current_section = None

        for line in lines:
            if line.startswith("Target:"):
                current_section = "target"
                val = line[len("Target:") :].strip()
                if val:
                    target_lines.append(val)
            elif line.startswith("Reason:"):
                current_section = "reason"
                val = line[len("Reason:") :].strip()
                if val:
                    reason_lines.append(val)
            else:
                if current_section == "target":
                    target_lines.append(line)
                elif current_section == "reason":
                    reason_lines.append(line)

        self._target_text = "\n".join(target_lines).strip() or self.request.title
        self._reason_text = "\n".join(reason_lines).strip()

        # Action from title
        if "Permission Request:" in self.request.title:
            self._action_name = self.request.title.split("Permission Request:", 1)[1].strip()
        else:
            self._action_name = "Permission"

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # Action Header row
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        lbl_action_tag = QLabel("ACTION REQUIRED", self)
        lbl_action_tag.setStyleSheet(
            "color: #94a3b8; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;"
        )
        lbl_action_tag.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(lbl_action_tag, 0, Qt.AlignmentFlag.AlignVCenter)

        self.badge_action = QLabel(self._action_name, self)
        self.badge_action.setObjectName("PermissionActionBadge")
        self.badge_action.setFixedHeight(24)
        self.badge_action.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.badge_action.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_row.addWidget(self.badge_action, 0, Qt.AlignmentFlag.AlignVCenter)
        header_row.addStretch()

        layout.addLayout(header_row)

        # Monospace Target Box
        target_box = QFrame(self)
        target_box.setObjectName("MonospaceTargetBox")
        target_layout = QVBoxLayout(target_box)
        target_layout.setContentsMargins(12, 10, 12, 10)

        lbl_target_heading = QLabel("TARGET / COMMAND", target_box)
        lbl_target_heading.setStyleSheet(
            "color: #64748b; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;"
        )
        target_layout.addWidget(lbl_target_heading)

        self.lbl_target = QLabel(self._target_text, target_box)
        self.lbl_target.setObjectName("MonospaceTargetText")
        self.lbl_target.setWordWrap(True)
        self.lbl_target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        target_layout.addWidget(self.lbl_target)

        layout.addWidget(target_box)

        # Reason section if present
        if self._reason_text:
            reason_box = QFrame(self)
            reason_layout = QVBoxLayout(reason_box)
            reason_layout.setContentsMargins(0, 2, 0, 2)
            reason_layout.setSpacing(4)

            lbl_reason_heading = QLabel("REASON", reason_box)
            lbl_reason_heading.setStyleSheet(
                "color: #94a3b8; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;"
            )
            reason_layout.addWidget(lbl_reason_heading)

            self.lbl_reason = QLabel(self._reason_text, reason_box)
            self.lbl_reason.setObjectName("ReasonText")
            self.lbl_reason.setWordWrap(True)
            reason_layout.addWidget(self.lbl_reason)

            layout.addWidget(reason_box)

        layout.addStretch(1)

    def set_initial_focus(self) -> None:
        """Allow focusing target text or first control."""
        self.lbl_target.setFocus()
