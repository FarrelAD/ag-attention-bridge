"""Pytest configuration and platform-aware fixtures for Ag Attention Bridge."""

import os
import sys

import pytest

# Ensure QT offscreen platform for headless testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Auto-skip Unix Domain Socket and Linux-specific /proc tests when executed on Windows
@pytest.fixture(autouse=True)
def skip_linux_only_tests_on_windows(request):
    if sys.platform == "win32":
        # Tests that rely on Unix domain socket files (.sock on filesystem) or /proc
        linux_only_modules = {
            "test_ipc",
            "test_native_flow",
            "test_permission_bridge",
            "test_phase_verification",
            "test_question_bridge",
            "test_response_flow",
        }
        if request.module.__name__.split(".")[-1] in linux_only_modules:
            pytest.skip(
                "Linux / KDE Plasma Wayland integration test (requires Unix domain socket file & /proc)"
            )
