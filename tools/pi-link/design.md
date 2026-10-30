# pi-link design

This document describes the local fork's root APIs and versioned manager/child integration.
Root identity, group broadcast, and delivered-author reply APIs are implemented.
Worker delivery requires the supported installed `pi-codex-subagents` manager/child bridge; absent integration reports unsupported without parent-model forwarding.
For installation, tool usage, configuration, and troubleshooting, read the [operator guide](README.md).
For test setup and commands, see [Fork development](README.md#fork-development).

## Contents

- [Root APIs and worker integration](#root-apis-and-worker-integration)
- [Limitations & Design Decisions](#limitations--design-decisions)
- [Dependencies](#dependencies)
- [Internals](#internals)

## Root APIs and worker integration

The root APIs let agents choose useful link identities and send one correction to several connected roots.
Worker inclusion delivers through the installed owner manager; without it, that owner reports `unsupported`.

Without group broadcast, a correction sent to one root agent must be relayed to other roots and their workers.
A root agent is a connected Pi session that may own delegated workers.
For example, a correction from “assess voice” to “assess directness” must reach a worker already preparing a voice-based test.
The worker integration does not depend on the parent model finishing its current work and remembering to forward the correction.
Agents also need to choose their own names and groups without replacing identities the user assigned.

### `link_set_identity`

```typescript
link_set_identity({ name: "prose-reviewer", group: "prose" });
link_set_identity({ group: "prose" }); // Keep the current local name.
link_set_identity({ name: "reviewer" }); // Keep the current group.
```

`name` is the local part of the link identity, not the full `name@group` string.
`group` is the suffix after the first `@`.
There is no separate group-creation operation: matching suffixes define membership.

- Both fields are optional, but at least one must be supplied.
- Omitted fields retain their values and ownership.
- A supplied name must be nonempty after the existing whitespace normalization and must not contain `@`.
  This prevents a name update from changing a separately protected group.
- A supplied group uses the existing whitespace normalization; `""` selects the implicit group of ungrouped terminals.
  Preserve the existing first-`@` rule, including groups whose text contains another `@`.
- The operation changes only this session's link identity, not its Pi session name, title, or selected session file.
- It does not reconnect a session the user explicitly disconnected.
  An offline change saves the preference for the next connection.

**User ownership takes precedence.**
Store the preferred local name and group with separate origins: `generated`, `agent`, or `user`.
Agents may change generated or agent-chosen fields, but may not replace user-chosen fields.
An unchanged user-owned field is a no-op and remains user-owned.
If any requested field would replace a user-owned value, reject the whole update without changing either field.
Return which fields are protected and the current identity; do not offer an agent-side override.
User naming commands can replace agent choices.
A manual assignment claims ownership of its explicit fields even when their text already matches the current values.

Manual naming inputs must record ownership when they are accepted:

- An explicit user local name owns the name field.
- An explicit `@group` suffix owns the group field, including an empty suffix used to select the ungrouped group.
- A plain name that leaves an already empty group unchanged does not claim that default group.
  The agent can still choose a group even when the user supplied its name.
- A manual combined-name update that removes an existing nonempty group records user ownership of the resulting empty group.
  Preserve the current `/link-name` behavior rather than silently retaining a removed suffix.
- A Pi session-name fallback with unknown authorship is protected as user-owned.
  Do not assume a session name was generated or agent-selected without provenance.

Persist ownership with the preferred values so reload and resume cannot remove the user's protection.
Existing `link-name` entries contain only a combined name, with no ownership information.
Treat both components of those legacy saved identities as user-owned when their origin is unknown.
Do not infer permission to rename from spelling, including a name that looks like `t-1234`.
Fresh default identities can be agent-renamable because their generated origin is known.

Client updates reuse the reconnect behavior described in [Name Uniqueness & Persistence](#name-uniqueness--persistence).
Agent hub updates suffix collisions; existing manual hub updates still reject a colliding name.
The hub still assigns unique runtime names; ownership applies to preferences, not collision suffixes.
Repeating an unchanged preference preserves the assigned collision suffix.
Explicit disconnect cancels a pending rename without discarding the saved preference.
Persist an optional `explicitGroup: true` with the preference to preserve an explicit empty suffix such as `reviewer@`.
Tool details return `preferred` (values, origins, and optional `explicitGroup`), `assignedName`, `connectionState`, and `pending`.
`assignedName` is `null` offline; `connectionState` is `hub`, `client`, or `disconnected`.
Do not report a pending reconnect or requested name as an already assigned identity.

A group change removes this session from its former group's visibility and targeting.
Agents must agree on the group before moving; these APIs do not discover or contact other groups.
Changing group does not revoke messages already queued under the previous membership.

### Broadcast through `link_send`

Keep the current direct-send call and add an explicit broadcast target:

```typescript
link_send({
  to: "reviewer@prose",
  message: "The condition is missing.",
  replyTo: "<received-message-id>",
});

link_send({
  to: { broadcast: true },
  message: "Assess directness, not voice. Stop tests based on the voice interpretation.",
  includeSubagents: true,
});
```

- `to` accepts either one terminal-name string or exactly `{ broadcast: true }`.
  An object avoids reserving a currently valid terminal name such as `all` or `*`.
- `message` remains required; `replyTo` remains optional and does not select recipients.
  For broadcasts, an empty `replyTo` is treated as omitted.
- `includeSubagents` defaults to `false` and may be `true` only for a broadcast.
  Direct sends remain one-recipient operations.
- Broadcast selects connected root sessions in the sender's current group, excluding the sending session.
  It never means every terminal on the hub and never infers membership from cwd.
- All plain names share the empty group.
  A broadcast there reaches unrelated ungrouped sessions too; use a named group for project-specific corrections.

The hub selects the root recipients once when it accepts the broadcast.
Later joins do not receive it, and later membership changes do not retract an accepted copy.
There is no subscription, offline backlog, or replay on reconnect.
The existing all-groups `hubBroadcast()` used for membership and status traffic is not the chat broadcast operation.

Generate one message UUID and preserve it, the sender attribution, content, and optional `replyTo` across all copies.
Show that a received message was broadcast, so recipients do not mistake it for an individual assignment.
Root recipients can use `link_reply` with that UUID to resolve the delivered author by session identity.
An ordinary direct `link_send` may still carry `replyTo` as unchecked correlation only.
Manager-delivered messages use the delivered-author reply API below; receiving a broadcast does not itself grant additional tools.
There is no automatic response or reply-all.
The existing inbox batching, busy/idle delivery behavior, and compaction holds still apply to root deliveries.

#### Active subagents

The installed manager supplies worker callbacks through synchronous `pi-link:workers:v1` discovery with `{ version: 1, ownerSessionId, provide(integration) }`.
Root discovers per operation, not at startup, and the manager selects only active own workers.
Without the bridge, `includeSubagents: true` reports `unsupported` worker outcomes, including for the sender.

With `includeSubagents: true`, include active subagents owned by each selected root and by the sending session.
Excluding the sender from its own root delivery must not exclude its workers from the correction.
Each owner selects its active workers once when it handles the broadcast.
Root selection and worker selection are not one atomic snapshot across processes.
Workers started after the owner's selection do not receive the message.

The owning `pi-codex-subagents` extension must perform worker delivery without invoking the parent model.
Children load configured extensions unless their template disables them.
The manager bridge does not require a child link connection; templates can disable pi-link while retaining bridge delivery and replies.
Do not infer parentage from names or cwd, or access another owner's workers.

This requires a supported integration point between pi-link and the subagent extension.
The subagent extension remains authoritative for worker identity, lifecycle, pause state, and RPC steering.
The child helper requires native `ctx.submitInput()` and pause APIs to acknowledge active-only steering admission.
Missing capabilities report `unsupported`; no raw-prompt or restart fallback replaces them.
It needs an active-only delivery operation: its existing `sendMessage()` may restart a completed child and is not sufficient as-is.
Deliver the original sender, message ID, and broadcast context to the worker rather than presenting the correction as a new parent-authored assignment.

- Include workers still starting or running when their owner selects them.
- Never restart a completed, failed, or interrupted worker to deliver a broadcast.
- Never resume a suspended worker or bypass the owner's pause handling.
- If a selected worker finishes or becomes unavailable before delivery, report it as skipped rather than starting another turn.
- If the integration is unavailable, report unsupported worker delivery rather than silently claiming all workers were included.

Normal worker task results continue through their parent channel.
Workers may ask a message's sender for clarification through the reply-only API below.
Independent link connections and the ordinary pi-link tools follow extension configuration and explicit template tool lists, not worker role.
Automatic recursive delivery to deeper descendant managers is outside this proposal.

#### Delivered-author replies and worker conversations

Root-to-root `link_reply` and the worker exchange below use admitted transcript references; workers additionally require the installed manager/child bridge.
A worker receiving a directness correction may need to ask whether it applies to quoted source material.
Requiring the parent model to relay both the question and answer would recreate the delay broadcast delivery removes.
Allow a private conversation with that sender, without arbitrary outreach or broadcast:

```typescript
// With manager integration: ask the sender of a delivered correction.
link_reply({
  replyTo: "<received-correction-id>",
  message: "Does this also apply to quoted source material?",
});

// With manager integration: root answers through the worker's manager.
link_reply({
  replyTo: "<received-worker-question-id>",
  message: "No. Preserve quoted source wording; assess only our explanation.",
});
```

`link_reply` is available to roots with required `replyTo` and `message` fields.
The manager/child integration itself supplies only this reply API; an enabled pi-link extension additionally registers its ordinary tools.
It has no `to`, recipient-list, broadcast, or worker-inclusion option.
One call replies to the original author of one message delivered to the caller, never to everyone who received that message.
A received broadcast therefore permits a private reply to its sender, not to its audience.

Unlike the optional correlation field on existing `link_send`, this `replyTo` selects the destination.
For roots, resolve it from the actual transcript of messages admitted to this Pi session's model input.
Outgoing custom `link` batches carry minimal references in `details.deliveries` and the receiver's `recipientSessionId`.
Only native Pi `message_end` for a matching admitted custom `link` message confers reply permission.
Calling `pi.sendMessage()` only queues steering; a queued or cleared copy does not grant reply permission.
The worker bridge must maintain the equivalent per-worker delivery authority.
A caller-supplied UUID alone is not evidence of delivery and must not allow arbitrary routing.
Unknown or ineligible references fail without sending a message.

Root authors are identified by Pi session ID, not only by a mutable terminal name.
Worker authors must be identified by their owning root session and stable `workerId` from the subagent manager.
`taskName` is display metadata, not a lookup key; reusing it must not redirect a reply.
The owning extensions attach this attribution; the worker cannot claim another sender or parent.
Replies get their own UUIDs and retain the answered message's UUID as `replyTo`.
A reply received by a root or worker can itself be answered, so the clarification exchange can continue.
Never substitute a different session that later acquires the original sender's terminal name.
Existing group restrictions still apply between owning roots; a reply does not bypass a subsequent group change.

The subagent bridge transports worker replies and incoming answers without asking the parent model to forward them.
An answer to a worker's question goes only to that worker, not to its siblings or its parent's model context.
Keep both directions visible in the owning session's worker transcript for inspection.
This bridge is independent of any pi-link connection separately enabled in the worker.

Worker answers use the same active-only lifecycle rules as broadcast delivery.
If the destination worker finishes, pauses, or becomes unavailable, report that outcome instead of restarting, resuming, or queueing work.
If the original root is offline or outside the permitted group, report the routing failure without choosing a fallback recipient.
Unavailable reply integration is reported as unsupported, not silently replaced by model-mediated forwarding.
Root reply receipts identify the new message ID and the resolved destination with an honest routing outcome.
The worker reply path preserves that contract.
Do not wait for the recipient's model response.

No automatic acknowledgment, reply-all, parent rebroadcast, or forwarding rule is introduced.
Workers reply for needed clarification or requested answers, not unsolicited receipt notifications.
Unicast prevents every worker from seeing every response; it cannot prevent several workers from independently asking the sender the same question.
Ask only when an answer can change the next action.
Do not add semantic deduplication, a suppression registry, or a wait period.
Roots broadcast general clarifications to the current group with `includeSubagents: true`, inspecting each owner and worker outcome.
Task-specific answers stay private through `link_reply` to the received message.
Normal task completion still goes to the parent, not through `link_reply` merely because a broadcast was received.

#### Routing receipt and failures

Broadcast waits for a bounded transport-level routing receipt, not for model responses.
Receipts identify selected roots and selected workers under their owning sessions, or explicitly report unavailable owner integration.
Use Pi session IDs for roots and owner-session ID plus stable `workerId` for workers.
Task names are display metadata; names alone do not establish parentage or worker identity.
Report successful submissions, known failures, skipped workers, and unknown outcomes separately.

Submission means the relevant transport accepted the copy, not that a model read, understood, or applied it.
A root can accept a copy while compaction still holds its model-visible inbox.
A worker result cannot be claimed merely because its parent accepted the root copy.
A failure for one recipient does not undo or suppress successful submissions to others.
If a receipt is lost or the bounded wait expires, report an unknown outcome; do not turn that uncertainty into success or known failure.
Do not automatically retry copies whose submission outcome is unknown.
An empty recipient set is reported explicitly, not as a message received by someone.

Direct sends retain their current asynchronous result and do not acquire stronger delivery guarantees from this addition.
The current messaging capability is `messagingVersion: 2`, advertised in registration, welcome, and membership metadata.
A client checks the hub capability before sending a broadcast or delivered-author reply.
The hub checks each selected root's capability and session ID; old peers produce explicit `unsupported` outcomes.
This does not add capability requirements to legacy direct `chat` sends.

The messaging module owns these JSON frames:

- `link_request`: version, UUID `id`, `operation` (`broadcast` or `reply`), `message`, and optional `replyTo`.
  Broadcast requests may set `includeSubagents`; replies carry a resolved `destination` with `name` and `sessionId`.
  A worker destination additionally requires both `workerId` and `taskName`.
- `link_receipt`: version, request `id`, `outcomes`, and `empty`.
- `link_delivery`: version and the message's `from`, `fromSessionId`, `content`, `id`, optional `replyTo`, and optional `broadcast` marker.
- `link_workers`: version, owner request `requestId`, message, and optional destination pair `workerId` and `taskName`.
- `link_worker_receipt`: version, owner request `requestId`, and worker outcomes.

Frames use `type` for the frame name and `messagingVersion: 2` for the wire version.
Version 1 hubs ignored worker attribution, so all receipt-based operations require v2 end-to-end instead of silently routing worker answers to the owner root.
The in-process manager events remain version 1; ordinary legacy direct chat is unchanged.

An outcome carries `kind` (`root`, `workers`, `worker`, or `routing`), `name`, optional `sessionId`, `status`, and optional `reason`.
Individual worker outcomes also require `workerId` and `taskName`.
Statuses are `submitted`, `failed`, `skipped`, `unsupported`, and `unknown`.
Tool details expose `{ messageId, operation, outcomes, empty }`, plus `error` when at least one outcome exists and none is `submitted`.
Model-visible text includes the full message ID and each reported recipient's identity, status, and reason.
A lost broadcast receipt explicitly leaves both recipient selection and submission outcomes unknown.

The optional `fromWorker` attribution names `ownerSessionId`, `workerId`, and `taskName`.
Only reply requests may carry it; the hub requires its owner session to equal the registered source socket session, and derives the root author from that socket.
It does not permit broadcast or replace root author identity.

The in-process manager emits `pi-link:worker-reply:v1` with version, current `ownerSessionId`, stable worker address, admitted child `reference`, message, and `respond(Promise<LinkResult>)`.
Root verifies the current owner and calls `respond` synchronously during event emission, resolving the destination from the manager-authoritative reference, not its own root references.
The manager is responsible for validating child transcript admission before emitting.
Worker metadata survives owner-to-hub-to-recipient transport.

`PI_SUBAGENT_OWNER_TOKEN` does not suppress pi-link. Template extension exclusions decide whether a managed child loads it; explicit tool lists decide which ordinary tools the model can use.
When both packages load, pi-link owns public `link_reply`; the helper registers a fallback at `session_start` only if that tool is absent.
Before independent endpoint routing, pi-link synchronously emits `pi-link:child-reply:v1` with `{ version: 1, replyTo, message, signal, respond(Promise<LinkResult>) }`.
The helper claims only an admitted manager-delivery reference in this child's transcript and reuses its normal reply implementation.
No claim means ordinary pi-link reply resolution; a claim selects the manager route permanently, including failure or unknown outcomes, without retrying on the endpoint.

The caller's routing deadline is five seconds (`ROUTING_DEADLINE_MS = 5_000`).
Owner-worker receipt waits use half that deadline (2.5 seconds), leaving time for aggregation.
The manager bounds its own delivery wait at two seconds, inside that owner receipt deadline.
A missing worker callback reports `unsupported` with `worker_integration_unavailable`.
A lost routing receipt reports `unknown` with `routing_deadline`; a lost owner receipt uses `worker_routing_deadline`.
Abort before submission reports `skipped`; abort after submission or disconnect while waiting reports `unknown`.
Neither abort nor deadline retracts accepted copies or cancels recipient work.
There are no automatic retries.
There is no read acknowledgment, completion timeout, cancellation of work, or authority to expand a recipient's task scope.

### Implementation boundaries and checks

The implemented boundary comprises root `link_set_identity`, group broadcast through `link_send`, and `link_reply` to admitted root-message authors.
Direct sends, existing user naming entrypoints, collision behavior, and saved session identity remain supported.
Identity provenance is persisted separately from runtime collision suffixes; unknown legacy ownership stays protected.
Root delivery references survive reload and resume through actual persisted `type: "custom_message"`, `customType: "link"` transcript entries.
On `session_start`, reset the previous session's reference state and replay only entries matching the current receiver's session ID.
The admitted transcript is authoritative; do not persist duplicate reference entries.
Root event discovery and worker-reply routing connect the structural manager bridge without importing the manager package.
Actual worker selection, steering, child tool exposure, private transcript records, and per-worker admission remain manager/helper responsibilities.
Root routing and structural manager fixture tests alone do not prove the actual manager/helper integration.

Verify root behavior through native Pi sessions.
Worker checks below additionally require the actual subagent manager/helper, not just structural callback fixtures:

- Generated and agent-chosen names can change, while manual and unknown-origin legacy names remain protected after reload and resume.
- Name and group ownership are independent; attempted protected updates leave both fields unchanged.
- Collision suffixes, partial identity updates, disconnected preferences, and group moves report the actual resulting identity.
- A broadcast reaches only the selected group, excludes the sender's root context, and preserves one UUID across recipient copies.
- Replies remain direct, and no terminal name becomes reserved by the broadcast syntax.
- Worker inclusion reaches the sender's workers too, without waiting for the parent model.
- Manager-bridge replies require a message delivered to that worker, with no arbitrary destination or broadcast option; other tool access follows template policy.
- A worker's clarification and the root's answer each reach one recipient without parent-model forwarding or sibling delivery.
- Worker attribution and reply references survive the exchange; renaming or name reuse never redirects it to another session.
- Unknown references, group changes, unsupported integration, and unavailable reply recipients produce explicit failures.
- Finished and paused workers are not restarted or resumed, including a worker that finishes during delivery.
- Root and worker submission failures, unavailable integration, lost receipts, and unsupported peers remain distinguishable.
- Late joiners and newly started workers receive no replay; partial failures do not duplicate successful copies.

## Limitations & Design Decisions

| #   | Decision                                  | Rationale / Impact                                                                                                                                               |
| --- | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **No authentication**                     | Any localhost process can connect to port 9900. Acceptable for local dev; don't expose the port externally.                                                      |
| 2   | **Hardcoded port (9900)**                 | Not configurable without editing `DEFAULT_PORT` in `index.ts`. Could conflict with other services on the same port.                                              |
| 3   | **Race-based hub promotion**              | Non-deterministic. Reconnect order can change which terminal holds a hub-assigned suffix; in-flight messages can be lost. Simple but imperfect.                  |
| 4   | **No offline backlog**                    | A definitely absent target is rejected and nothing is stored, so a terminal that reconnects receives no messages it missed while offline.                        |
| 5   | **Client rename triggers full reconnect** | Changing a client's name requires a new `register` message, so the client disconnects and reconnects. Hub renames are handled in-place.                          |
| 6   | **Single-machine / localhost-only**       | Link only binds to `127.0.0.1`; terminals on different machines cannot join.                                                                                     |
| 7   | **Replies remain asynchronous** | `link_reply` waits only for routing outcomes, not model responses; `link_send.replyTo` remains unchecked correlation. |
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

The discovery sequence runs on startup by default, with explicit startup naming, or when `/link-connect` is used.
See [Configuration](README.md#configuration) for details.

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
Old hubs forward additional direct-chat fields, but old receivers may discard them and old senders omit them.
Plain direct messages remain supported without invented IDs or author references.
Broadcast and `link_reply` use the capability-checked frames described under [Routing receipt and failures](#routing-receipt-and-failures).

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

Root default names are random 4-character hex IDs: `t-a1b2`, `t-c3d4`, etc.
Managed children default to `<parent-local-name>-subagent-<four-random-hex>` in the parent's group, prepending `t-` only if the parent name does not already start with it.
This is only the generated fallback; startup overrides, saved identity, and Pi session names retain their existing precedence.

**Parent handoff:** pi-link publishes `PI_LINK_PARENT_IDENTITY` as JSON `{ version: 1, sessionId, name }`, using its current assigned combined name, including collision suffixes.
The subagent manager copies the environment at launch and supplies `PI_SUBAGENT_PARENT_SESSION_ID` for the immediate parent.
The child uses the snapshot only when that ID matches; missing, malformed, unsupported, or mismatched snapshots keep the independent random default.
This environment handoff is a naming hint, not proof of parentage for routing or access.
Each child publishes its own snapshot for its children.
Accepted runtime name changes refresh the snapshot, including offline renames and hub assignments; shutdown removes the runtime's snapshot if it still owns it.
The child's generated identity persists through the normal `link-identity` entries, so later parent renames do not change an existing child's name.
Neither inherited component claims user ownership or changes the child's Pi session title.

**Groups (`local@group`):** see [Configuration](README.md#configuration) for the rule a user needs. Internally, the hub serves every group over one set of connections; for the targeted traffic it handles, `routeMessage()` treats a target in another group as not found. Collisions suffix the local part only, so a deduped name never changes group: `builder` becomes `builder-2`, `archon@pi-link` becomes `archon-2@pi-link`.

**Persistence:** accepted naming updates save `link-identity` entries with local name, group, per-field origins, and optional explicit-empty-suffix spelling.
Legacy `link-name` entries remain readable and protect both components as user-owned.
The extension and shell launcher share `identity-format.mjs` for naming-entry validation and spelling.
Both apply valid current and legacy entries in file order; CLI list/resume discovery therefore follows the same saved identity as extension startup rather than retaining historical names as aliases.
Startup naming (`pi-link <name>`, `pi --link-name <name>`) records manual ownership too.
Hub-assigned variants such as `builder-2` do not replace the saved preference.
On reconnect, a client requests the preferred name rather than its last runtime name.

**Rename guards:**

- A same-value manual assignment records ownership of its explicit fields before returning `"Already using..."`.
- On the hub, a manual rename rejects a name taken by another connected client; an agent identity update instead receives a unique suffix.
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

Delivery is held while a `manual`-reason compaction holds this terminal's gate, because a message delivered mid-compaction would be reasoned about against context that is being rebuilt. Two flags gate it: `compactRunning` for a compaction serving a remote `link_compact`, and `localCompacting`, set from `session_before_compact`; a remote request raises `compactRunning` first and adds `localCompacting` only if its compaction reaches that hook, since Pi reports its own reason as `manual` either way. Automatic (threshold/overflow) compaction is deliberately **not** gated: it runs inside the agent run, where Pi already queues steered messages and drains them afterwards. Because a gated flush does not reschedule, the release path is necessary: `releaseInbox()` runs after either flag clears and schedules a flush only when neither gate remains, and `compactDeadline` is the backstop for a `localCompacting` left raised, since failure emits no lifecycle ending event that clears it.

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
