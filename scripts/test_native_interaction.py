#!/usr/bin/env python3
"""CLI Interactive Testing Script for Antigravity Native Interaction Pathway.

Demonstrates and verifies direct ConnectRPC interaction submission to:
POST /exa.language_server_pb.LanguageServerService/HandleCascadeUserInteraction

Usage:
    python scripts/test_native_interaction.py [--cascade-id <id>] [--workspace <path>]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from ag_attention_bridge.antigravity.client import AntigravityClient
from ag_attention_bridge.antigravity.discovery import AntigravityDiscovery
from ag_attention_bridge.antigravity.models import (
    PermissionScope,
    QuestionEntry,
    QuestionOption,
)


def print_banner() -> None:
    print("=" * 70)
    print("   AG ATTENTION BRIDGE — NATIVE INTERACTION CLI TEST")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fast test utility for native Antigravity interaction RPC"
    )
    parser.add_argument(
        "--cascade-id",
        type=str,
        default=None,
        help="Target cascade ID (conversationId). If omitted, active cascades will be queried.",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Workspace path to filter language server process.",
    )
    parser.add_argument(
        "--select-option-id",
        type=str,
        default=None,
        help="Option ID to select (non-interactive mode).",
    )
    parser.add_argument(
        "--allow",
        action="store_true",
        help="Auto-allow permission in non-interactive mode.",
    )
    parser.add_argument(
        "--deny",
        action="store_true",
        help="Auto-deny permission in non-interactive mode.",
    )

    args = parser.parse_args()
    print_banner()

    # 1. Discover Active Language Server
    print("[1/5] Discovering active Antigravity Language Server processes...")
    discovery = AntigravityDiscovery()
    servers = discovery.discover_servers()

    if not servers:
        print("[-] ERROR: No active Antigravity Language Server process found.")
        print("    Ensure Google Antigravity is running with an open workspace.")
        return 1

    server = None
    if args.workspace:
        server = discovery.find_server_for_workspace(args.workspace)
        if not server:
            print(f"[-] No server found specifically for workspace '{args.workspace}'. Using first available.")
            server = servers[0]
    else:
        server = servers[0]

    print(f"[+] Found Language Server:")
    print(f"    • PID:            {server.pid}")
    print(f"    • HTTPS Port:     {server.https_port}")
    print(f"    • Workspace ID:   {server.workspace_id}")
    print(f"    • CSRF Token:     {server.masked_csrf_token}")

    client = AntigravityClient(server)

    # 2. Heartbeat check
    print("\n[2/5] Testing server connection...")
    try:
        hb = client.heartbeat()
        print(f"[+] Heartbeat OK: {hb}")
    except Exception as e:
        print(f"[-] Failed to connect to Language Server at {server.base_url}: {e}")
        return 1

    # 3. Locate Target Cascade
    cascade_id = args.cascade_id
    if not cascade_id:
        print("\n[3/5] Querying active conversations in workspace...")
        conversations = client.search_conversations()
        if not conversations:
            print("[-] No conversations found in this workspace.")
            cascade_id = input("    Please enter cascade ID manually: ").strip()
            if not cascade_id:
                print("[-] No cascade ID provided. Exiting.")
                return 1
        else:
            print(f"[+] Found {len(conversations)} conversation(s):")
            for idx, conv in enumerate(conversations[:8], 1):
                c_id = conv.get("cascadeId", "")
                title = conv.get("title") or conv.get("summary") or "[No Title]"
                print(f"    [{idx}] {title[:40]:<40} (ID: {c_id})")

            # Check if any conversation currently has a waiting step
            found_waiting = False
            for conv in conversations[:5]:
                c_id = conv.get("cascadeId", "")
                waiting = client.find_waiting_interaction(c_id, max_retries=1)
                if waiting:
                    cascade_id = c_id
                    found_waiting = True
                    print(f"\n[+] Auto-detected live WAITING step in conversation: {c_id}")
                    break

            if not found_waiting:
                choice = input("\n    Select conversation number [1] or enter cascade ID: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(conversations):
                    cascade_id = conversations[int(choice) - 1]["cascadeId"]
                elif choice:
                    cascade_id = choice
                else:
                    cascade_id = conversations[0]["cascadeId"]

    print(f"\n[+] Target Cascade ID: {cascade_id}")

    # 4. Detect Waiting Step
    print("\n[4/5] Inspecting trajectory for WAITING interactions...")
    waiting = client.find_waiting_interaction(cascade_id, max_retries=3)

    if not waiting:
        print(f"[-] No step in status 'WAITING' found in cascade {cascade_id}.")
        print("    To test live interaction, trigger a question in Antigravity chat, e.g.:")
        print('    "Ask me which database to use: PostgreSQL or SQLite, and wait for answer."')
        return 0

    traj_id, step_idx, step_data = waiting
    step_type = step_data.get("type", "UNKNOWN")
    short_traj = f"{traj_id[:8]}...{traj_id[-4:]}" if len(traj_id) > 12 else traj_id

    print(f"[+] Waiting Step Located!")
    print(f"    • Trajectory ID:  {short_traj}")
    print(f"    • Step Index:     {step_idx}")
    print(f"    • Step Type:      {step_type}")

    # Check for askQuestion
    ask_q = step_data.get("askQuestion") or step_data.get("ask_question")
    perm = step_data.get("permission") or step_data.get("runCommand") or step_data.get("filePermission")

    if ask_q:
        raw_questions = ask_q.get("questions", [])
        if not raw_questions:
            print("[-] askQuestion step has no questions array.")
            return 1

        first_q = raw_questions[0]
        q_text = first_q.get("question", "")
        options = first_q.get("options", [])
        is_multi = first_q.get("isMultiSelect", False)

        print(f"\n    Question: {q_text}")
        print(f"    Multi-select: {is_multi}")
        print("    Available Options:")
        for idx, opt in enumerate(options, 1):
            opt_id = opt.get("id", str(idx))
            opt_text = opt.get("text", opt.get("label", ""))
            print(f"      [{idx}] (ID: {opt_id}) {opt_text}")

        # Selection
        selected_id = args.select_option_id
        write_in = ""
        if not selected_id:
            user_in = input("\n    Select option number (or type custom answer): ").strip()
            if user_in.isdigit() and 1 <= int(user_in) <= len(options):
                selected_id = options[int(user_in) - 1]["id"]
            elif user_in:
                write_in = user_in
                selected_id = options[0]["id"] if options else "0"
            else:
                selected_id = options[0]["id"] if options else "0"

        print(f"\n[5/5] Submitting native response via HandleCascadeUserInteraction...")
        q_entry = QuestionEntry(
            question=q_text,
            options=[QuestionOption(id=o.get("id", str(i)), text=o.get("text", "")) for i, o in enumerate(options)],
            is_multi_select=is_multi,
            selected_option_ids=[selected_id] if not write_in else [],
            write_in_response=write_in,
            skipped=False,
        )

        payload = client.build_ask_question_payload(traj_id, step_idx, [q_entry])
        print(f"    Payload: {json.dumps(payload, indent=2)}")

        t0 = time.perf_counter()
        resp = client.handle_cascade_user_interaction(cascade_id, payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[+] RPC Response (in {elapsed_ms:.1f}ms): {resp}")

    elif perm:
        print(f"\n    Permission details: {perm}")
        allow = True
        if args.deny:
            allow = False
        elif not args.allow:
            choice = input("\n    Decision (a=Allow Once, d=Deny) [a]: ").strip().lower()
            allow = choice != "d"

        print(f"\n[5/5] Submitting native permission decision (allow={allow})...")
        payload = client.build_permission_payload(
            traj_id,
            step_idx,
            allow=allow,
            scope=PermissionScope.PERMISSION_SCOPE_ONCE,
        )
        print(f"    Payload: {json.dumps(payload, indent=2)}")

        t0 = time.perf_counter()
        resp = client.handle_cascade_user_interaction(cascade_id, payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[+] RPC Response (in {elapsed_ms:.1f}ms): {resp}")

    else:
        print(f"[-] Unrecognized interaction structure in step: {list(step_data.keys())}")
        return 1

    # Verify trajectory state
    print("\nVerifying step transition...")
    time.sleep(0.5)
    still_waiting = client.find_waiting_interaction(cascade_id, max_retries=1)
    if still_waiting and still_waiting[1] == step_idx:
        print("[-] Notice: Step still reported as WAITING (may take a moment to transition).")
    else:
        print("[+] SUCCESS: Step unblocked! Antigravity has resumed the trajectory natively.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
