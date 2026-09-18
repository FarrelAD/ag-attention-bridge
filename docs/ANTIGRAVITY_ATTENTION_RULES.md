# Ag Attention Bridge — Antigravity Project Rules

## Mission
Build a lightweight KDE Wayland companion for Antigravity that surfaces `ask_question` and `ask_permission` as premium always-on-top dialogs, lets the user respond without switching to Antigravity, and keeps unresolved interactions accessible from the system tray.

Use these rules as the default engineering contract. Prefer correctness, low resource use, simple architecture, and verified Antigravity behavior over cleverness.

## Stack
Default stack:
- Python 3.11+
- PySide6 / Qt6 Widgets
- Qt event loop
- QSystemTrayIcon
- QLocalServer/QLocalSocket for local IPC where practical
- JSON messages
- systemd --user only for optional autostart
- KDE KWin Window Rules for Wayland placement/keep-above

Do not add Electron, a browser runtime, HTTP server, database, Redis, asyncio, or a large framework unless a proven requirement justifies it.

## Architectural Boundaries
Maintain these layers:

`Antigravity Hooks -> Hook Adapter -> Local IPC -> Daemon/Domain -> UI`

### Hook Adapter
Must be tiny. It:
- reads Antigravity JSON from stdin;
- validates required fields;
- sends a typed local request;
- waits only when a synchronous user decision is required;
- prints ONLY valid hook JSON to stdout.
Diagnostics/logging must never pollute stdout.

### Daemon
One process per user. Own:
- QApplication;
- local IPC server;
- session/request state;
- pending queue;
- transcript context reader;
- response bridge;
- modal controller;
- system tray.

### Domain
UI-independent models for sessions, requests, options, responses, and states. Key sessions by `conversationId`; key individual interactions by generated `request_id`.

### UI
UI must not parse Antigravity payloads or implement hook protocol logic. It receives normalized domain models and returns typed user actions.

### Transcript
`transcriptPath` is READ-ONLY. Parse defensively. Transcript context is optional presentation data, never a hard dependency for answering a hook.

Never edit Antigravity databases, transcript files, internal SQLite history, IDE storage, private IPC, or undocumented internal state.

## Official Hook Strategy
Primary integration must use documented Antigravity hooks:
- `PreToolUse`
- `PreInvocation`
- `PostInvocation`
- `Stop`

Use `PreToolUse` for `ask_question|ask_permission`.

Permission:
- map Allow to documented `decision: "allow"`;
- map Deny to documented `decision: "deny"`;
- never auto-approve or auto-deny.

Question answering:
- treat the response bridge as an experimentally verified subsystem;
- first observe the real lifecycle on the installed Antigravity version;
- prefer documented `injectSteps.userMessage`;
- use `PostInvocation` + `terminationBehavior: "force_continue"` only after tests prove the lifecycle;
- use `Stop -> decision:"continue"` / next invocation only as a documented fallback;
- never invent undocumented hook output such as `{"answer":...}`.

If the question bridge cannot be made reliable with documented primitives, stop and report the exact limitation. Do not use UI automation or mutate Antigravity internals as a hidden workaround.

## Request Lifecycle
Canonical states:
`received -> pending -> presented -> answered -> consumed`

Optional:
`hidden` is presentation state only; the request remains `pending`.

Rules:
- `Esc` or window close NEVER means Deny/Cancel.
- Closing hides the modal to tray.
- Pending requests must survive modal hide.
- Never consume a response before the bridge confirms it was emitted.
- Deduplicate repeated hook events.
- Correlate every response with `conversationId + request_id`.
- Never allow one conversation to consume another conversation's response.

If a modal is already active, enqueue new requests instead of opening stacked dialogs. Default to FIFO.

## IPC
Local-only. Prefer QLocalServer/QLocalSocket.
No TCP listener.

Protocol requirements:
- JSON;
- explicit `type`;
- `request_id`;
- `conversation_id`;
- protocol version;
- structured success/error response.

Keep protocol serialization isolated in `ipc/protocol.py`.

IPC errors must fail clearly. If the daemon is unavailable, do not leave Antigravity hanging indefinitely.

## State
Prefer in-memory state. Persist only what is required for crash recovery/user experience.

If persistence is needed, use a small JSON file under XDG state/data directories. No database for MVP.

Bound queues and cached transcript context. Do not retain screenshots or large artifacts.

## UI Direction
Style: premium AI assistant.

The app should feel intentional, calm, compact, and modern—not like a default QMessageBox.

Target modal:
- width roughly 600–680 px;
- content-driven height;
- max ~70% of available screen;
- internal scroll for long text;
- clear hierarchy;
- generous but efficient spacing;
- rounded card-like sections;
- restrained shadows/borders;
- avoid decorative clutter.

Header:
- Ag Attention Bridge identity;
- project/workspace;
- model when available;
- subtle pending-count/status.

Context:
- latest relevant user message;
- latest relevant agent message;
- collapse/trim long context;
- context must never overpower the current interaction.

Current interaction gets highest visual priority.

### Question UI
Single-select -> radio controls.
Multi-select -> checkboxes.
If freeform is supported, provide a text area.
Options must be readable without horizontal scrolling.

### Permission UI
Show:
- Action
- Target
- Reason

Commands, paths, and code-like values use monospace styling.
Do not hide or sanitize normal Antigravity permission content unless required for rendering safety.

### Keyboard
- Esc: hide to tray, unresolved.
- Enter: submit only when action is unambiguous.
- Tab/arrow navigation must work.
- Focus the first meaningful decision control.

Do not use desktop notification balloons or notification sounds.

## Tray
Use QSystemTrayIcon.

Tray exists whenever daemon runs.
Left click:
- show active pending request;
- otherwise open queue/status.

Context menu:
- Open Pending Requests
- Show/Hide Current Request
- Open Logs
- Quit

Pending count must be visible as a numeric badge rendered into the tray icon (e.g. via QPainter). Do not depend on a platform badge API.

Closing the modal must leave the tray alive.

## KDE Wayland
Qt hint:
`Qt.WindowType.WindowStaysOnTopHint`.

Also document/use a KWin Window Rule for stronger behavior:
- Keep above: Force Yes
- Initial placement: Centered
- Accept focus: Yes
- Focus stealing prevention: None if required
- Skip pager: Yes
- Skip switcher: preferably Yes

Use `show()`, `raise_()`, and `activateWindow()` as best-effort hints. KWin is the authority for Wayland placement/focus.

Do not make manual absolute window positioning a core requirement.

## Performance
The daemon must be event-driven.
No polling loops for Antigravity state.
Idle CPU should be effectively zero.

Do not read entire transcripts repeatedly. Read only enough recent content for the modal.
Avoid unnecessary background threads/processes.
One hook adapter process per event is acceptable; persistent heavy workers are not.

## Code Structure
Prefer cohesive modules and explicit names. Suggested boundaries:

- `domain/`
- `ipc/`
- `hooks/`
- `antigravity/`
- `ui/`
- `state/`

Do not create abstraction layers before a second real use case exists.
Do not create empty placeholder files merely to match an architecture diagram.
Keep business logic out of widgets.

Use type hints for public/internal boundaries and domain models.
Prefer dataclasses/enums or equally simple typed structures.
Keep functions small enough to understand locally.
Avoid global mutable state except the single application/daemon ownership boundary.

## Error Handling
Never silently swallow exceptions.

Expected recoverable failures:
- malformed hook payload;
- daemon unavailable;
- socket disconnect;
- transcript unavailable/partially written;
- stale pending request.

User-impacting bridge errors must be visible in the app/logs and must not falsely mark a request resolved.

Hook stdout is protocol-only; errors go to stderr or log files.

## Testing Priority
Test behavior before visual polish.

Must test:
1. IPC encode/decode and request correlation.
2. Queue ordering/deduplication.
3. Esc/close leaves request pending.
4. tray count equals unresolved queue count.
5. permission allow/deny outputs exact hook JSON.
6. question bridge lifecycle with real Antigravity.
7. multi-conversation isolation.
8. transcript parser tolerates unknown/partial JSONL.
9. daemon restart/failure behavior.

For the question bridge, distinguish:
- documented behavior;
- experimentally observed behavior;
- assumptions still unproven.

## Agent Workflow
Before editing:
1. inspect only files relevant to the task;
2. identify current phase and acceptance criteria;
3. avoid repo-wide scans unless necessary.

While implementing:
- make the smallest coherent change;
- preserve architectural boundaries;
- do not refactor unrelated code;
- avoid speculative features;
- reuse existing helpers before adding dependencies;
- update tests with behavior changes.

After editing:
1. run focused tests first;
2. run broader tests only when warranted;
3. report files changed;
4. report what was verified;
5. explicitly call out unresolved lifecycle assumptions.

Do not claim a bridge works until tested against the real installed Antigravity build.

## MVP Scope
MVP includes:
- persistent system tray;
- numeric pending badge;
- external modal for `ask_question`;
- external modal for `ask_permission`;
- direct response without opening Antigravity;
- latest useful conversation context;
- Esc/close -> hide to tray;
- multi-session queue;
- KDE Wayland keep-above behavior.

Out of scope unless required:
- desktop notifications;
- sounds;
- remote/network access;
- cloud sync;
- plugin marketplace packaging;
- full transcript/chat client;
- unrelated Antigravity automation.

## Decision Principle
When several designs work, choose the one that:
1. uses documented Antigravity primitives;
2. is easiest to test;
3. has the fewest dependencies;
4. uses the least idle CPU/memory;
5. keeps the response path deterministic;
6. remains understandable for future GitHub contributors.
