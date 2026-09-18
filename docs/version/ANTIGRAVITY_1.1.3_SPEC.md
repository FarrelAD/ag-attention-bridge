# Antigravity 1.1.3 Technical Specification Baseline

This document captures the exact technical baseline of Antigravity IDE version **1.1.3** as verified on Linux x86_64. Use this specification as the reference point when analyzing future Antigravity updates.

---

## 1. Product & Binary Metadata

* **IDE Name**: `Antigravity IDE`
* **IDE Version**: `1.1.3` (VS Code Base: `1.107.0`)
* **Commit**: `ecfbad74d93962fc8ca485d93ab9b4f3d4cb6cf8`
* **Release Date**: `2026-08-13T08:37:22.547Z`
* **Antigravity Extension**: `antigravity` (Version: `0.2.0`, Publisher: `google`)
* **Extension Path**: `/home/<user>/development/clones/Antigravity IDE/resources/app/extensions/antigravity`
* **Core Binary**: `bin/language_server_linux_x64`
* **Binary MD5**: `a8bf3925589e4be3b8e9a2a2a9563f29`
* **Binary Architecture**: ELF 64-bit LSB executable, x86-64, dynamically linked, Go runtime

---

## 2. Process Architecture & Command-Line Arguments

Antigravity executes **two distinct types** of language server processes simultaneously:

### 2.1 Global Language Server (Primary Agent Runtime)
This process hosts the live conversation trajectories, coordinates model tool execution, and registers user interactions across all workspaces.

* **Typical Command-Line**:
  ```text
  /path/to/language_server_linux_x64 \
    --csrf_token <dynamic_uuid_v4> \
    --extension_server_port <port> \
    --extension_server_csrf_token <dynamic_uuid_v4> \
    --app_data_dir antigravity-ide \
    --subclient_type ide \
    --cloud_code_endpoint https://cloudcode-pa.googleapis.com
  ```
* **Key Characteristic**: **Does NOT** contain `--workspace_id` in its command line.
* **Ports**:
  * ConnectRPC HTTPS: Bound dynamically on localhost (does not appear in cmdline flags; resolved via socket inode inspection).
  * Extension server port: Passed via `--extension_server_port`.

### 2.2 Satellite Workspace Language Servers (LSP & Code Analysis)
These processes are spawned per workspace folder for language features (code navigation, completions).

* **Typical Command-Line**:
  ```text
  /path/to/language_server_linux_x64 \
    --enable_lsp \
    --csrf_token <dynamic_uuid_v4> \
    --extension_server_port <port> \
    --extension_server_csrf_token <dynamic_uuid_v4> \
    --https_server_port <port> \
    --lsp_port <port> \
    --workspace_id file_home_user_project \
    --cloud_code_endpoint https://daily-cloudcode-pa.googleapis.com \
    --subclient_type ide \
    --app_data_dir antigravity-ide \
    --parent_pipe_path /tmp/server_<hex>
  ```
* **Key Characteristic**: Contains `--workspace_id` and often `--https_server_port`.

---

## 3. Port Discovery Contract

Because modern Antigravity releases omit `--https_server_port` from the Global Language Server process cmdline, port discovery uses a two-tier strategy:

1. **Tier 1 (Flag Lookup)**: If `--https_server_port` is present in cmdline, use it directly.
2. **Tier 2 (Socket Inode Resolution)**:
   * Read `/proc/<pid>/fd/` and extract all socket symlinks: `socket:[<inode>]`.
   * Parse `/proc/net/tcp` (and `/proc/net/tcp6`) to map inode numbers to local IPv4 listening ports in hex format (e.g. `9633` = `38451`).
   * Probe candidate ports using HTTPS `POST /exa.language_server_pb.LanguageServerService/Heartbeat` with header `x-codeium-csrf-token: <csrf_token>`.
   * The responding port is verified and cached as the server's `https_port`.

---

## 4. ConnectRPC Service & Endpoints

Base URL: `https://127.0.0.1:<https_port>`
Service: `/exa.language_server_pb.LanguageServerService/`

All RPC calls require:
* **Method**: `POST`
* **Header**: `Content-Type: application/json`
* **Header**: `x-codeium-csrf-token: <csrf_token>` (exact CSRF token parsed from `/proc/<pid>/cmdline`)
* **TLS**: Self-signed certificate on loopback (`ssl.CERT_NONE` validation).

### Verified Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `Heartbeat` | POST | Health probe verifying port and CSRF token validity. Returns `{}`. |
| `GetCascadeTrajectory` | POST | Retrieves full conversation trajectory steps, state transitions, and tool calls. |
| `GetCascadeTrajectorySteps` | POST | Retrieves sliced steps starting from `stepOffset`. |
| `HandleCascadeUserInteraction` | POST | **Primary resolution endpoint.** Submits user interaction decisions natively. |
| `SearchConversations` | POST | Lists active and historical conversations in the workspace. Returns items containing `needsAttention: bool` (`true` when waiting for user input). |

---

## 5. Native Interaction Data Model

### 5.1 Trajectory Step Anatomy
In Antigravity 1.1.3:
* **Question Flow (`ask_question`)**:
  1. A step with `type: "CORTEX_STEP_TYPE_PLANNER_RESPONSE"` and `status: "CORTEX_STEP_STATUS_DONE"` is created (contains the tool call definition).
  2. Antigravity creates an execution step with `type: "CORTEX_STEP_TYPE_ASK_QUESTION"`.
  3. The execution step contains `requestedInteraction: {"askQuestion": {"questions": [...]}}`.
  4. Status transitions to `CORTEX_STEP_STATUS_WAITING`.
  5. In `SearchConversations`, the conversation has `"needsAttention": true`.
* **Terminal / File Permission Flow (`run_command`, `write_to_file`)**:
  1. Antigravity security sandbox pauses the tool execution step (e.g. `type: "CORTEX_STEP_TYPE_RUN_COMMAND"`).
  2. Step status transitions to `CORTEX_STEP_STATUS_WAITING`.
  3. Step contains `requestedInteraction: {"permission": {"resource": {"action": "command", "target": "<cmd>"}, "actionDescription": "<desc>", "suggestedPersistPattern": "<pattern>"}}`.
  4. In `SearchConversations`, the conversation has `"needsAttention": true`.
* **Resolution**:
  1. When the user responds via `HandleCascadeUserInteraction`, Antigravity appends `completedInteractions: [{"request": {...}, "response": {...}}]`.
  2. Status transitions to `CORTEX_STEP_STATUS_DONE` (or `CORTEX_STEP_STATUS_RUNNING` for authorized commands).
  3. `"needsAttention"` is cleared.

> [!IMPORTANT]
> The target `stepIndex` for `HandleCascadeUserInteraction` **must** be the execution step index (`CORTEX_STEP_TYPE_ASK_QUESTION` or `CORTEX_STEP_TYPE_RUN_COMMAND`), **never** the planner response step index.

### 5.2 `HandleCascadeUserInteraction` Request Schema

```json
{
  "cascadeId": "<uuid>",
  "interaction": {
    "trajectoryId": "<uuid>",
    "stepIndex": <int>,
    
    // Oneof: askQuestion OR permission
    "askQuestion": {
      "responses": [
        {
          "question": "<string>",
          "options": [
            { "id": "<string_id>", "text": "<string>" }
          ],
          "isMultiSelect": <bool>,
          "selectedOptionIds": ["<id1>", "<id2>"],
          "writeInResponse": "<string>",
          "skipped": <bool>
        }
      ],
      "cancelled": <bool>
    },
    
    "permission": {
      "allow": <bool>,
      "scope": "<PermissionScope_enum_string>",
      "userDenyInstruction": "<string>"
    }
  }
}
```

### 5.3 Option ID Schema (`wDi` in `jetskiAgent/main.js`)
* Antigravity string options use **1-based string indices**: `"1"`, `"2"`, `"3"`.
* Structured option dictionaries preserve `opt.id`.
* The response payload echoes the full question and options list with `selectedOptionIds` containing the chosen IDs.

---

## 6. Antigravity Hooks Specification

Configured in: `~/.gemini/config/hooks.json`

```json
{
  "ag-attention-bridge": {
    "PreToolUse": [
      {
        "matcher": "ask_question|ask_permission",
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.local/bin/ag-hook-adapter --event PreToolUse",
            "timeout": 30
          }
        ]
      }
    ],
    "PreInvocation": [
      {
        "type": "command",
        "command": "$HOME/.local/bin/ag-hook-adapter --event PreInvocation",
        "timeout": 15
      }
    ],
    "PostInvocation": [
      {
        "type": "command",
        "command": "$HOME/.local/bin/ag-hook-adapter --event PostInvocation",
        "timeout": 15
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "$HOME/.local/bin/ag-hook-adapter --event Stop",
        "timeout": 15
      }
    ]
  }
}
```

### Observation Hook Contract
For `PreToolUse` on `ask_question` and `ask_permission`, the adapter returns:
```json
{
  "decision": "allow",
  "reason": "Ag Attention Bridge observation hook; native interaction will resolve externally."
}
```
This allows the language server to proceed with creating the native execution step in the trajectory without blocking stdout.
