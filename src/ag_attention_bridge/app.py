
"""Main application entry point for Ag Attention Bridge daemon."""

from __future__ import annotations

import fcntl
import logging
import os
import signal
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ag_attention_bridge.config import get_xdg_runtime_dir, get_xdg_state_dir
from ag_attention_bridge.domain.models import InteractionRequest
from ag_attention_bridge.ipc.server import IpcServer
from ag_attention_bridge.state.store import RequestQueue, SessionStore
from ag_attention_bridge.ui.tray import AttentionTrayIcon

logger = logging.getLogger("ag_attention_bridge.app")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def acquire_instance_lock() -> int | None:
    """Acquire exclusive single-instance lock file. Returns fd if acquired, None if another instance runs."""
    lock_path = get_xdg_runtime_dir() / "ag-attention-bridge.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError):
        return None


def handle_signals(app: QApplication, server: IpcServer | None = None) -> None:
    """Allow Python signal handlers (SIGINT, SIGTERM) to interrupt Qt loop."""
    def _clean_quit():
        if server:
            server.stop()
        app.quit()

    signal.signal(signal.SIGINT, lambda *_: _clean_quit())
    signal.signal(signal.SIGTERM, lambda *_: _clean_quit())

    timer = QTimer()
    timer.timeout.connect(lambda: None)  # Wake up Python interpreter
    timer.start(500)
    # Retain reference to prevent garbage collection
    app._sig_timer = timer  # type: ignore


def main() -> int:
    setup_logging()

    # STRICT SINGLE INSTANCE GUARD:
    # Never allow more than 1 daemon process per user desktop session!
    lock_fd = acquire_instance_lock()
    if lock_fd is None:
        logger.warning("Another instance of Ag Attention Bridge is already running. Exiting redundant instance.")
        return 0

    logger.info("Starting Ag Attention Bridge daemon...")

    # Ensure state directory exists
    get_xdg_state_dir()

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("ag-attention-bridge")
    app.setDesktopFileName("ag-attention-bridge")
    app.setQuitOnLastWindowClosed(False)

    # State stores
    sessions = SessionStore()
    queue = RequestQueue()

    # Antigravity Native Interaction Resolver
    from ag_attention_bridge.antigravity.interaction_resolver import InteractionResolver
    resolver = InteractionResolver()

    # Interaction Modal
    from ag_attention_bridge.ui.main_dialog import InteractionModal

    modal = InteractionModal()
    modal.set_resolver(resolver)

    def present_active():
        active = queue.get_active()
        if active:
            modal.load_request(active, queue_index=1, queue_total=queue.count())
            modal.show()
            modal.raise_()
            modal.activateWindow()
        else:
            modal.hide()

    def on_modal_resolved(request_id: str, response_val: Any):
        logger.info("Modal resolved request %s with: %s", request_id, response_val)
        server.resolve_request(request_id, response_val)
        present_active()

    def on_modal_dismissed(request_id: str):
        logger.info("Modal dismissed request %s to tray", request_id)
        queue.dismiss_to_tray(request_id)

    modal.resolved.connect(on_modal_resolved)
    modal.dismissed.connect(on_modal_dismissed)

    # System tray icon
    def on_open_pending():
        if modal.isVisible():
            modal.raise_()
            modal.activateWindow()
        else:
            present_active()

    def on_toggle_current():
        if modal.isVisible():
            modal.hide_to_tray()
        else:
            present_active()

    tray = AttentionTrayIcon(
        on_open_pending=on_open_pending,
        on_toggle_current=on_toggle_current,
    )
    tray.show()

    # Auto-synchronize queue count changes with tray badge and modal header
    def on_count_updated(count: int):
        tray.update_badge(count)
        if modal.isVisible() and modal.current_request:
            modal.badge_count.setText(f"1 of {count}")

    queue._on_count_changed = on_count_updated

    # IPC Server
    server = IpcServer(queue=queue, sessions=sessions, resolver=resolver)
    if not server.start():
        logger.error("Could not start IPC server. Exiting.")
        return 1

    def on_request_received(req: InteractionRequest):
        logger.info("New interaction request received: [%s] %s", req.request_id, req.title)
        if not modal.isVisible():
            present_active()
        else:
            modal.badge_count.setText(f"1 of {queue.count()}")

    server.request_received.connect(on_request_received)

    # Process watcher: auto-shutdown when Antigravity IDE is closed
    import argparse
    parser = argparse.ArgumentParser(description="Ag Attention Bridge Daemon")
    parser.add_argument("--no-watch", action="store_true", help="Disable auto-shutdown when Antigravity exits")
    args, _ = parser.parse_known_args()

    if not args.no_watch:
        from ag_attention_bridge.state.watcher import AntigravityProcessWatcher
        watcher = AntigravityProcessWatcher(check_interval_ms=10000, max_missing_count=2, parent=app)
        watcher.antigravity_exited.connect(app.quit)
        watcher.start()
        app.aboutToQuit.connect(watcher.stop)

    logger.info("Ag Attention Bridge daemon running. Modal UI, IPC server, and System tray ready.")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
