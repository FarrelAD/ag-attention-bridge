# Native Antigravity Interaction Implementation

## 1. Overview

**Ag Attention Bridge** surfaces Antigravity interactions (`ask_question`, permissions, approvals) as always-on-top KDE Wayland dialogs and resolves them via **Antigravity's native interaction pathway** over localhost ConnectRPC:

```text
POST https://127.0.0.1:<https_server_port>/exa.language_server_pb.LanguageServerService/HandleCascadeUserInteraction
Headers:
  Content-Type: application/json
  x-codeium-csrf-token: <dynamic_csrf_token>
```

This delivers user decisions directly into Antigravity's internal Go runtime channel (`agent.InteractionRequester`) within ~3–5ms, continuing the existing agent trajectory without emitting synthetic `userMessage` chat turns, without keyboard automation, and without AT-SPI emulation.

---

## 2. End-to-End Architecture

```text
Antigravity Global Language Server (PID 356160 / port 38451)
  │
  ├─ 1. Emits PreToolUse hook (stdin JSON)
  │      │
  │      ▼
  │  Hook Adapter (src/ag_attention_bridge/hooks/adapter.py)
  │      │
  │      ├─ Non-blocking IPC notification to daemon (wait_for_response=False)
  │      └─ Returns observation response on stdout (<5ms):
  │         {"decision": "allow", "reason": "Ag Attention Bridge observation hook; native interaction will resolve externally."}
  │
  ├─ 2. Language Server executes tool & creates execution step:
  │      - Type: CORTEX_STEP_TYPE_ASK_QUESTION
  │      - Status: CORTEX_STEP_STATUS_WAITING
  │      - Field: requestedInteraction.askQuestion.questions[]
  │
  ├─ 3. Bridge Daemon (PySide6 / KDE Wayland Modal)
  │      │
  │      ├─ AntigravityDiscovery scans /proc
  │      │  - Discovers Global Language Server (no --workspace_id, defaults to "global")
  │      │  - Discovers Satellite Workspace Language Servers
  │      │  - Resolves HTTPS port via /proc/<pid>/fd socket inodes + /proc/net/tcp
  │      │
  │      ├─ InteractionResolver Candidate Evaluation
  │      │  - Queries candidate servers for cascadeId
  │      │  - Prioritizes server with active uncompleted waiting step (has_waiting=True)
  │      │  - Fallback to server with maximum step count (freshest trajectory)
  │      │
  │      ├─ AntigravityClient.find_waiting_interaction
  │      │  - Traverses steps in reverse, skipping steps with completedInteractions
  │      │  - Targets execution step index (e.g. 1368, NOT plannerResponse 1367)
  │      │  - Extracts authoritative 1-based option IDs ("1", "2", ...)
  │      │
  │      ├─ Modal UI enters NATIVE_WAITING_READY
  │      │  - Header displays Project Badge (📁 <project_name>) and metadata subtitle
  │      │  - Renders native radio/checkbox options with keyboard shortcuts (1–9, Enter, Esc)
  │      │
  │      └─ User selects option and presses Enter / clicks Submit
  │             │
  │             ▼
  │  InteractionResolver (idempotent lock on cascadeId + trajectoryId + stepIndex)
  │      │
  │      ▼
  └─ 4. ConnectRPC POST /HandleCascadeUserInteraction
         │
         ▼
     Language Server receives native response, appends completedInteractions,
     transitions step to CORTEX_STEP_STATUS_DONE, and resumes the agent trajectory!
```

---

## 3. Key Components & Implementation Details

### 3.1 Global Language Server vs Workspace Servers
Antigravity employs a multi-process architecture:
1. **Global Language Server**: Runs without `--workspace_id` in its command line. Hosts the active conversation trajectory, coordinates tool calls, and handles user interactions for the active agent session.
2. **Satellite Workspace Language Servers**: Spawned per opened workspace folder with `--enable_lsp --workspace_id file_<path>`. Used primarily for LSP language analysis.

**Discovery Fix in [`discovery.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/discovery.py)**:
```python
# Language servers must have csrf_token; workspace_id defaults to 'global' if omitted
csrf_token = args.get("csrf_token")
if not csrf_token:
    return None

workspace_id = args.get("workspace_id", "global")
```
When `--https_server_port` is omitted from the command line, `_find_https_port_for_pid()` maps socket file descriptors in `/proc/<pid>/fd` against `/proc/net/tcp` listening ports and validates responsiveness via loopback TLS probe.

### 3.2 Authoritative Candidate Selection
When multiple Language Server processes exist, multiple processes may hold cached copies of a conversation. [`interaction_resolver.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/interaction_resolver.py) selects the true active server:

```python
# Candidate sorting key:
# 1. Server with active waiting step (has_waiting=True)
# 2. Server with maximum step count (freshest trajectory)
candidates.sort(key=lambda item: (item[1], item[0]), reverse=True)
winner = candidates[0][2]
```

### 3.3 Trajectory Step Anatomy & Target `stepIndex`
Antigravity distinguishes between the planning step and the execution step:
* **`PLANNER_RESPONSE`** (e.g. index 1367): Emitted by the model, containing `toolCalls[].argumentsJson`. Antigravity does **not** register user input on this step. Submitting to this index triggers `"input not registered for step 1367"`.
* **`CORTEX_STEP_TYPE_ASK_QUESTION`** (e.g. index 1368): Created by Antigravity runtime to execute the interaction. Holds `requestedInteraction: {"askQuestion": ...}`. When answered, Antigravity records `completedInteractions: [...]`.

[`client.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/client.py) resolves the target step by skipping any step where `completedInteractions` is present and locating the active uncompleted step with `requestedInteraction` or status `WAITING`.

### 3.4 Modal Header & Project Title Display
The modal header complies with Project Rules by displaying:
* **Brand identity**: `Ag Attention Bridge`
* **Project Badge**: `QLabel#ProjectBadge` displaying `📁 <project_name>` with tooltip showing the full workspace directory path.
* **Queue Counter**: Badge showing `1 of N` pending interactions.
* **Metadata Subtitle**: `Project: <name> • Session: <conv_id[:8]>... • Model: <model_name>`

---

## 4. ConnectRPC Native Payload Schemas

### 4.1 `ask_question` Payload
```json
{
  "cascadeId": "02232dd3-9214-4497-b840-1b57bf1f3bf3",
  "interaction": {
    "trajectoryId": "09588ba9-57aa-49f9-beae-a3f87c54f5d8",
    "stepIndex": 1368,
    "askQuestion": {
      "responses": [
        {
          "question": "Apakah sekarang modal langsung aktif dan berhasil di-submit?",
          "options": [
            { "id": "1", "text": "(Recommended) Sempurna! Modal langsung siap tanpa error" },
            { "id": "2", "text": "Masih ada kendala" }
          ],
          "isMultiSelect": false,
          "selectedOptionIds": ["1"],
          "writeInResponse": "",
          "skipped": false
        }
      ],
      "cancelled": false
    }
  }
}
```

### 4.2 Permission Payload
#### Allow Once
```json
{
  "cascadeId": "02232dd3-9214-4497-b840-1b57bf1f3bf3",
  "interaction": {
    "trajectoryId": "09588ba9-57aa-49f9-beae-a3f87c54f5d8",
    "stepIndex": 1369,
    "permission": {
      "allow": true,
      "scope": "PERMISSION_SCOPE_ONCE"
    }
  }
}
```

#### Deny
```json
{
  "cascadeId": "02232dd3-9214-4497-b840-1b57bf1f3bf3",
  "interaction": {
    "trajectoryId": "09588ba9-57aa-49f9-beae-a3f87c54f5d8",
    "stepIndex": 1369,
    "permission": {
      "allow": false,
      "scope": "PERMISSION_SCOPE_ONCE",
      "userDenyInstruction": "Denied by user"
    }
  }
}
```

#### Supported Scopes
* `PERMISSION_SCOPE_UNSPECIFIED = 0`
* `PERMISSION_SCOPE_ONCE = 1` (Allow Once)
* `PERMISSION_SCOPE_CONVERSATION = 2` (Allow for this session)
* `PERMISSION_SCOPE_WORKSPACE = 3`
* `PERMISSION_SCOPE_GLOBAL = 4`
* `PERMISSION_SCOPE_PROJECT = 5`

---

## 5. Active Language Server Poller (`needsAttention: true`)

### 5.1 The Reactive Hook Limitation for Terminal Permissions
Antigravity's security sandbox pauses execution for terminal (`run_command`) and out-of-workspace file modification tools before tool execution starts:
1. `PostInvocation` **never fires** while a tool is waiting for permission (because tool execution has not completed).
2. `PreToolUse` requires a non-empty `decision` (`allow` or `deny`). Outputting an empty object `{}` causes Antigravity to reject the tool (`tool call denied`). Outputting `allow` in advance bypasses user security checks.
3. Therefore, relying solely on reactive hooks creates a visibility gap for sandbox permissions across multiple windows.

### 5.2 The Native Discovery Solution
Antigravity Language Servers maintain an authoritative list of conversations via ConnectRPC `SearchConversations`. When any conversation is paused waiting for user input (questions or permissions), Antigravity marks the conversation item with:
```json
"needsAttention": true
```

### 5.3 Background Poller Architecture
* **`InteractionResolver.scan_waiting_interactions()`**:
  * Iterates across all discovered Language Server PIDs in `/proc`.
  * Calls `SearchConversations` on each server using cached HTTP clients.
  * When `"needsAttention": true` is found, resolves the authoritative interaction via `resolve_authoritative_waiting_interaction(cascade_id, max_retries=2)`.
* **`IpcServer.start_background_poller(interval_ms=2000)`**:
  * A non-blocking `QTimer` dispatches worker threads every 2.0 seconds.
  * Ensures only one scanning thread runs concurrently (`self._scanning` guard).
  * Emits `_interaction_discovered` signal directly back to the Qt main thread upon discovery.
* **On-Demand Polling**:
  * Daemon startup immediately triggers `poll_active_interactions()`.
  * Clicking the KDE system tray icon ("Open Pending Requests" or "Show/Hide Current Request") instantly polls all Language Servers.
* **Deterministic Queue Management**:
  * When a request is resolved, `self.queue.consume(request_id)` is invoked unconditionally, immediately updating tray badges.
  * Stale requests from older steps in the same conversation are auto-purged (`old_req.step_index < current_step_index`).

---

## 6. Security & Isolation Controls

1. **Localhost Only**: `AntigravityClient` verifies that the target address is `127.0.0.1` or `localhost`. Remote addresses trigger an immediate `SecurityValidationError`.
2. **Process UID Verification**: Scans in `/proc` check `stat_info.st_uid == os.getuid()`. Processes owned by other users or containers are rejected.
3. **CSRF Token Masking**: Diagnostics and logs use `masked_csrf_token` (e.g. `b42c****9df5`). Plaintext tokens are never written to disk.
4. **Idempotent Lock**: The tuple `(cascade_id, trajectory_id, step_index)` is tracked in `InteractionResolver._state_map` with a thread lock, preventing accidental duplicate RPC submissions on double-clicks.

---

## 7. Keyboard & Window Behavior (KDE Wayland)

* **Always-On-Top**: `Qt.WindowType.WindowStaysOnTopHint` applied to `InteractionModal`.
* **KWin Window Rules**: Rules ensure window placement is centered, kept above, and accepts immediate focus without window-manager stealing prevention delays.
* **Esc Key / Close Button**: Hides modal to KDE system tray without answering or cancelling the interaction. The interaction remains pending in memory and accessible from the tray icon.
* **1–9 Number Shortcuts**: Instantly selects corresponding option when freeform text input is not focused.
* **Enter Key**: Submits selection only when in `NATIVE_WAITING_READY` state.

---

## 8. Verification & Test Coverage

All automated unit and integration tests pass:
* `tests/test_antigravity_discovery.py` — Global and workspace server discovery, port fallback, UID validation.
* `tests/test_antigravity_client.py` — ConnectRPC protocol transport, loopback enforcement, payload schemas.
* `tests/test_interaction_resolver.py` — Freshest candidate selection, state transitions, duplicate submission guards.
* `tests/test_native_flow.py` — End-to-end flow from observation hook to native RPC completion.
* `tests/test_ui.py` — Modal rendering, project badge, keyboard navigation, tray badge synchronization.

**Live In-Session Benchmark**: ConnectRPC round-trip submission takes **3–5ms**, instantly resuming Antigravity execution.
