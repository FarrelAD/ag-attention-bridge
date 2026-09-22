"""Unit tests for AntigravityProcessWatcher."""

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from ag_attention_bridge.state.watcher import (
    AntigravityProcessWatcher,
    is_antigravity_running,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_is_antigravity_running_real_system():
    # Non-existent process returns False
    assert is_antigravity_running("completely_fake_process_name_9999") is False


def test_antigravity_process_watcher_signal(qapp, monkeypatch):
    # Simulate Antigravity not running
    monkeypatch.setattr(
        "ag_attention_bridge.state.watcher.is_antigravity_running",
        lambda *args: False,
    )

    exited_signals = []
    watcher = AntigravityProcessWatcher(check_interval_ms=20, max_missing_count=2)
    watcher.antigravity_exited.connect(lambda: exited_signals.append(True))

    watcher.start()

    # Process events to let timer fire twice
    import time

    for _ in range(10):
        QCoreApplication.processEvents()
        if exited_signals:
            break
        time.sleep(0.02)

    watcher.stop()
    assert len(exited_signals) == 1
