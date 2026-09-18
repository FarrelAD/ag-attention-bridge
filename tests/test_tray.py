"""Tests for system tray icon and badge rendering."""

import os
import pytest

# Ensure headless execution for Qt in CI / test runner
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from ag_attention_bridge.ui.tray import AttentionTrayIcon, create_badged_icon


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_create_badged_icon_zero(qapp):
    icon = create_badged_icon(0)
    assert not icon.isNull()
    pixmap = icon.pixmap(64, 64)
    assert not pixmap.isNull()
    assert pixmap.width() == 64
    assert pixmap.height() == 64


def test_create_badged_icon_positive(qapp):
    icon = create_badged_icon(5)
    assert not icon.isNull()
    pixmap = icon.pixmap(64, 64)
    assert not pixmap.isNull()


def test_create_badged_icon_large_count(qapp):
    icon = create_badged_icon(120)
    assert not icon.isNull()


def test_attention_tray_icon_state(qapp):
    opened = False
    toggled = False

    def on_open():
        nonlocal opened
        opened = True

    def on_toggle():
        nonlocal toggled
        toggled = True

    tray = AttentionTrayIcon(
        on_open_pending=on_open,
        on_toggle_current=on_toggle,
    )

    assert tray.pending_count == 0
    assert "Idle" in tray.toolTip()

    tray.update_badge(3)
    assert tray.pending_count == 3
    assert "3 pending" in tray.toolTip()
    assert "3" in tray.action_pending.text()

    # Verify action callback
    tray._handle_open_pending()
    assert opened is True

    tray._handle_toggle_current()
    assert toggled is True
