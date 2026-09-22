"""Pytest configuration and platform-aware fixtures for Ag Attention Bridge."""

import os
import sys

import pytest

# Ensure QT offscreen platform for headless testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Tests that strictly require POSIX /proc filesystem if not mocked
LINUX_PROC_TESTS = {
    # None currently; all mock discovery or use platform abstraction
}


@pytest.fixture(autouse=True)
def skip_linux_only_tests_on_windows(request):
    if sys.platform == "win32":
        mod_name = request.module.__name__.split(".")[-1]
        if mod_name in LINUX_PROC_TESTS:
            pytest.skip("Test requires Linux /proc filesystem")
