"""Headless tests for UI components: QuestionView, PermissionView, and InteractionModal."""

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ag_attention_bridge.domain.models import (
    InteractionOption,
    InteractionRequest,
    QuestionItem,
    RequestType,
)
from ag_attention_bridge.ui.main_dialog import InteractionModal
from ag_attention_bridge.ui.permission_view import PermissionView
from ag_attention_bridge.ui.question_view import QuestionView


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_question_view_single_select(qapp):
    req = InteractionRequest(
        request_id="q-1",
        conversation_id="conv-1",
        request_type=RequestType.QUESTION,
        title="Choose a framework",
        body="Choose a framework",
        questions=[
            QuestionItem(
                id="0",
                question="Choose a framework",
                options=[
                    InteractionOption(id="0", label="FastAPI"),
                    InteractionOption(id="1", label="Django"),
                ],
                multi_select=False,
            )
        ],
    )

    view = QuestionView(req)
    assert view._sections[0].lbl_question.text() == "Choose a framework"
    # First option selected by default
    ans = view.get_answer()
    assert ans == [{"question": "Choose a framework", "selected": ["FastAPI"]}]

    # Select second option
    view._sections[0]._radio_buttons[1][0].setChecked(True)
    ans2 = view.get_answer()
    assert ans2 == [{"question": "Choose a framework", "selected": ["Django"]}]

    # Custom write-in overrides
    assert view._sections[0]._custom_input is not None
    view._sections[0]._custom_input.setText("Flask")
    ans3 = view.get_answer()
    assert ans3 == [{"question": "Choose a framework", "selected": ["Flask"]}]


def test_question_view_multi_select(qapp):
    req = InteractionRequest(
        request_id="q-2",
        conversation_id="conv-1",
        request_type=RequestType.QUESTION,
        title="Select packages",
        body="Select packages",
        questions=[
            QuestionItem(
                id="0",
                question="Select packages",
                options=[
                    InteractionOption(id="0", label="pytest"),
                    InteractionOption(id="1", label="black"),
                    InteractionOption(id="2", label="ruff"),
                ],
                multi_select=True,
            )
        ],
    )

    view = QuestionView(req)
    # None checked initially
    assert view.get_answer() == [{"question": "Select packages", "selected": []}]

    # Check 1 and 3
    view._sections[0]._checkboxes[0][0].setChecked(True)
    view._sections[0]._checkboxes[2][0].setChecked(True)
    assert view.get_answer() == [{"question": "Select packages", "selected": ["pytest", "ruff"]}]


def test_permission_view(qapp):
    req = InteractionRequest(
        request_id="p-1",
        conversation_id="conv-1",
        request_type=RequestType.PERMISSION,
        title="Permission Request: run_command",
        body="Target: npm run build\nReason: Compile frontend bundle",
    )

    view = PermissionView(req)
    assert view.badge_action.text() == "run_command"
    assert "npm run build" in view.lbl_target.text()
    assert "Compile frontend bundle" in view.lbl_reason.text()


def test_interaction_modal_esc_hide(qapp):
    modal = InteractionModal()
    dismissed_ids = []
    modal.dismissed.connect(lambda req_id: dismissed_ids.append(req_id))

    req = InteractionRequest(
        request_id="req-esc-test",
        conversation_id="conv-1",
        request_type=RequestType.QUESTION,
        title="Question",
        body="Question",
        options=[InteractionOption(id="0", label="Yes")],
    )

    modal.load_request(req)
    modal.show()

    # Simulate pressing Escape
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    modal.keyPressEvent(event)

    assert not modal.isVisible()
    assert dismissed_ids == ["req-esc-test"]


def test_interaction_modal_close_event(qapp):
    modal = InteractionModal()
    dismissed_ids = []
    modal.dismissed.connect(lambda req_id: dismissed_ids.append(req_id))

    req = InteractionRequest(
        request_id="req-close-test",
        conversation_id="conv-1",
        request_type=RequestType.QUESTION,
        title="Question",
        body="Question",
        options=[InteractionOption(id="0", label="Yes")],
    )

    modal.load_request(req)
    modal.show()

    # Trigger close
    modal.close()

    assert not modal.isVisible()
    assert dismissed_ids == ["req-close-test"]


def test_interaction_modal_submit(qapp):
    modal = InteractionModal()
    resolved_data = []
    modal.resolved.connect(lambda req_id, val: resolved_data.append((req_id, val)))

    req = InteractionRequest(
        request_id="req-submit-test",
        conversation_id="conv-1",
        request_type=RequestType.QUESTION,
        title="Pick one",
        body="Pick one",
        options=[
            InteractionOption(id="0", label="Alpha"),
            InteractionOption(id="1", label="Beta"),
        ],
    )

    modal.load_request(req)
    # Default is Alpha
    modal.btn_submit.click()

    assert len(resolved_data) == 1
    assert resolved_data[0][0] == "req-submit-test"
    assert resolved_data[0][1] == [{"question": "Pick one", "selected": ["Alpha"]}]


def test_interaction_modal_permission_actions(qapp):
    modal = InteractionModal()
    resolved_data = []
    modal.resolved.connect(lambda req_id, val: resolved_data.append((req_id, val)))

    req = InteractionRequest(
        request_id="req-perm-test",
        conversation_id="conv-1",
        request_type=RequestType.PERMISSION,
        title="Permission Request: run_command",
        body="Target: rm -rf /tmp/test\nReason: Cleanup",
    )

    modal.load_request(req)
    modal.show()
    assert modal.btn_deny.isVisible()

    # Click allow
    modal.btn_submit.click()
    assert resolved_data == [("req-perm-test", "allow")]

    # Click deny on new request
    req2 = InteractionRequest(
        request_id="req-perm-test-2",
        conversation_id="conv-1",
        request_type=RequestType.PERMISSION,
        title="Permission Request: run_command",
        body="Target: rm -rf /tmp/test\nReason: Cleanup",
    )
    modal.load_request(req2)
    modal.btn_deny.click()
    assert resolved_data[1] == ("req-perm-test-2", "deny")
