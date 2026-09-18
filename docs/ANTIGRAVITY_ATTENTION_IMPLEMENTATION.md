# Ag Attention Bridge — Prompt & Implementation Plan

## 1. Project Goal

Build **Ag Attention Bridge**, a lightweight Linux desktop companion for Google Antigravity on **KDE Plasma + Wayland**.

The application exists to remove the need to switch back to the Antigravity window whenever an agent asks the user a question or requests permission.

When Antigravity needs user input, Ag Attention Bridge must:

1. detect the interaction through official Antigravity hooks;
2. display a premium always-on-top modal in the center of the active desktop;
3. show enough conversation context to make the decision without opening Antigravity;
4. let the user answer directly from the modal;
5. return the answer/decision to the Antigravity execution flow;
6. hide unresolved requests in the system tray if the user presses `Esc` or closes the modal;
7. show the number of pending requests as a badge on the tray icon;
8. allow pending requests to be reopened from the tray.

This is initially a personal desktop utility, but the codebase must be clean enough to publish on GitHub later.

The application must remain lightweight. Avoid Electron and browser-based desktop runtimes.

---

# 2. Recommended Stack

Use:

- **Python 3.11+**
- **PySide6 / Qt 6 Widgets**
- `QApplication`
- `QDialog` / `QWidget`
- `QSystemTrayIcon`
- `QMenu`
- `QLocalServer` / `QLocalSocket` where practical
- JSON payloads
- small persisted JSON state only where necessary
- `systemd --user` for optional autostart/background service
- KDE **KWin Window Rules** for reliable keep-above/placement behavior on Wayland

Do not introduce `asyncio`, databases, web servers, Electron, Redis, or other infrastructure unless a demonstrated requirement appears.

Prefer the Qt event loop as the application event loop.

---

# 3. Official Antigravity Primitives

Use only documented Antigravity interfaces as the primary integration path.

Relevant hooks:

- `PreToolUse`
- `PostToolUse`
- `PreInvocation`
- `PostInvocation`
- `Stop`

Relevant tools:

- `ask_question`
- `ask_permission`

Useful common hook fields:

- `conversationId`
- `workspacePaths`
- `transcriptPath`
- `artifactDirectoryPath`
- `modelName`

`ask_question` exposes structured questions including question text, options, and multi-select state.

`ask_permission` exposes structured permission information such as action, target, and reason.

`PreToolUse` can return tool gating decisions such as `allow`, `deny`, `ask`, and `force_ask`.

`PreInvocation` and `PostInvocation` can inject a `userMessage`.

`PostInvocation` can use `terminationBehavior: "force_continue"`.

`Stop` can return `decision: "continue"` with a reason if a fallback continuation is required.

Do **not** edit Antigravity databases, internal SQLite history, transcript files, IDE UI state, or undocumented IPC.

Official reference:
https://antigravity.google/docs/ide/hooks/

---

# 4. Critical Unknown: ask_question Response Bridge

Permission responses can be handled directly through the documented `PreToolUse` decision mechanism.

`ask_question` is different: the IDE hook contract currently exposes the question but does not document an output field equivalent to:

```json
{"answer":"PostgreSQL"}
```

Therefore the question-response bridge must be proven with a dedicated PoC before the full UI is built.

## Preferred bridge experiment

Target lifecycle:

```text
Antigravity
    |
    | ask_question
    v
PreToolUse
    |
    | capture question
    v
hook_adapter
    |
    v
Ag Attention Bridge daemon
    |
    | show modal
    | wait for user
    v
user answer
    |
    +--> response stored by conversationId/requestId
    |
PreToolUse finishes
    |
    | intercept original question tool call
    v
PostInvocation
    |
    | injectSteps:
    |   userMessage: <external answer>
    | terminationBehavior: force_continue
    v
Antigravity model continues
```

The exact behavior of an intercepted `ask_question` followed by `PostInvocation` injection must be tested.

### Fallback sequence

If `PostInvocation` is not reached:

1. keep the external answer pending;
2. detect the following `Stop`;
3. return `decision: "continue"` with a clear reason containing the external answer;
4. on the next `PreInvocation`, inject the pending answer as `userMessage`;
5. mark the response consumed only after successful injection.

Never silently discard a response.

Do not build UI complexity until this bridge is verified on the installed Antigravity version.

---

# 5. System Architecture

```text
+----------------------------------------------------+
|                  Antigravity IDE                   |
+--------------------------+-------------------------+
                           |
                     official hooks
                           |
       +-------------------+-------------------+
       |                   |                   |
   PreToolUse         PostInvocation          Stop
       |                   |                   |
       +-------------------+-------------------+
                           |
                    hook_adapter.py
                           |
                  local IPC / socket
                           |
                           v
+----------------------------------------------------+
|              Ag Attention Bridge Daemon            |
|                                                    |
|  Request Router                                    |
|  Session Store                                     |
|  Pending Request Queue                             |
|  Transcript Context Reader                         |
|  Response Bridge                                   |
|  Tray Controller                                   |
|  Modal Controller                                  |
+--------------------------+-------------------------+
                           |
                           v
+----------------------------------------------------+
|               PySide6 / Qt User Interface          |
|                                                    |
|  Premium Interaction Modal                         |
|  Queue Viewer                                      |
|  System Tray + numeric badge                       |
+----------------------------------------------------+
                           |
                           v
                    KWin Window Rules
              keep-above / centered / focus
```

---

# 6. Component Responsibilities

## `hook_adapter`

A tiny CLI process called by Antigravity hooks.

Responsibilities:

- read JSON from stdin;
- identify event type;
- validate only the fields needed;
- send the event to the daemon;
- for synchronous decision events, wait for the daemon response;
- emit only valid Antigravity hook JSON to stdout;
- write diagnostics to stderr/log file, never stdout.

The adapter must contain almost no UI or business logic.

## `daemon`

One persistent process per Linux user.

Responsibilities:

- own the Qt application;
- own the system tray;
- accept hook connections;
- track active conversations;
- deduplicate requests;
- maintain pending interaction queue;
- open/hide modals;
- return answers to waiting adapters;
- persist minimal crash-recovery state if required.

## `session store`

Key sessions primarily by `conversationId`.

Suggested state:

```text
Session
- conversation_id
- workspace_paths
- project_name
- model_name
- transcript_path
- pending_requests[]
```

Suggested request state:

```text
InteractionRequest
- request_id
- conversation_id
- type: question | permission
- title
- body
- options[]
- multi_select
- context
- created_at
- status: pending | answered | consumed
- response
```

## `transcript reader`

Read `transcriptPath` as read-only context.

Goal:

- latest meaningful user message;
- latest meaningful agent text;
- optionally a short recent context window.

Requirements:

- defensive parser;
- tolerate unknown JSONL records;
- tolerate partial/truncated writes;
- never modify transcript files;
- never depend on undocumented fields for core execution.

If transcript parsing fails, the modal must still show the structured hook payload.

## `response bridge`

Responsible for translating UI actions into valid Antigravity hook responses.

Keep permission response and question response as separate strategies.

---

# 7. IPC

Prefer **QLocalServer / QLocalSocket** because the main application already uses Qt and the target is local-only.

Requirements:

- local user only;
- no TCP port;
- newline-delimited or length-prefixed JSON messages;
- request/response correlation by `request_id`;
- reconnect cleanly when daemon restarts;
- adapter timeout must be configurable;
- no stdout debug noise from hook commands.

Possible socket identity:

```text
ag-attention-bridge
```

If QLocalSocket behavior becomes problematic, use an AF_UNIX socket under:

```text
$XDG_RUNTIME_DIR/ag-attention-bridge.sock
```

Do not expose network access.

---

# 8. Interaction Behavior

## New request

If no request modal is active:

- immediately present it;
- request focus;
- keep it above normal windows.

If another request is already active:

- enqueue the new request;
- update tray badge;
- do not open multiple competing dialogs.

Use FIFO by default.

## Esc / close button

`Esc` or window close must:

- hide the modal;
- **not** reject, approve, or answer the request;
- leave the request pending;
- keep the hook waiting when applicable;
- update tray badge.

## Tray

Tray icon is always available while the daemon runs.

Left click:

- show current pending request;
- if none, show lightweight status/queue window.

Context menu:

- Open Pending Requests
- Show/Hide Current Request
- Open Logs
- Quit

If requests are pending, dynamically render a numeric badge over the tray icon using `QPainter`.

No desktop notification balloons and no notification sounds.

---

# 9. UI Direction

Style: **premium AI assistant**, not a generic Qt utility.

Visual goals:

- calm;
- focused;
- compact;
- modern;
- high information density without clutter;
- visually closer to a premium AI desktop assistant than to a settings dialog.

Suggested dimensions:

- width: 600–680 px;
- height: content-driven;
- maximum height: about 70% of available screen;
- long content scrolls internally.

Layout:

```text
+------------------------------------------------+
| AG  Ag Attention Bridge        project / model |
|------------------------------------------------|
| USER CONTEXT                                   |
| latest relevant user request                   |
|                                                |
| AGENT CONTEXT                                  |
| latest relevant model response                 |
|------------------------------------------------|
| INPUT REQUIRED                                 |
| actual question / permission                   |
|                                                |
| options or command/details                     |
|                                                |
|                         [Cancel] [Submit/Allow]|
+------------------------------------------------+
```

Question controls:

- radio buttons for single-select;
- checkboxes for multi-select;
- optional freeform input if useful;
- clearly distinguish selected state.

Permission controls:

- show Action;
- Target;
- Reason;
- command/path values in a monospace block when appropriate;
- `Deny` and `Allow` receive equal visual weight except the primary action may use accent styling.

Keyboard:

- `Esc`: hide to tray, do not resolve;
- `Enter`: submit when unambiguous;
- arrow keys/tab navigation must work;
- focus the first meaningful control.

Do not create desktop notifications.

---

# 10. KDE Wayland Integration

Use Qt window flags as an application hint:

```python
Qt.WindowType.WindowStaysOnTopHint
```

Use KWin Window Rules as the stronger desktop-level policy.

Document a recommended KWin rule for the Ag Attention Bridge modal:

- Match application/window class;
- Keep above: Yes / Force;
- Initial placement: Centered;
- Accept focus: Yes;
- Focus stealing prevention: None where necessary;
- Skip pager: Yes;
- Skip switcher: preferably Yes;
- taskbar behavior may remain hidden because the tray is the primary persistent surface.

Do not rely on manual `window.move()` positioning as the primary Wayland placement mechanism.

Call `show()`, `raise_()`, and `activateWindow()` as best-effort hints, while allowing KWin to make the final focus/placement decision.

---

# 11. Project Structure

Start with:

```text
ag-attention-bridge/
├── pyproject.toml
├── README.md
├── src/
│   └── ag_attention_bridge/
│       ├── __init__.py
│       ├── app.py
│       ├── config.py
│       ├── domain/
│       │   ├── models.py
│       │   └── enums.py
│       ├── ipc/
│       │   ├── server.py
│       │   ├── client.py
│       │   └── protocol.py
│       ├── hooks/
│       │   ├── adapter.py
│       │   ├── question_bridge.py
│       │   └── permission_bridge.py
│       ├── antigravity/
│       │   ├── transcript.py
│       │   └── payloads.py
│       ├── ui/
│       │   ├── main_dialog.py
│       │   ├── question_view.py
│       │   ├── permission_view.py
│       │   ├── queue_view.py
│       │   ├── tray.py
│       │   └── theme.py
│       └── state/
│           └── store.py
├── hooks/
│   └── hooks.example.json
├── scripts/
│   ├── install-hooks.sh
│   └── install-user-service.sh
├── systemd/
│   └── ag-attention-bridge.service
└── tests/
    ├── test_protocol.py
    ├── test_payloads.py
    ├── test_queue.py
    └── test_question_bridge.py
```

Do not create every file in advance if it has no implementation yet.

---

# 12. Implementation Phases

## Phase 0 — Repository bootstrap

- create Python project;
- configure PySide6;
- add structured logging;
- establish package layout;
- verify simple tray app starts on KDE Wayland.

Acceptance:
- tray icon visible;
- process idle CPU effectively zero;
- clean shutdown.

## Phase 1 — Hook instrumentation

Build the hook adapter in observation mode.

Capture sanitized payloads for:

- `PreToolUse: ask_question`;
- `PreToolUse: ask_permission`;
- `PostInvocation`;
- `Stop`.

Record actual event order from the installed Antigravity version.

Acceptance:
- no behavior changes to Antigravity;
- exact lifecycle documented from real tests.

## Phase 2 — IPC + tray queue

- daemon;
- local socket;
- request protocol;
- queue state;
- numeric tray badge;
- tray click reopens queue/current request.

Acceptance:
- synthetic requests can be queued and resolved;
- `Esc` hides without resolving;
- no lost requests.

## Phase 3 — Premium modal

Implement the UI without Antigravity response injection first.

Acceptance:
- question options render correctly;
- multi-select works;
- permission details render correctly;
- long content scrolls;
- keyboard navigation works;
- close/Esc hides to tray.

## Phase 4 — Permission bridge

Connect `ask_permission`.

Acceptance:
- Allow produces documented `{"decision":"allow"}`;
- Deny produces documented `{"decision":"deny", ...}`;
- Antigravity receives the result without switching windows.

## Phase 5 — Question bridge PoC

Test the real lifecycle before generalizing.

Experiment:

1. capture `ask_question`;
2. display external UI;
3. collect answer;
4. intercept original interaction;
5. inject external answer using documented invocation hooks;
6. force continuation where required;
7. verify model interprets the answer correctly.

Test:

- one option;
- multiple options;
- multi-select;
- freeform;
- modal hidden to tray before answering;
- concurrent conversation.

If this strategy fails, stop and document the exact lifecycle. Do not resort to editing Antigravity internals.

## Phase 6 — Transcript context

Read the transcript read-only and add:

- latest user request;
- latest model text;
- graceful parser fallback.

Context is presentation-only and must never become a hard dependency for answering.

## Phase 7 — KDE polish

- KWin rule documentation;
- active-window focus behavior;
- centered placement;
- high-DPI testing;
- multi-monitor testing;
- dark/light compatibility if practical.

## Phase 8 — Packaging

- `systemd --user` service;
- installer/uninstaller;
- sample hooks configuration;
- README;
- GitHub-ready license and contribution notes.

---

# 13. Performance Targets

Idle daemon:

- near-zero CPU;
- avoid polling;
- event-driven IPC only;
- minimal wakeups.

Memory:

- keep transcript context bounded;
- do not load entire long transcripts when only recent context is required;
- do not retain large artifacts/screenshots.

No browser engine.

---

# 14. Reliability Rules

- Never lose an unresolved request because the modal was closed.
- Never treat UI close as Deny.
- Never auto-answer questions.
- Never auto-approve permission.
- Correlate every answer with `conversationId` + `request_id`.
- Deduplicate repeated hook events.
- stdout from hook adapters must contain only the hook protocol response.
- Logging goes to stderr or application log.
- Malformed payloads fail safely and visibly.
- If daemon is unavailable, degrade cleanly instead of breaking Antigravity.

---

# 15. Initial Antigravity Prompt

Use the following prompt when starting implementation:

> Implement **Ag Attention Bridge** according to `ANTIGRAVITY_ATTENTION_IMPLEMENTATION.md` and `ANTIGRAVITY_ATTENTION_RULES.md`.
>
> Start with Phase 0 and Phase 1 only. Do not jump directly to the full UI.
>
> First inspect the current repository and create the minimum clean project structure required. Use Python + PySide6/Qt6 and keep the process event-driven and lightweight.
>
> The most important technical uncertainty is the `ask_question` response bridge. Before designing around assumptions, instrument the official Antigravity hooks and verify the real lifecycle/order for `PreToolUse(ask_question)`, `PostInvocation`, `PreInvocation`, and `Stop` on this installed Antigravity version.
>
> Do not modify Antigravity internal databases, transcript files, private IPC, or undocumented state. `transcriptPath` is read-only.
>
> After each implementation phase:
> 1. run the relevant tests;
> 2. report what was proven;
> 3. distinguish documented behavior from observed behavior;
> 4. update implementation notes if the actual lifecycle differs from the plan.
>
> Optimize for maintainability, low idle resource usage, and KDE Plasma Wayland compatibility. Avoid unnecessary dependencies and abstractions.

---

# 16. Definition of MVP Done

MVP is complete when:

- Ag Attention Bridge runs persistently in the KDE system tray;
- `ask_question` opens the external centered keep-above modal;
- `ask_permission` opens the external modal;
- the user can answer/allow/deny without opening Antigravity;
- closing or pressing Esc hides the request to tray without resolving it;
- tray badge shows the number of pending requests;
- tray allows pending requests to be reopened;
- answers are correlated to the correct Antigravity conversation;
- multi-session requests do not overwrite one another;
- no desktop notification is required;
- idle resource usage remains low;
- no undocumented modification of Antigravity state is used.
