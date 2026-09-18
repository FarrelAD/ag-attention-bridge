#!/usr/bin/env python3
"""Interactive visual demo runner for Ag Attention Bridge InteractionModal.

Run directly on your desktop to inspect the premium AI assistant modal UI,
test keyboard navigation, and verify Esc/hide-to-tray behavior.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ag_attention_bridge.domain.models import (
    InteractionOption,
    InteractionRequest,
    RequestType,
)
from ag_attention_bridge.ui.main_dialog import InteractionModal
from ag_attention_bridge.ui.tray import AttentionTrayIcon


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Sample requests
    question_req = InteractionRequest(
        request_id="demo-question-1",
        conversation_id="conv-demo-plasma-6",
        request_type=RequestType.QUESTION,
        title="Which web framework architecture would you prefer for the new API?",
        body="Which web framework architecture would you prefer for the new API?",
        options=[
            InteractionOption(id="1", label="FastAPI (Asynchronous, High Throughput, OpenAPI built-in)"),
            InteractionOption(id="2", label="Go / Gin (Compiled, Extremely Low Memory Footprint)"),
            InteractionOption(id="3", label="Rust / Axum (Zero Cost Abstractions, Memory Safe)"),
        ],
        multi_select=False,
    )

    permission_req = InteractionRequest(
        request_id="demo-perm-2",
        conversation_id="conv-demo-plasma-6",
        request_type=RequestType.PERMISSION,
        title="Permission Request: run_command",
        body="Target: git push origin feat/kde-attention-bridge --force-with-lease\nReason: Publish feature branch with atomic commits for peer review",
    )

    queue = [question_req, permission_req]
    current_idx = 0

    modal = InteractionModal()

    def load_current():
        if current_idx < len(queue):
            req = queue[current_idx]
            modal.load_request(req, queue_index=current_idx + 1, queue_total=len(queue))
            modal.show()
            modal.raise_()
            modal.activateWindow()
        else:
            print("[Demo] All requests answered! Closing demo.")
            app.quit()

    def on_resolved(req_id: str, value: object):
        nonlocal current_idx
        print(f"[Demo] Resolved {req_id} -> Result: {value}")
        current_idx += 1
        load_current()

    def on_dismissed(req_id: str):
        print(f"[Demo] Request {req_id} dismissed to tray (remains pending). Click tray icon to restore.")

    modal.resolved.connect(on_resolved)
    modal.dismissed.connect(on_dismissed)

    # System Tray
    tray = AttentionTrayIcon(
        on_open_pending=lambda: modal.show() or modal.raise_() or modal.activateWindow(),
        on_toggle_current=lambda: modal.hide_to_tray() if modal.isVisible() else modal.show(),
    )
    tray.update_badge(len(queue))
    tray.show()

    load_current()

    print("\n--- Ag Attention Bridge Visual Demo Running ---")
    print("* Press Tab / Arrow keys to navigate options")
    print("* Press Enter to Submit / Allow")
    print("* Press Esc or click 'X' to hide to tray (click tray icon to restore)")
    print("------------------------------------------------\n")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
