"""Question view component for ask_question interactions (single and multi-question)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ag_attention_bridge.antigravity.models import QuestionEntry, QuestionOption
from ag_attention_bridge.domain.models import InteractionOption, InteractionRequest, QuestionItem


class QuestionSectionWidget(QWidget):
    """Widget rendering a single question section with its options and custom input."""

    def __init__(
        self,
        question_item: QuestionItem,
        index: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.question_item = question_item
        self.index = index
        self._button_group: QButtonGroup | None = None
        self._checkboxes: list[tuple[QCheckBox, InteractionOption]] = []
        self._radio_buttons: list[tuple[QRadioButton, InteractionOption]] = []
        self._custom_input: QLineEdit | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Question title
        prefix = f"{self.index}. " if self.index is not None else ""
        self.lbl_question = QLabel(f"{prefix}{self.question_item.question}", self)
        self.lbl_question.setObjectName("QuestionTitle")
        self.lbl_question.setWordWrap(True)
        layout.addWidget(self.lbl_question)

        # Options Container
        options_frame = QFrame(self)
        options_layout = QVBoxLayout(options_frame)
        options_layout.setContentsMargins(0, 2, 0, 2)
        options_layout.setSpacing(8)

        if not self.question_item.multi_select:
            # Single select (Radio buttons)
            self._button_group = QButtonGroup(self)
            for idx, opt in enumerate(self.question_item.options):
                # Include index prefix e.g. [1] Option Text for fast keyboard UX
                num_hint = f"{idx + 1}. " if idx < 9 else ""
                rb = QRadioButton(f"{num_hint}{opt.label}", options_frame)
                rb.setCursor(Qt.CursorShape.PointingHandCursor)
                self._button_group.addButton(rb, idx)
                options_layout.addWidget(rb)
                self._radio_buttons.append((rb, opt))

            # Select first option by default
            if self._radio_buttons:
                self._radio_buttons[0][0].setChecked(True)
        else:
            # Multi select (Checkboxes)
            for idx, opt in enumerate(self.question_item.options):
                num_hint = f"{idx + 1}. " if idx < 9 else ""
                cb = QCheckBox(f"{num_hint}{opt.label}", options_frame)
                cb.setCursor(Qt.CursorShape.PointingHandCursor)
                options_layout.addWidget(cb)
                self._checkboxes.append((cb, opt))

        layout.addWidget(options_frame)

        # Optional Freeform Write-in Input
        if self.question_item.allow_custom_input:
            custom_box = QFrame(self)
            custom_layout = QVBoxLayout(custom_box)
            custom_layout.setContentsMargins(0, 2, 0, 0)
            custom_layout.setSpacing(4)

            lbl_custom = QLabel("Or write custom response:", custom_box)
            lbl_custom.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500;")
            custom_layout.addWidget(lbl_custom)

            self._custom_input = QLineEdit(custom_box)
            self._custom_input.setPlaceholderText("Type answer here...")
            custom_layout.addWidget(self._custom_input)

            layout.addWidget(custom_box)

    def set_focus(self) -> None:
        if self._radio_buttons:
            self._radio_buttons[0][0].setFocus()
        elif self._checkboxes:
            self._checkboxes[0][0].setFocus()
        elif self._custom_input:
            self._custom_input.setFocus()

    def select_by_number(self, num: int) -> bool:
        """Select option by 1-based index (e.g. key 1-9)."""
        idx = num - 1
        if not self.question_item.multi_select:
            if 0 <= idx < len(self._radio_buttons):
                self._radio_buttons[idx][0].setChecked(True)
                self._radio_buttons[idx][0].setFocus()
                return True
        else:
            if 0 <= idx < len(self._checkboxes):
                cb = self._checkboxes[idx][0]
                cb.setChecked(not cb.isChecked())
                cb.setFocus()
                return True
        return False

    def get_selected_option_ids(self) -> list[str]:
        """Return native option IDs selected by the user."""
        if not self.question_item.multi_select:
            for rb, opt in self._radio_buttons:
                if rb.isChecked():
                    return [opt.id]
            return [self.question_item.options[0].id] if self.question_item.options else []
        else:
            return [opt.id for cb, opt in self._checkboxes if cb.isChecked()]

    def get_write_in_response(self) -> str:
        """Return freeform custom text entered by user."""
        return self._custom_input.text().strip() if self._custom_input else ""

    def get_selected(self) -> list[str]:
        """Legacy helper returning selected option text or custom input for backward compatibility."""
        custom_text = self.get_write_in_response()
        if not self.question_item.multi_select:
            if custom_text:
                return [custom_text]
            for rb, opt in self._radio_buttons:
                if rb.isChecked():
                    return [opt.label]
            return [self.question_item.options[0].label] if self.question_item.options else []
        else:
            selected = [opt.label for cb, opt in self._checkboxes if cb.isChecked()]
            if custom_text:
                selected.append(custom_text)
            return selected

    def to_question_entry(self) -> QuestionEntry:
        """Construct native QuestionEntry for HandleCascadeUserInteraction."""
        opts = [QuestionOption(id=opt.id, text=opt.label) for opt in self.question_item.options]
        selected_ids = self.get_selected_option_ids()
        write_in = self.get_write_in_response()

        # If user typed custom input in single select without picking radio, option IDs can be empty
        if write_in and not self.question_item.multi_select:
            selected_ids = []

        return QuestionEntry(
            question=self.question_item.question,
            options=opts,
            is_multi_select=self.question_item.multi_select,
            selected_option_ids=selected_ids,
            write_in_response=write_in,
            skipped=False,
        )


class QuestionView(QWidget):
    """Widget presenting one or multiple structured questions."""

    def __init__(self, request: InteractionRequest, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.request = request
        self._sections: list[QuestionSectionWidget] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        questions = self.request.questions
        if not questions:
            # Fallback to single question constructed from request title/options
            q_item = QuestionItem(
                id="0",
                question=self.request.title,
                options=self.request.options,
                multi_select=self.request.multi_select,
                allow_custom_input=self.request.allow_custom_input,
            )
            questions = [q_item]

        is_multiple = len(questions) > 1
        for idx, q_item in enumerate(questions, 1):
            section = QuestionSectionWidget(
                q_item,
                index=idx if is_multiple else None,
                parent=self,
            )
            layout.addWidget(section)
            self._sections.append(section)

        layout.addStretch(1)

    def set_initial_focus(self) -> None:
        if self._sections:
            self._sections[0].set_focus()

    def handle_number_shortcut(self, num: int) -> bool:
        """Forward number shortcut 1-9 to first section if text input is not active."""
        if not self._sections:
            return False
        # Do not hijack if user is typing in custom input
        focus_w = self.focusWidget()
        if isinstance(focus_w, QLineEdit):
            return False
        return self._sections[0].select_by_number(num)

    def get_answer(self) -> list[dict[str, Any]]:
        """Return structured answers for all questions (backward compatibility)."""
        result = []
        for section in self._sections:
            selected = section.get_selected()
            result.append(
                {
                    "question": section.question_item.question,
                    "selected": selected,
                }
            )
        return result

    def get_native_question_entries(self) -> list[QuestionEntry]:
        """Return list of native QuestionEntry models for RPC submission."""
        return [section.to_question_entry() for section in self._sections]
