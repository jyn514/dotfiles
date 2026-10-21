# pi-link design

This document describes the local fork's current architecture, protocol, and implementation constraints.
For installation, tool usage, configuration, and troubleshooting, read the [operator guide](README.md).
For test setup and commands, see [Fork development](README.md#fork-development).

## Contents

- [Limitations & Design Decisions](#limitations--design-decisions)
- [Dependencies](#dependencies)
- [Internals](#internals)

## Limitations & Design Decisions

| #   | Decision                                  | Rationale / Impact                                                                                                                                               |
| --- | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **No authentication**                     | Any localhost process can connect to port 9900. Acceptable for local dev; don't expose the port externally.                                                      |
| 2   | **Hardcoded port (9900)**                 | Not configurable without editing `DEFAULT_PORT` in `index.ts`. Could conflict with other services on the same port.                                              |
| 3   | **Race-based hub promotion**              | Non-deterministic. Reconnect order can change which terminal holds a hub-assigned suffix; in-flight messages can be lost. Simple but imperfect.                  |
| 4   | **No offline backlog**                    | A definitely absent target is rejected and nothing is stored, so a terminal that reconnects receives no messages it missed while offline.                        |
| 5   | **Client rename triggers full reconnect** | Changing a client's name requires a new `register` message, so the client disconnects and reconnects. Hub renames are handled in-place.                          |
| 6   | **Single-machine / localhost-only**       | Link only binds to `127.0.0.1`; terminals on different machines cannot join.                                                                                     |
| 7   | **Replies remain asynchronous**           | `replyTo` correlates messages but does not create a waiting request, delivery receipt, automatic response, or timeout. |
| 8   | **Groups isolate attention, not access**  | No auth: any process may pick any group, and `pi-link --status` shows all of them; isolation needs one version everywhere, so upgrade and restart together.      |

---

## Dependencies

At runtime pi-link needs one package, `ws` (^8.20.0), the WebSocket server and client; `pi install` brings it in. Development adds `@types/ws` (^8.18.1) for its type definitions. Everything else comes from Pi itself and needs no install: `@earendil-works/pi-coding-agent` for the SDK types (`ExtensionAPI`, `ExtensionContext`) and `VERSION`, `@earendil-works/pi-tui` for the Text widget used in custom message rendering, and `typebox` for the tool parameter schemas.

> See [Prerequisites](README.md#prerequisites) for supported Pi versions.

---

## Internals

> This section covers implementation details for contributors and developers who want to understand or modify the extension's internals.

### Hub-Spoke Topology

The network topology is **hub-spoke (star)**:

```
                       +-----------+
                       |    Hub    |
                       |   :9900   |
                       +-----+-----+
                             |
              +--------------+--------------+
              |              |              |
          +---+---+      +---+---+      +---+---+
          | pi-2  |      | pi-3  |      | pi-4  |
          |client |      |client |      |client |
          +-------+      +-------+      +-------+
```

- The **first terminal** to start becomes the **hub** - it runs a `WebSocketServer` on `127.0.0.1:9900`.
- **Subsequent terminals** connect as **clients** via plain WebSocket.
- All messages route **through the hub**; clients never talk directly to each other.

### Auto-Discovery Protocol

The discovery sequence runs on startup (with `--link` or `pi-link`) or when `/link-connect` is used. See [Configuration](README.md#configuration) for details.

The sequence is a simple fallback:

1. Attempt to connect as a **client** to `127.0.0.1:9900`. The WebSocket opening handshake is bounded at **5 seconds**; a listener that accepts the connection but never completes the upgrade fails the attempt instead of holding it open.
2. If connection fails → become the **hub** (start a WebSocket server on that port).
3. If both fail (rare race condition) → retry after a randomized 2-5 second backoff.

Only **one attempt runs at a time**, across both steps. Startup, a retry and `/link-connect` arriving while an attempt is in flight all join that attempt rather than opening a second connection, so a terminal cannot register twice or leave a second socket behind.

### Hub Promotion

When the hub disconnects, clients detect the WebSocket close event, enter `"disconnected"` state, and call `scheduleReconnect()`. The **first terminal to retry** becomes the new hub via the same initialize-or-fallback flow.

There is **no explicit leader election** - promotion is race-based.

The old hub transfers no shared roster or routing state to its successor: every terminal drops the snapshots it held for the network that went away - names, statuses, working directories and context - while its own local state, the inbox included, survives. Clients wait the same randomized 2-5 second backoff before retrying, so promotion usually lands in that window rather than within a guaranteed bound, and messages in flight while no hub is listening can be lost. Survivors that rejoin the winner as clients re-register with their saved preferred name rather than their prior runtime name (see [Name Uniqueness & Persistence](#name-uniqueness--persistence)), so a terminal that was `builder-2` may come back as `builder`, or take the suffix this time. The winner does not re-register at all: it starts the hub keeping the identity it was already running under, unless a `/link-name` rename was in flight when the old hub vanished, which it then adopts.

### Protocol

The wire protocol consists of the following message types, all serialized as JSON over WebSocket frames.
Cwd and context fields are optional.
New `chat` messages carry `id` and optional `replyTo`; these references are independent of terminal names.
Old hubs forward the additional fields, but old receivers discard them and old senders omit them.
Upgrade both peers for reply metadata; plain messages from older peers remain supported without invented IDs.

| Type               | Direction       | Purpose                                                                                             |
| ------------------ | --------------- | --------------------------------------------------------------------------------------------------- |
| `register`         | Client → Hub    | First message after connecting; requests a name, optionally reports cwd and context                 |
| `welcome`          | Hub → Client    | Confirms assigned name, terminal list + status/cwd/context snapshots                                |
| `terminal_joined`  | Hub → All       | Broadcast when a terminal joins; may include cwd and context                                        |
| `terminal_left`    | Hub → All       | Broadcast when a terminal disconnects                                                               |
| `chat`             | Any → Any       | Message delivered to the receiver's model: steered into a running agent, or starting a turn if idle |
| `compact_request`  | Any → Any       | Request a remote terminal to compact its context; awaits a response                                 |
| `compact_response` | Any → Any       | Completion/failure response for a compact_request                                                   |
| `status_update`    | Any → Hub → All | Terminal broadcasts agent status change; carries updated context                                    |
| `error`            | Hub → Client    | Error notification                                                                                  |

### Message Flow Examples

**Joining the link:**

```
Client                         Hub
  |                             |
  | register {name:"builder",   |
  |           cwd:"C:\\Users\\..."} |
  |---------------------------->|
  |                             |
  | welcome {name, terminals,   |
  | statuses, cwds}             |
  |<----------------------------|
  |                             |
```

Hub then broadcasts `terminal_joined` to the other connected terminals.
The `welcome` message includes status, cwd, Pi session ID, and context snapshots for connected terminals.
`register`, `terminal_joined`, and `status_update` carry an optional `sessionId`; `welcome` carries a name-keyed `sessionIds` map.
Peers that omit these fields remain supported.

**Sending a chat message:**

```
Client A            Hub              Client B
  |                  |                  |
  | chat {to:pi-2}   |                  |
  |----------------->|                  |
  |                  | chat {from:A}    |
  |                  |----------------->|
  |                  |                  |
```

### Name Uniqueness & Persistence

The hub enforces unique terminal names via a `uniqueName()` function. If `"builder"` is already taken, the next terminal requesting that name is assigned `"builder-2"`, then `"builder-3"`, and so on.

Default names are random 4-character hex IDs: `t-a1b2`, `t-c3d4`, etc.

**Groups (`local@group`):** see [Configuration](README.md#configuration) for the rule a user needs. Internally, the hub serves every group over one set of connections; for the targeted traffic it handles, `routeMessage()` treats a target in another group as not found. Collisions suffix the local part only, so a deduped name never changes group: `builder` becomes `builder-2`, `archon@pi-link` becomes `archon-2@pi-link`.

**Persistence:** `/link-name` saves the preferred name to the session via `pi.appendEntry("link-name", { name })`. On session resume, the saved name is restored and requested from the hub. Startup naming (`pi-link <name>`, `pi --link-name <name>`) persists the same way - hub-assigned variants like `"builder-2"` are not saved. On reconnect, the terminal always requests the preferred name, not the last runtime name.

**Rename guards:**

- If you're already using the requested name, `/link-name` returns early (`"Already using..."`).
- On the hub, renaming checks if the name is taken by another connected client before accepting the change.
- On a client, the rename triggers a reconnect; the hub enforces uniqueness during re-registration and may assign a different name if taken.

**Unregistered client guard:** The hub ignores all non-`register` messages from clients that haven't completed registration, preventing protocol violations from malformed or out-of-order messages.

### State Management

| State Field               | Type                                  | Purpose                                                                                                                     |
| ------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `role`                    | `"hub" \| "client" \| "disconnected"` | Current network role                                                                                                        |
| `connectionAttempt`       | `record \| null`                      | The one establishment attempt in flight: its shared promise plus any pending socket/server. Object identity marks the owner |
| `agentRunning`            | `boolean`                             | Between `agent_start` and `agent_settled` — not `agent_end`; drives status only                                             |
| `compactRunning`          | `boolean`                             | Whether a remote request holds this terminal's delivery gate                                                                |
| `localCompacting`         | `boolean`                             | Whether a `manual`-reason compaction has raised the delivery gate                                                           |
| `activeTools`             | `Map`                                 | `toolCallId` → `toolName` for calls still running; the first drives status                                                  |
| `stateSince`              | `number`                              | Timestamp of last status change (used for duration display)                                                                 |
| `currentCwd`              | `string`                              | Current working directory reported to peers on connect                                                                      |
| `inbox`                   | `array`                               | Queued incoming messages awaiting delivery                                                                                  |
| `flushTimer`              | `Timer \| null`                       | Pending inbox flush; armed by the first queued message and not moved afterwards                                             |
| `compactDeadline`         | `Timer \| undefined`                  | Backstop releasing the inbox if a compaction reports no ending                                                              |
| `pendingCompactResponses` | `Map`                                 | Outstanding compact requests awaiting bounded responses                                                                     |
| `disposed`                | `boolean`                             | Set on shutdown; guards WebSocket callbacks against stale context                                                           |
| `startupConnectTimer`     | `Timer \| null`                       | Deferred startup connect so Pi's startup cycle completes first                                                              |
| `manuallyDisconnected`    | `boolean`                             | Set by `/link-disconnect`; suppresses auto-reconnect                                                                        |

### Message Routing & Error Handling

`routeMessage()` returns a `boolean` indicating delivery status:

- **Hub** - delivery is authoritative. If a chat target is not connected, the hub sends a protocol-level error back to a client sender; a local hub sender already receives the failed delivery result. A `compact_request` to an unknown target gets a synthesized `compact_response` (`ok: false`, `reason: "not_found"`), so the bounded compact call fails fast.
- **Client** - delivery is optimistic (`true` means "sent to hub"). The hub handles routing and errors via the protocol.

### Connection Lifecycle

Internally, teardown is split into two functions:

- **`disconnect()`** - closes sockets, clears connection state, resolves pending promises. Used by `/link-disconnect` and called internally by `cleanup()`.
- **`cleanup()`** - calls `disconnect()`, sets `disposed = true`, clears `ctx`. Used on `session_shutdown`.

Three helpers protect WebSocket callbacks from stale extension context:

- **`getUi()`** - safely accesses `ctx.ui`, returns `null` if the context is invalidated.
- **`notify()`** - wraps `getUi()?.notify()` for safe notification delivery.
- **`isRuntimeLive()`** - returns `false` if `disposed` or context is stale; checked before processing any incoming WebSocket message.

Startup connect is deferred via `scheduleStartupConnect()` (`setTimeout(0)`) so Pi's startup cycle completes and the extension context is fully valid before WebSocket work begins.

`disconnect()` also cancels the connection attempt in flight: it invalidates the attempt first, then closes whatever it had pending - a dialing socket or a binding server - so nothing can finish establishing after the user asked to disconnect. The startup and retry timers are cancelled on the same path, so `/link-disconnect` before the deferred startup connect opens nothing at all. Because ownership is tracked per attempt, a callback from a superseded or cancelled transport is inert: only the established socket (`ws`) may deliver messages or tear down client state, and only the established server (`wss`) may accept clients.

The `manuallyDisconnected` flag distinguishes user-initiated disconnects (`/link-disconnect`) from connection loss. When set, `scheduleReconnect()` is suppressed - the terminal stays offline until `/link-connect` is explicitly called.

### Agent Lifecycle Integration

The extension hooks into Pi's agent lifecycle events:

- **`agent_start`** → Sets `agentRunning = true`, which drives status. Clears the local compaction gate (`localCompacting`, never a remote request's `compactRunning`) - safe only under the current deployment, not by Pi alone: Pi refuses to start an ordinary prompt during a manual compaction, and pi-link holds back the one delivery path that refusal does not cover, so nothing can start a run mid-compaction. Another extension starting a turn during one would void that. Status normally becomes `thinking`.
- **`agent_end`** → Drops any tool calls still recorded, so an unmatched one falls back to `thinking` instead of staying pinned. It deliberately does **not** end the run: Pi may still retry, compact automatically, or drain a queued continuation, so the status stays `thinking`.
- **`agent_settled`** → The authoritative end of a run: Pi emits it once no retry, compaction or queued continuation is left. Status becomes `idle` — unless the event's context reports Pi busy again, which means another extension started a new run during settlement, and that newer run keeps reporting `thinking`.
- **`tool_execution_start`** → Records that call. It is displayed unless an earlier call is still running.
- **`tool_execution_end`** → Drops that one call. The display stays `tool:<name>` while other calls remain, moves to the next call when the displayed one ends, and returns to `thinking` after the last one while the agent run continues.
- **`session_before_compact`** → For a manual compaction, raises the gate that holds inbox delivery. Automatic (threshold/overflow) compaction is left alone: it runs inside the agent run, where Pi already queues and drains steered messages itself.
- **`session_compact`** → Clears the local compaction gate and force-pushes a `status_update` so peers see the new (post-compaction) context usage immediately.
- **`model_select`** → Force-pushes a `status_update`: the context window, and so the usage percentage, belongs to the model.
- **`session_tree`** → Force-pushes a `status_update`: context usage belongs to the active branch.
- **`session_shutdown`** → Full cleanup via `cleanup()`: closes all sockets, resolves pending promises, and disposes the extension.

The five agent and tool handlers — `agent_start`, `agent_end`, `agent_settled` (when Pi still reports the session idle), `tool_execution_start` and `tool_execution_end` — each recompute the status and hand it to `pushStatus()`, which publishes only when the display identity changed since the last publish: a second concurrent tool starting behind the one already shown is silent, and so is a mutation that leaves a raised compaction gate on display. The session handlers keep the separate paths described in their own bullets, and `session_shutdown` cleans up rather than pushing. `disconnect()` is the only thing that clears the stored baseline, and `pushStatus()` returns immediately while the terminal is disconnected, so handler events in that interval restore nothing; once connected again, either a client's forced `welcome` push or the first of those ordinary handler events restores it. `session_compact`, `model_select` and `session_tree` always push, whether the identity changed or not — including while a remote request's gate still holds the displayed identity.

Status updates are push-based: each terminal broadcasts changes to the hub, which fans them out. New joiners receive a status snapshot for all terminals in the `welcome` message. Context updates reuse the same status path, including forced updates after a compaction, a model change and tree navigation.

### Inbox

An arriving `chat` message goes into a local inbox rather than calling `pi.sendMessage()` immediately, so that arrivals close together can be coalesced into a single delivery.

The flush pipeline:

1. **Fixed window** - `scheduleFlush(FLUSH_DELAY_MS)` arms a timer only when none is pending, so the first queued message sets the deadline (about 200ms) and later arrivals join that window without moving it. The window is not sliding: sustained arrivals closer together than the delay cannot postpone delivery.
2. **Compaction gate** - `flushInbox()` returns without rescheduling while the compaction gate is raised.
3. **Batch** - up to 20 messages or ~16 000 chars per delivery, including ID and reply annotations (soft cap - the first item is always included even if oversized).
4. **Deliver** - one `pi.sendMessage()` call with a `[Link: N message(s) received]` block. Pi reads the receiver's state at this point — not at send time — to decide whether the batch steers a running agent or starts a turn.
5. **Drain** - if the inbox still has items, reschedule.

Delivery is held while a `manual`-reason compaction holds this terminal's gate, because a message delivered mid-compaction would be reasoned about against context that is being rebuilt. Two flags gate it: `compactRunning` for a compaction serving a remote `link_compact`, and `localCompacting`, set from `session_before_compact`; a remote request raises `compactRunning` first and adds `localCompacting` only if its compaction reaches that hook, since Pi reports its own reason as `manual` either way. Automatic (threshold/overflow) compaction is deliberately **not** gated: it runs inside the agent run, where Pi already queues steered messages and drains them afterwards. Because a gated flush does not reschedule, the release path is load-bearing: `releaseInbox()` runs after either flag clears and schedules a flush only when neither gate remains, and `compactDeadline` is the backstop for a `localCompacting` left raised, since failure emits no lifecycle ending event that clears it.

| Constant             | Value   | Purpose                                          |
| -------------------- | ------- | ------------------------------------------------ |
| `FLUSH_DELAY_MS`     | 200     | Batching window, from the first queued message   |
| `BATCH_MAX_ITEMS`    | 20      | Max messages per batch                           |
| `BATCH_MAX_CHARS`    | 16 000  | Soft cap on batch text size (~4K tokens)         |
| `COMPACT_TIMEOUT_MS` | 300 000 | Remote-compact wait, reused as the gate backstop |

### Remote compaction

A `compact_request` that passes the capability and idle checks is served by calling `ctx.compact()` — the same operation as `/compact`. The caller is answered when the runtime reports a result through `onComplete`/`onError`. Each call targets one terminal, independent calls can run concurrently, and link participants are cooperating peers: nothing here is privileged.

Serving a request raises the inbox gates in order, and not always both. `compactRunning` is set synchronously before `ctx.compact()` is called; `localCompacting` rises only if execution reaches the manual `session_before_compact` hook, so a runtime that refuses early — nothing to compact, already compacted, or another preparation failure — returns through `onError` without the local gate ever going up. When the compaction does succeed, `session_compact` clears the local gate first, and the later `finish()` clears `compactRunning` and calls `releaseInbox()`, which is what drains the inbox.

What a failure hides is the ending, not the failure itself. A remote compaction reports its error through `onError`, which runs `finish()` and answers the caller, so `compactRunning` always comes back down. But `session_compact` is a success-only ending and pi-link does not listen to Pi's `session_compact_failed`, so a `localCompacting` already raised by the hook stays up until the target's next agent run (`agent_start`), a later successful compaction, or the `compactDeadline` backstop 300 seconds after that gate rose. A human `/compact` has no result callback at all, so those three are its only release paths.

Those 300 seconds are two independent timers, not one synchronized deadline: the caller's bounded wait uses `COMPACT_TIMEOUT_MS` to stop waiting, and the local gate backstop reuses the same constant only to avoid inventing a second one. Aborting the caller before the request goes out leaves the target untouched; aborting after it goes out stops the caller from waiting and nothing else — the target's compaction, once started, runs to its own end.

### Rendering

Delivered link batches render with a styled `⚡ [link]` prefix using the theme's accent color.
Sender attribution and message IDs appear inside the message body, not in the prefix.
The link status text in Pi's footer uses `theme.fg("dim", ...)` to match Pi's standard footer styling.

Deliveries sit in the same background panel Pi draws around extension messages by default, indented by your configured output padding.
Message IDs and `Reply to` lines render as part of each message's content, including after session restore.
The collapsed six-row preview may hide later annotations in a batch; use Pi's expansion shortcut to see the full panel.
This is correlation, not a nested thread view or a link to the original message.

A long delivery is previewed rather than printed whole. Collapsed, it shows the first six rows as they wrap at the current window width, followed by `... (N more lines, ctrl+o to expand)`; a message that already fits in six rows shows in full with no hint. Expanding is Pi's own global toggle — `Ctrl+O` unless you have rebound `app.tools.expand`, and the hint always names your actual binding — so it expands every custom message at once, including messages restored from an earlier session. If you have unbound `app.tools.expand` entirely there is no key to name, so both hints read `bind app.tools.expand to expand` instead. Only the display changes: the full text is what reaches the model, what `link_send` delivered, and what the session file keeps.

The same toggle also expands outgoing calls: `link_send` and `link_compact` collapse the message or instructions into a one-line preview — runs of whitespace become single spaces — and keep its first 60 characters, which a narrow terminal may still wrap onto more than one row. Expanding reveals the uncollapsed text with its line breaks and spacing as rendered by Pi. Expanding a call says nothing about delivery — the tool's own result line reports that.
