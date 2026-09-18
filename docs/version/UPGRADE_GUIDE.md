# Antigravity Upgrade & Maintenance Guide

When Antigravity IDE updates to a new version, changes in internal binary names, command-line arguments, ConnectRPC schemas, or step types may require adjustments in **Ag Attention Bridge**.

Follow this step-by-step runbook to diagnose, verify, and update the project safely.

---

## 1. Quick Diagnostic Checklist

When Antigravity updates, run through these five quick checks:

```text
[ ] Check 1: Process Name & Path (Is it still language_server_linux_x64?)
[ ] Check 2: Command-Line Flags (Are --csrf_token and ports still present?)
[ ] Check 3: HTTPS Port Discovery (Does inode /proc/net/tcp lookup still find the port?)
[ ] Check 4: ConnectRPC Endpoints (Are HandleCascadeUserInteraction and GetCascadeTrajectory still valid?)
[ ] Check 5: Step Structure (Are CORTEX_STEP_TYPE_ASK_QUESTION and requestedInteraction unchanged?)
[ ] Check 6: Active Poller / needsAttention flag (Does SearchConversations still return needsAttention: true?)
```

---

## 2. Phase 1: Identifying New Version Details

Run the following commands in the terminal to inspect the updated installation:

```bash
# 1. Check IDE Product Version & Commit
cat "$HOME/development/clones/Antigravity IDE/resources/app/product.json" | grep -E '"nameShort"|"version"|"commit"|"date"'

# 2. Check Extension Package Version
cat "$HOME/development/clones/Antigravity IDE/resources/app/extensions/antigravity/package.json" | grep -E '"name"|"version"'

# 3. Check Language Server Binary Hash
md5sum "$HOME/development/clones/Antigravity IDE/resources/app/extensions/antigravity/bin/language_server_linux_x64"
```

Record any changed version numbers or hashes against [`ANTIGRAVITY_1.1.3_SPEC.md`](./ANTIGRAVITY_1.1.3_SPEC.md).

---

## 3. Phase 2: Verifying Process Architecture & Arguments

Inspect the running processes to verify process names and flags:

```bash
# List all running language server processes
ps aux | grep language_server
```

### What to check:
1. **Binary Name**: Is it still `language_server_linux_x64`?
   - *If changed*: Update `b"language_server_linux_x64"` in [`discovery.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/discovery.py#L92).
2. **Global vs Workspace Server**:
   - Verify that the primary Language Server process still runs with `--csrf_token`.
   - Verify if `--workspace_id` is present or absent on the primary process.
3. **Arg Parsing**:
   - Check if `--csrf_token` has been renamed or replaced with another flag (e.g. `--auth_token` or an environment variable).

---

## 4. Phase 3: Verifying Port Discovery & Heartbeat

Test whether Ag Attention Bridge's discovery can find the language server ports:

```bash
# Run Discovery Test
.venv/bin/python3 -c "
from ag_attention_bridge.antigravity.discovery import AntigravityDiscovery
disc = AntigravityDiscovery()
servers = disc.discover_servers()
print(f'Found {len(servers)} servers:')
for s in servers:
    print(f'  PID {s.pid}: Port={s.https_port}, CSRF={s.masked_csrf_token}, Workspace={s.workspace_id}')
"
```

### Testing Heartbeat via curl:
```bash
# Test ConnectRPC Heartbeat manually (replace <port> and <token> with live values from /proc)
curl -k -s -X POST \
  -H "Content-Type: application/json" \
  -H "x-codeium-csrf-token: <csrf_token>" \
  -d '{}' \
  "https://127.0.0.1:<https_port>/exa.language_server_pb.LanguageServerService/Heartbeat"
```
*Expected response*: `{}` (HTTP 200).

### Troubleshooting Port Discovery:
* If no port is discovered:
  1. Run `ls -l /proc/<pid>/fd | grep socket` to verify socket inodes exist.
  2. Run `ss -tlpn | grep <pid>` to view listening ports.
  3. If Antigravity switched to a Unix Domain Socket instead of localhost HTTPS:
     Check `/tmp/` for newly created domain sockets (e.g. `/tmp/server_*.sock`).

---

## 5. Phase 4: Verifying ConnectRPC Services & Protobuf Schemas

If `Heartbeat` succeeds but interactions fail, check whether the RPC method names or payload formats have changed.

### 5.1 Scanning Binary Strings for Service Names
```bash
BINARY="$HOME/development/clones/Antigravity IDE/resources/app/extensions/antigravity/bin/language_server_linux_x64"

# Check if LanguageServerService paths changed
strings "$BINARY" | grep -E "LanguageServerService/(Heartbeat|GetCascadeTrajectory|HandleCascadeUserInteraction)"
```

### 5.2 Inspecting Extension Frontend Call Graph
Antigravity's UI bundle defines how interactions are serialized before calling `HandleCascadeUserInteraction`:

```bash
BUNDLE_DIR="$HOME/development/clones/Antigravity IDE/resources/app/extensions/antigravity"

# Search for interaction handler in frontend bundles
grep -rn "HandleCascadeUserInteraction" "$BUNDLE_DIR"
grep -rn "selectedOptionIds" "$BUNDLE_DIR"
```

### What to check:
1. **CSRF Header**: Is the header still `x-codeium-csrf-token`?
   - *If changed*: Update `CSRF_HEADER_NAME` in [`client.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/client.py).
2. **Payload structure**:
   - Does `interaction` still take `trajectoryId`, `stepIndex`, and `askQuestion` / `permission`?
   - Do questions still use `selectedOptionIds: string[]` and `writeInResponse: string`?
   - Do permissions still use `allow: bool` and `scope: PermissionScope`?

---

## 6. Phase 5: Verifying Trajectory Step Types

Run a script to dump the step types and keys of an active conversation:

```bash
.venv/bin/python3 -c "
from ag_attention_bridge.antigravity.discovery import AntigravityDiscovery
from ag_attention_bridge.antigravity.client import AntigravityClient
import json

disc = AntigravityDiscovery()
servers = disc.discover_servers()
for s in servers:
    c = AntigravityClient(s)
    convs = c.search_conversations()
    if convs:
        cid = convs[0].get('conversationId')
        traj = c.get_cascade_trajectory(cid)
        steps = traj.get('trajectory', {}).get('steps', [])
        print(f'Server PID {s.pid} has {len(steps)} steps for {cid}')
        if steps:
            last = steps[-1]
            print('  Last step keys:', list(last.keys()))
            print('  Last step type:', last.get('type'))
            print('  Last step status:', last.get('status'))
"
```

### What to check:
1. Are step types still `CORTEX_STEP_TYPE_ASK_QUESTION`, `CORTEX_STEP_TYPE_PLANNER_RESPONSE`, and `CORTEX_STEP_TYPE_RUN_COMMAND`?
2. Are statuses still `CORTEX_STEP_STATUS_WAITING` and `CORTEX_STEP_STATUS_DONE`?
3. Is `completedInteractions` still populated upon interaction completion?
   - *If step names changed*: Update string constants in [`client.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/client.py) and [`interaction_resolver.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/interaction_resolver.py).

---

## 7. Code Modification Mapping Reference

Use this table to find the exact file to modify when a specific component changes:

| Component / Change in Antigravity | File in Ag Attention Bridge | Key Functions / Constants |
|---|---|---|
| **Binary process name** (e.g. `language_server_linux_arm64` or new binary) | [`src/ag_attention_bridge/antigravity/discovery.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/discovery.py) | `parse_pid_cmdline` (line 92) |
| **Command line flags** (e.g. new flag for CSRF or workspace ID) | [`src/ag_attention_bridge/antigravity/discovery.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/discovery.py) | `parse_cmdline_args`, `parse_pid_cmdline` |
| **Port discovery mechanism** (e.g. UDS domain socket or custom port flag) | [`src/ag_attention_bridge/antigravity/discovery.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/discovery.py) | `_find_https_port_for_pid` |
| **CSRF HTTP Header name** (e.g. `x-antigravity-csrf-token`) | [`src/ag_attention_bridge/antigravity/client.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/client.py) | `CSRF_HEADER_NAME` (line 21) |
| **RPC Service Path** (e.g. renamed package or endpoint) | [`src/ag_attention_bridge/antigravity/client.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/client.py) | `RPC_SERVICE_PATH` (line 22) |
| **Question payload structure** (e.g. new protobuf field name) | [`src/ag_attention_bridge/antigravity/client.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/client.py)<br>[`src/ag_attention_bridge/antigravity/models.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/models.py) | `build_ask_question_payload`<br>`QuestionEntry.to_dict()` |
| **Permission payload / scopes** | [`src/ag_attention_bridge/antigravity/client.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/client.py)<br>[`src/ag_attention_bridge/antigravity/models.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/models.py) | `build_permission_payload`<br>`PermissionScope` enum |
| **Step matching & Waiting step criteria** | [`src/ag_attention_bridge/antigravity/client.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/client.py) | `find_waiting_interaction` (line 155) |
| **Server candidate selection logic** | [`src/ag_attention_bridge/antigravity/interaction_resolver.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/interaction_resolver.py) | `_get_client_for_cascade` (line 66) |
| **Active Poller & Multi-Workspace Scanning** | [`src/ag_attention_bridge/antigravity/interaction_resolver.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/antigravity/interaction_resolver.py)<br>[`src/ag_attention_bridge/ipc/server.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/ipc/server.py) | `scan_waiting_interactions`<br>`start_background_poller`, `poll_active_interactions` |
| **Hook Adapter Matcher / PreToolUse JSON** | [`src/ag_attention_bridge/hooks/adapter.py`](file:///home/mashupsoat/development/ag-attention-bridge/src/ag_attention_bridge/hooks/adapter.py)<br>[`scripts/install-hooks.sh`](file:///home/mashupsoat/development/ag-attention-bridge/scripts/install-hooks.sh) | `handle_hook`<br>`HOOKS_FILE` template |

---

## 8. Phase 6: Post-Update Verification Runbook

After making any adjustments for the new Antigravity version:

1. **Run Full Test Suite**:
   ```bash
   .venv/bin/pytest -v
   ```
   *Expected*: All tests pass without failures.

2. **Reinstall & Reload Hooks**:
   ```bash
   bash scripts/install-hooks.sh
   ```

3. **Verify Running Processes**:
   ```bash
   ps aux | grep -E "ag-attention-bridge|language_server"
   ```

4. **Trigger Live Test in IDE**:
   * Ask the agent in chat to call `ask_question` or execute a permission-requiring command.
   * Verify the modal appears with the project title `📁 <project_name>` in the header.
   * Verify pressing `Enter` or clicking `Submit` successfully unblocks the agent in `<10ms`.
   * Check diagnostic logs for confirmation:
     ```bash
     tail -n 20 "$HOME/.local/state/ag-attention-bridge/bridge.log"
     ```
     Look for `[WAITING_STEP_FOUND]`, `[NATIVE_READY]`, and `[RPC_SUCCESS] status=200`.
