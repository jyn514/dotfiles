# pi-link

This is a local fork of `alvivar/pi-link` 0.5.2 at commit `8dcec96c89c3816f6290a68a64c8f40545e0df4a`.
The upstream MIT license is retained in [LICENSE](LICENSE).
This fork adds protected agent-selected identities, group broadcasts, and private replies by delivered-message reference.
It retains asynchronous conversations without blocking asks or offline storage.
Root APIs integrate with the installed `pi-codex-subagents` manager/child bridge for active-worker delivery and private worker replies. Without that bridge, worker outcomes are explicitly unsupported.
It connects on startup by default.
The npm package `pi-link` still selects upstream, not this fork.
The link is localhost-only and has no authentication; do not expose port 9900 externally.

Run several Pi agents side by side and let them work as a team.
Once this fork is loaded, new sessions connect automatically and can send work or questions to other local Pi sessions.

One Pi is powerful. Several, talking to each other, unlock patterns a single terminal cannot:

- **Research + Build** — one terminal digs through APIs, docs or logs while another writes the code.
- **Parallel work** — split a large task ("you take the backend, you take the frontend") and collect the results.
- **Orchestrator / Workers** — one terminal delegates, tracks who reported back, and assembles the whole.
- **Review pipeline** — one writes, another reviews, back and forth until both are satisfied.

Questions, ideas? There's a [pi-link thread](https://discord.com/channels/1456806362351669492/1485515696719921183) in the official Pi Discord.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Walkthrough](#walkthrough)
- [LLM Tools](#llm-tools)
- [Slash Commands](#slash-commands)
- [CLI: `pi-link`](#cli-pi-link)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Design](#design)
- [Fork development](#fork-development)

---

## Prerequisites

- [Pi coding agent](https://github.com/badlogic/pi-mono), version **0.84.2 or later** (for pi-link 0.3+), stable releases only, reported as `x.y.z` without a prerelease or build suffix. On Pi 0.74–0.84.1, pin `pi-link@0.2.x`; on Pi ≤0.73, pin `pi-link@0.1.14`.
- Node.js (LTS recommended)

Pi's package installation does not check the host version, so `pi install` succeeds on an older Pi. pi-link then refuses to initialize instead of half-running: it throws before registering anything, and Pi reports it under **[Extension issues]** with the required minimum and the version it detected.

---

## Quick Start

### Install

The minimum install — enables every in-Pi feature (`/link`, `link_send`, `/link-connect`, `--link` flag, auto-resume, and all LLM tools):

From the dotfiles repository root, install this fork's locked dependencies and refresh configuration links:

```bash
npm ci --prefix tools/pi-link --ignore-scripts --no-audit --no-fund
./setup dotfiles
```

Setup links `~/.pi/agent/pi-link` to this directory.
The tracked Pi settings select `./pi-link` as a local package, loading both the extension and its skill on startup.
Run `/reload` in existing Pi sessions after refreshing the links.
For sandbox sessions, start a fresh sandbox once to expose the package's skill to guest tools.
Outside this dotfiles setup, register the local package with `pi install ./tools/pi-link` instead.

To try the extension without registering the package:

```bash
pi -e ./tools/pi-link/index.ts --link
```

Loading the file alone does not load the bundled skill.
Do not load it separately when the package is already configured.

#### Optional: shell launcher

If you also want the `pi-link <name>` shell command to start named sessions from a terminal prompt (e.g. `pi-link builder` in one window, `pi-link reviewer` in another), install the CLI globally as well:

```bash
npm install -g ./tools/pi-link
```

Install the local package with Pi before adding the optional shell launcher.
Running `npm i -g pi-link` instead installs upstream, without this fork's reply fields.

Registering a local package with Pi does not put its launcher on `PATH`.
The global npm install exposes the fork's `pi-link` command.

The shell launcher is convenience-only — you can always reach the same functionality from inside Pi via `/link-connect` and `/link-name <name>`.

### Uninstall

Remove `./pi-link` from `config/pi-agent/settings.json` to disable the tracked startup integration, then reload Pi.
For a separately registered local package, run `pi uninstall ./tools/pi-link` from the dotfiles root.
Run `npm uninstall -g pi-link` to remove the optional shell launcher.

### Usage

New sessions connect automatically when this fork is loaded.
To choose a name, use `--link-name` or the optional launcher:

```bash
pi                           # random name like t-a3f9
pi --link-name builder       # with a name of your choice
pi-link builder              # same, plus resume that session by name later (needs the shell launcher)
```

Use `/link-disconnect` to opt a session out; that choice survives reload and resume.
Use `/link-connect` to reconnect, or `/link` to check status.
See [Session Resume](#session-resume) for `pi-link <name>` details.

---

## Walkthrough

Here's a concrete example of two terminals collaborating. Open two terminals, each with its name already set:

```bash
pi --link-name builder       # Terminal 1
pi --link-name researcher    # Terminal 2
```

The first one to start becomes the hub; the second joins it. **In Terminal 1**, both names are now visible:

```
> /link
⚡ Link: builder (hub) · 2 online
  builder: idle (5s) · 45K/272K (17%)
    cwd: ~/my-project
  researcher: idle (12s) · 80K/272K (29%)
    cwd: ~/my-project
```

Already inside a session? Name it from the prompt instead — `/link-connect` if it is not on the link yet, then:

```
> /link-name researcher
✓ Reconnecting, requesting "researcher" (hub may assign a different name if taken)...
```

A client reconnects under its new name, so give it a moment before checking `/link`. Either way the name is saved with the session and comes back on resume.

**Now ask Terminal 1's LLM to delegate work:**

In Terminal 1, type a normal prompt:

```
> Use link_send to ask "researcher" to summarize README.md, then report DONE with the summary back to builder
```

Terminal 1 calls `link_send` and returns immediately. The message enters Terminal 2's reasoning — steered into its current run if it is working, or starting a turn if it is idle. Terminal 2 completes the assignment, then sends a conventional `DONE` callback. That callback enters Terminal 1 the same way, where the result can be presented or used for follow-up work.

### Once it works: groups

With two projects open, you may not want their terminals to see each other. Put a group after `@` in the name — `pi --link-name builder@frontend`, or `/link-name builder@frontend` from inside — and that terminal lists, messages and compacts only names ending in the same `@frontend`; a plain `builder` elsewhere no longer appears. The hub still serves everyone, and `pi-link --status` shows all groups. Full rule under [Configuration](#configuration).

---

## LLM Tools

Five tools cover identity, messaging, discovery, and remote compaction.
The bundled **pi-link-tools** skill supplies model action conventions; the reference below describes observable behavior.

### Which tool should I use?

| Tool | Behavior | Returns |
| --- | --- | --- |
| `link_set_identity` | Set this session's preferred name and/or group | Preference, origins, assigned name, connection state, and pending state |
| `link_send` | Send to one terminal or broadcast to the current group | Direct-send status, or a bounded broadcast routing receipt |
| `link_reply` | Reply privately to a delivered message's author | A bounded routing receipt for the resolved destination |
| `link_list` | List connected terminals in your group | Roles, Pi session IDs, status, cwd, and context |
| `link_compact` | Request remote compaction and wait for its result | Compacted, declined, or failed |

### `link_set_identity`

Set this session's preferred local link name, group, or both:

```typescript
link_set_identity({ name: "reviewer", group: "prose" });
link_set_identity({ group: "prose" }); // Keep the local name.
link_set_identity({ name: "reviewer" }); // Keep the group.
```

At least one field is required.
`name` must be nonempty after whitespace normalization and cannot contain `@`.
`group` is the text after the first `@`; `""` selects the ungrouped group, and further `@` characters are group text.
Omitted fields retain both their value and ownership.
This does not rename the Pi session or change its selected session file.

Name and group have independent origins: `generated`, `agent`, or `user`.
The tool can replace generated or agent-chosen fields, but a request that would replace either user-owned field fails atomically.
Supplying the same user-owned value is a no-op and leaves it protected.
User naming commands can replace agent choices and claim their explicitly assigned fields even when the text already matches.
Legacy saved names and Pi session-name fallbacks with unknown authorship remain protected.
Ownership survives reload and resume.
A user spelling such as `reviewer@` retains its explicit empty suffix.

A connected client may reconnect to apply the change.
Registration and agent hub renames may receive a collision suffix such as `reviewer-2@prose` without changing the saved preference or origins.
A colliding manual hub rename still fails.
Repeating an unchanged preference preserves its assigned collision suffix.
Explicit disconnect cancels a pending rename but retains the saved preference.
An offline update saves the preference without reconnecting.

Tool details contain `preferred`, `assignedName`, `connectionState`, and `pending`.
`preferred` contains `name`, `group`, `nameOrigin`, `groupOrigin`, and optional `explicitGroup`.
`assignedName` is `null` offline; `pending` means the requested client rename has not been assigned yet.
Do not treat a preference as an already connected name.
Agree on a group before moving: these tools cannot discover or contact sessions in another group.

### `link_send`

| Parameter | Type | Description |
| --- | --- | --- |
| `to` | `string` or exactly `{ broadcast: true }` | One terminal name, or the current group's connected roots |
| `message` | `string` | Message content |
| `replyTo` | optional `string` | Correlation only; does not select recipients or prove prior delivery |
| `includeSubagents` | optional `boolean` | Defaults to `false`; `true` is allowed only for broadcast |

#### Direct send

```typescript
link_send({ to: "reviewer@prose", message: "Check the condition." });
```

A string target sends to one other terminal and returns immediately.
A typo, an offline name, and a name outside your group all fail the same local target check.
Sending to yourself is rejected.
For a client, success means the message was handed to the hub connection, not that the hub routed it or the receiver saw it.
A later hub routing failure appears as a human notification, not a new result to the sending model.
Successful direct sends return a UUID as `messageId` in their text and details.

The optional `replyTo` field records a correlation without checking history or selecting the recipient.
Use [`link_reply`](#link_reply) to answer a received message by its delivered author rather than a remembered name.

#### Group broadcast

```typescript
link_send({
  to: { broadcast: true },
  message: "Assess directness, not voice. Stop tests based on the voice interpretation.",
  includeSubagents: true,
});
```

The hub selects connected roots in the sender's current group once, excluding the sending root.
A root is a connected Pi session, not one of its delegated workers.
All plain names share the empty group, so an ungrouped broadcast can interrupt unrelated sessions.
Agree on a named group before moving there or sending project-specific broadcasts.
There is no special string target: names such as `all` and `*` remain ordinary names.

All selected copies retain one UUID, sender attribution, content, optional `replyTo`, and a visible broadcast marker.
For broadcasts, an empty `replyTo` is treated as omitted.
Late joiners receive no replay, and later group changes do not retract accepted copies.
The call waits at most five seconds for routing outcomes, never for a model response.
Its details contain `messageId`, `operation` (`broadcast` or `reply`), `outcomes`, and `empty`.
`error` is present when at least one outcome exists and none is `submitted`.
Each outcome identifies its kind and destination, with `status` and an optional `reason`.
Model-visible result text includes the full message ID and each reported recipient's identity, status, and reason.
Statuses distinguish `submitted`, `failed`, `skipped`, `unsupported`, and `unknown`.
A partial result does not undo copies already submitted.
`submitted` means transport acceptance, not model admission, reading, or completion.
A lost receipt, disconnect, deadline, or cancellation after sending can leave an unknown outcome; do not automatically resend unknown copies.
Without a broadcast routing receipt, even the recipient selection can be unknown.
An empty selection is reported explicitly.

**Worker delivery requires the supported `pi-codex-subagents` manager/child bridge in each owning session.**
Children also need Pi's native fresh-input admission and pause APIs; missing capabilities report `unsupported`.
`includeSubagents: true` asks each manager for its active own workers, including the sender's workers.
The manager owns selection and lifecycle: finished or paused workers are not restarted or resumed.
Root delivery does not wait for the parent model to forward the correction.
Without a manager, that owner's worker outcome is `unsupported` with `worker_integration_unavailable`; root copies can still succeed.
The manager's child helper supplies `link_reply` for manager-delivered messages.
Workers also load configured extensions normally: if pi-link is enabled, it registers its ordinary tools and an independent connection.
Use template `disabledExtensions` to opt out of pi-link, or an explicit `tools` list to restrict the model's tools; worker status alone does not suppress the extension.
Private replies route by stable worker ID and owner session, never by task name.
Older hubs or peers without messaging v2 (which preserves worker reply attribution) remain explicitly unsupported for broadcast and `link_reply`.
Upgrade and restart linked terminals together.
See [active subagents](design.md#active-subagents) for the bridge boundary.

#### Incoming messages

Messages reaching a root enter its inbox.
Nearby arrivals are usually delivered as one `[Link: N message(s) received]` block, in arrival order.
Each message includes its sender and full ID; replies include `Reply to <original-message-id>`, and broadcasts are marked.
These fields appear in both model-visible text and the transcript panel.
Older direct-message peers may omit IDs or session attribution.
The batching window, caps, and compaction holds are described in [Inbox](design.md#inbox).

The receiver's state is read when the batch is delivered, not when it is sent.
A running receiver is steered at Pi's next safe boundary, after current tool calls finish and before the next LLM call.
An idle receiver starts a turn.
There is no send mode that bypasses the receiver's reasoning, and no automatic model response.

### `link_reply`

Reply privately to the author of a message actually delivered to this Pi session:

```typescript
link_reply({ replyTo: "<full-received-message-id>", message: "The condition needs a null check." });
```

Both `replyTo` and `message` are required; there is no `to`, broadcast, or worker-inclusion option.
The tool resolves the author from messages admitted to Pi's model input and recorded in this session's actual transcript.
An ID copied from elsewhere or an unknown reference fails without sending.
Queued messages do not grant reply permission before model admission, including messages cleared from the steering queue.
A message from an old peer without sufficient author attribution cannot establish a usable reference.

Root authors are identified by Pi session ID, not their mutable link names.
Renaming does not redirect a reply to someone who later takes the old name.
The author must still be connected and in the permitted group.
A broadcast reply goes only to its author, never its audience.
Replies have new IDs and can themselves be answered after delivery.
They use the same bounded routing receipt and structured details as broadcasts, not a model-response wait.
With the manager/child bridge installed, worker-authored questions retain worker attribution, and answers reach only that stable worker through its owner manager, not the parent model or siblings. Worker reply authority comes from actual child transcript admission, not a root inbox copy. Without the bridge, worker replies remain explicitly unsupported.

### `link_list`

Lists the connected terminals in your [group](#configuration), with role info, Pi session IDs, status, working directory, context usage, and self-identification.
Takes no parameters.
Full Pi session IDs appear in both the text and `details.sessionIds`, keyed by terminal name.
A known parent session ID can be matched to its terminal; the list does not infer parentage.
Older peers may not report an ID, so their map entries are omitted.
Your own status and context are read when you run `link_list`; peer values are their latest reported snapshots.

Each terminal reports its current working directory on connect. `link_list` shows the full absolute path.

Each terminal also reports its LLM context usage, rendered as `45K/272K (17%)` — tokens used over the context window, with percent. Briefly after compaction it shows as `?/272K` until the next measured context value is available.

Each terminal's status is derived automatically from Pi lifecycle events - agents can't set it manually. Four states:

| Status            | Meaning                                                                            |
| ----------------- | ---------------------------------------------------------------------------------- |
| `idle (2m)`       | Waiting for user input                                                             |
| `thinking (3s)`   | Work Pi has not settled yet — the LLM call, plus any automatic retry or compaction |
| `tool:bash (12s)` | The first still-active call, not a list                                            |
| `compacting (8s)` | Manual compaction gate raised; messages held                                       |

Pi can run tools in parallel, so `tool:<name>` names the first still-active call Pi reported — one call that really is still running, not a list of every concurrent one — and it advances only when that call ends, staying `tool:<name>` until the last one does.

Only a manual compaction shows `compacting`; while it does, messages to that terminal are held — see [Inbox](design.md#inbox).

Durations are computed at render time from a `since` timestamp - no timer traffic over the wire. Terminals that just joined with no status data yet render as blank, not fake idle.

Working directories use full absolute paths in tool output. In the TUI (`/link`), paths are shortened to `~/...` when possible to keep the display compact.

**Example output:**

```
Connected terminals:
  • builder (you)  idle (12s)  · 45K/272K (17%)
    cwd: /home/me/my-project
  • researcher  thinking (3s)  · ?/272K
    cwd: /home/me/my-project
  • reviewer  idle (1m)  · 90K/272K (33%)
    cwd: /home/me/my-project
```

### `link_compact`

Ask another terminal to compact its context window and wait up to 300 seconds for a result. The target may compact successfully, decline, or return an error. After a successful result, the next call can dispatch work to the freshly trimmed worker.

| Parameter      | Type     | Description                                            |
| -------------- | -------- | ------------------------------------------------------ |
| `to`           | `string` | Target terminal name                                   |
| `instructions` | `string` | Optional custom compaction instructions for the target |

- **Success** result: `Compacted "<name>"`.
- **Busy decline** — the target accepts only when Pi reports its session idle **and** no manual compaction holds its delivery gate, so an active run, an automatic retry, an automatic compaction and a queued continuation all decline immediately with `reason: "busy"` without interrupting the work in progress.
- **The other declines** — a runtime offering no compaction capability declines with `reason: "unsupported"` and is never asked to compact; a session under the runtime's threshold declines with `Compact on "<target>" not done: Nothing to compact (session too small)`; a target that has done nothing since its last compaction declines with `Compact on "<target>" not done: Already compacted`.
- **Self-target rejection** — calling `link_compact` on yourself returns a `self_target` error (`Cannot compact yourself.`).
- **Flat 300-second timeout** — the timeout bounds the caller's wait only; nothing aborts the target, so a timed-out call may mean the compaction is still running.
- Any terminal can request compaction on another **in its group**.

The mechanics behind these outcomes — what an accepted request runs, the delivery gate it raises, what releases that gate after a cancellation, and what aborting the caller does — are in [Remote compaction](design.md#remote-compaction).

---

## Slash Commands

| Command             | Purpose                                                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `/link`             | Show link status (name, role, online count, agent status, context usage, and cwd per terminal)                           |
| `/link-name [name]` | Rename and save as this session's preferred link name. With no argument, adopts the Pi session name. Restored on resume. A name with `@` also sets your group. |
| `/link-connect`     | Connect to Pi Link (works anytime, with or without `--link`)                                                             |
| `/link-disconnect`  | Disconnect from Pi Link and suppress auto-reconnect (overrides `--link`)                                                 |

### Examples

```
> /link
⚡ Link: builder (hub) · 3 online
  builder: idle (12s) · 45K/272K (17%)
    cwd: ~/my-project
  worker-1: thinking (3s) · ?/272K
    cwd: ~/my-project
  worker-2: tool:bash (5s) · 180K/272K (66%)
    cwd: ~/other-project

> /link-name orchestrator
✓ Renamed to "orchestrator"

> /link-name
✓ Renamed to "my-session"

> /link-disconnect
✓ Disconnected from link

> /link-connect
✓ Joined link as "orchestrator" (3 online)
```

With no argument, `/link-name` adopts the Pi session name. `/link-connect` joins an existing hub if one is running; otherwise it starts the hub.

**Name persistence:** `/link-name` saves your preferred name to the session. Resume later and it's restored automatically. If the name is taken, the hub assigns a variant (e.g., `"builder-2"`), but your preferred name stays saved for the next reconnect. See [Name Uniqueness & Persistence](design.md#name-uniqueness--persistence) for details.

See [Configuration](#configuration) for details on `--link`, `/link-connect`, and `/link-disconnect` behavior.

---

## CLI: `pi-link`

`pi-link` is the optional shell launcher installed with `npm install -g ./tools/pi-link` from the dotfiles root.
It resolves sessions by name, lists them, and asks the running hub who is connected.

### Session Resume

Pi's `--session` flag requires a file path, not a display name. `pi-link` bridges this — it resolves a session by name and launches Pi directly:

```bash
pi-link worker-1                # resume or create session "worker-1"
pi-link worker-1 --model sonnet # with extra Pi flags
```

How it works: `pi-link worker-1` scans Pi's session directory, finds the session named "worker-1", and spawns `pi --session <path> --link`. Session-dir resolution matches Pi's lookup order: `PI_CODING_AGENT_SESSION_DIR` env > `<cwd>/.pi/settings.json` `sessionDir` > `<agentDir>/settings.json` `sessionDir` > default `<agentDir>/sessions/`. `<agentDir>` follows `PI_CODING_AGENT_DIR` and defaults to `~/.pi/agent/`.

Lookup is **scoped to the current cwd by default**; pass `--global` (`-g`) to consider sessions in any cwd. A scoped lookup stops reading a session file as soon as its header names another cwd, so it never learns the names of sessions belonging to other directories, and its cost tracks this cwd's own history rather than the history of unrelated projects.

- **One match in scope** → resumes that session
- **No match in scope** → creates a new session in the current cwd, and advises `--global` without claiming a session exists elsewhere.
- **Multiple matches in scope** → prints candidates to stderr, exits 1
- **Conflicting flags** (`--session`, `--continue`, `--resume`, `--fork`, etc.) → rejected with an error

### Discovering sessions

`pi-link --list` shows pi-link sessions in the current cwd; `pi-link --list --global` (or `-g`) lists them across all directories. Sorted by last activity — starting a session with the same name it already has does not bump recency; only real activity (messages, tool calls, edits, name changes) does.

```
$ pi-link --list
NAME             MODIFIED  MESSAGES  ID
builder          2m ago    4632      6332faab
researcher       5m ago    1493      20d43841

Resume: pi-link <name>
```

With `--global`:

```
$ pi-link --list --global
NAME             CWD                   MODIFIED  MESSAGES  ID
builder          ~/my-project          2m ago    4632      6332faab
researcher       ~/other-project       5m ago    1493      20d43841

Resume: pi-link <name>
```

`--global` adds a `CWD` column with `~` substituted for `$HOME`. Output is plain when piped (`NO_COLOR` honored).

`pi-link <name>` and `pi-link --resolve <name>` follow the same scoping: local cwd by default, `--global` (or `-g`) widens. A local miss never silently jumps cwds: it says the name was not found here and suggests `--global`. Because a local scan skips sessions from other cwds without reading them, that suggestion is advice rather than a report that a match exists elsewhere - run it with `--global` to find out.

For scripting, `pi-link --resolve <name>` prints just the session path (machine-readable, no other output). Exit codes: `0` on single match, `1` if ambiguous (multiple matches printed to stderr), `2` if not found.

### `--status`: who is connected right now

`--list` and `--status` answer different questions. `--list` reads session files on disk and answers *which sessions exist in history on this machine* — a session that died days ago still appears. `--status` asks the running hub and answers *who is connected to the link at this instant* — it is held in the hub's memory, so it needs a live hub and reports nothing about sessions that are merely saved.

```
$ pi-link --status
NAME        STATUS               CONTEXT          CWD
builder     idle (7m)            92K/272K (34%)   ~/my-project
researcher  tool:link_send (3s)  ?/272K           ~/my-project
reviewer    compacting (12s)     1.3M/2.0M (63%)  ~/other-project
worker-1    ?                    ?                ?
```

The hub is listed first, then clients sorted by name. A `?` means the hub could not report that field — for `worker-1` above, it has registered but has not yet sent its first status update. **`?` means unknown, not idle.** Reading it as idle is the mistake this command exists to prevent.

The word for what this proves is **connected**, not alive: it shows terminals registered with the hub that answered. A terminal whose process is wedged still holds its connection, so `--status` never claims a terminal is healthy — only that it is on the link.

Querying is read-only. It does not register a terminal, does not appear in anyone's `link_list`, and broadcasts nothing to the fleet.

#### Scripting

`--status --json` writes the hub's response body to stdout unchanged once it passes the same checks the table uses, and the endpoint is plain HTTP, so `curl` works too:

```bash
pi-link --status --json
curl 127.0.0.1:9900/status
```

Two of the terminals above, as the hub reports them:

```json
{
  "hub": "builder",
  "port": 9900,
  "terminals": [
    {
      "name": "builder",
      "role": "hub",
      "status": "idle",
      "sinceSeconds": 420,
      "cwd": "/home/me/my-project",
      "context": { "tokens": 92000, "window": 272000 }
    },
    {
      "name": "worker-1",
      "role": "client",
      "context": null
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `hub` | Name of the hub that answered; always equal to `terminals[0].name` |
| `port` | Port the hub is bound to |
| `terminals` | Hub first, then clients sorted by name — never empty |
| `terminals[].name` | Terminal name as the hub knows it |
| `terminals[].role` | `hub` for the first entry, `client` for the rest |
| `terminals[].status` | `idle`, `thinking`, `compacting`, or `tool:<name>` |
| `terminals[].sinceSeconds` | Whole seconds in that status, rounded — relative, so no clock agreement is needed |
| `terminals[].cwd` | Working directory; **omitted** when the hub does not know it |
| `terminals[].context` | **Always present**: `null` when there is no snapshot, otherwise `{ tokens, window }` |

**`status` and `sinceSeconds` are one optional pair — both present or both absent.** They are absent for a terminal the hub has registered but not yet heard from. Absence means unknown; do not substitute a default.

**`context` uses `null`, not omission.** The field is always there; `null` means no snapshot exists, and `{ "tokens": null, "window": 272000 }` means a snapshot exists but the token count is mid-refresh (rendered `?/272K`).

Two things may grow, and consumers must tolerate both:

- **Unknown fields.** Documented fields are frozen; new ones may be added, so ignore what you do not recognize rather than rejecting the payload.
- **Unknown `status` values.** The vocabulary is not frozen — it has grown before, gaining `compacting` in 0.3.0. Treat any non-empty string as possible; the CLI renders an unrecognized value as-is instead of refusing the response.

Everything above is what the hub sends. The CLI validates only the fields its table prints — `terminals` as an array of objects with a string `name`, an optional string `cwd`, `context` as `null` or `{ tokens, window }`, and `status`/`sinceSeconds` together or absent. A body failing that exits 1 with the unsupported message instead of a stack trace, **in both modes**. A zero exit certifies nothing beyond printability — not hub-first order, not `terminals[0].name === hub`, not a numeric `port`, not even that a hub answered; verify what you depend on yourself. Once the body passes, `--json` writes it as received, unreformatted.

#### Exit codes

| Code | Meaning | Message |
| --- | --- | --- |
| `0` | Something answered with a printable payload | — |
| `2` | No hub answered | `No link hub running on :9900.` |
| `1` | Usage error, or an answer the table cannot print | `Link hub does not support /status — update pi-link and restart terminals.` |

The two failure messages are deliberately distinct, so a script can tell *no usable answer* from *an answer this CLI cannot read* without parsing anything else. Exit `2` covers both nothing listening and a listener that accepts the request but does not answer within two seconds — every timeout is exit `2`. Exit `1` covers a listener that responds with something the table cannot read — for example a pi-link 0.3.0 hub, which answers plain HTTP with `426 Upgrade Required`, so an out-of-date fleet lands here deterministically rather than looking like an outage.

Exit `2` means no hub answered **at that instant**. When a hub exits, a surviving client promotes itself to replace it, which takes roughly 2–5 seconds — poll again before concluding the fleet is down.

#### Notes

`PI_LINK_PORT` changes only where the CLI looks; the extension always binds the hub to `9900`. The value is not validated — an unusable one simply fails the request and is reported back to you in the exit-`2` message.

The endpoint is bound to `127.0.0.1` with no authentication, the same trust boundary as the WebSocket surface it shares a port with: any process on this machine can already connect to the link.

Finally, `--status` and `--json` belong to the wrapper only until a session name appears. After one, they are pi's: `pi-link mybot --status` forwards `--status` to pi untouched, exactly like any other passthrough flag.

---

## Configuration

This fork connects new sessions by default.
A saved `/link-disconnect` takes precedence over the default; `/link-connect` or an explicit startup name reconnects that session.
Agents can see their own tool results and incoming message panels; the user can see both in the transcript.
The bundled skill tells agents not to repeat those messages in their ordinary replies.

**Naming concepts**

- **link name** — identity used on the network (visible in `link_list`, `/link`, and messages).
- **group** — the text after the first `@` in a link name, compared exactly.
  `archon@pi-link` is in `pi-link`, and `a@g@h` is in `g@h`.
  A name without `@`, or ending in one such as `a@`, belongs to the single implicit group of plain names.
  Comparison is **case-sensitive**: `a@Team` and `a@team` are different groups.
  `link_list`, `link_send`, `link_reply`, `link_compact`, `/link` and the footer see or reach only your own group.
  The hub still routes for every group, and `pi-link --status` shows all of them.
  Renaming with `/link-name` or an accepted `link_set_identity` group change moves you.
- **Pi session name** — identity Pi gives the session itself; lives in the session JSONL's latest `session_info` entry.
- **saved link name** — the link name persisted to the session, restored on resume. Set by `/link-name`, `pi-link <name>`, `pi --link-name <name>`, or `link_set_identity`.
- **`--link-name` flag vs `/link-name` command** — same concept (the link name) at different times (startup vs mid-session).

| What you want                        | Use                     |
| ------------------------------------ | ----------------------- |
| Resume/create a named session        | `pi-link <name>`        |
| Stable link identity, normal Pi flow | `pi --link-name <name>` |
| Quick try, random name               | `pi --link`             |
| Already in a session                 | `/link-connect`         |
| Disconnect mid-session               | `/link-disconnect`      |

`pi-link <name>` resumes/creates a session AND sets your link identity in one step. `pi --link-name <name>` sets only the link identity, leaving Pi's normal session selection (latest in cwd, or fresh) untouched.

**Name normalization:** Link names are normalized — leading/trailing whitespace removed and internal whitespace runs collapsed to a single space. `/link-name "build   lead"` saves and shows as `build lead`.

**Name precedence:** `pi --link-name` > `pi-link <name>` > saved `/link-name` > Pi session name > random `t-xxxx`. _(The `pi-link` wrapper itself does not accept `--link-name`; pick one or the other.)_

`/link-connect` and `/link-disconnect` save their intent to the session — resume later and the connection state is restored without needing the flag. Explicit user intent takes precedence over `--link`.

---

## Troubleshooting

### Port 9900 is already in use

If another process occupies port 9900, the terminal can't become the hub. It tries to connect as a client first, and that attempt fails within 5 seconds even against a listener that accepts the connection and never speaks WebSocket - so the terminal falls back to trying the hub role and then retries after 2-5 seconds, rather than sitting offline indefinitely. Free the port or modify `DEFAULT_PORT` in `index.ts` - see [Limitations](design.md#limitations--design-decisions).

### `link_compact` reports a busy target

A `link_compact` request does not interrupt work the target is still doing, so it declines while that terminal is unsettled — see [`link_compact`](#link_compact) for the full list of what counts. Try again once `/link` or `link_list` reports the target idle, keeping in mind that idle is what was true a moment ago, not a reservation: the target can start working again before your request lands. `link_send` is different — it enters or steers the target's reasoning instead of declining just because it is busy.

### I sent a message but got no reply

A successful send is not a confirmation, and a message ID does not establish delivery.
For a direct send from a client, success means the message was handed to the hub connection.
For broadcasts and `link_reply`, inspect the routing receipt: even `submitted` does not mean a model read or acted on the message.
Replies are ordinary messages the other agent chooses to send, so nothing produces one automatically.
Run `/link`, or ask your model to call `link_list`, and check the target: confirm the name is still exactly right.
A target in the `compacting` state holds messages that reach it until that state clears.
Otherwise silence may mean the work is still running or that no reply was sent.
If the target cancelled a `/compact`, pi-link cannot see that, so its messages may stay held until its next run or up to five minutes.
See [Remote compaction](design.md#remote-compaction).

### `pi-link --status` reports no hub, or an unsupported one

The two messages mean different things. `No link hub running on :9900.` (exit `2`) means nothing answered — either the link is genuinely down, or you caught it during the 2–5 second window while a client promotes itself to hub, so poll again before believing it. `Link hub does not support /status — update pi-link and restart terminals.` (exit `1`) means something answered but the response did not pass the CLI's checks — for example, a pi-link 0.3.0 hub, which predates the endpoint. Updating is not enough on its own: the running terminals keep the old hub alive until they restart. See [`--status`: who is connected right now](#--status-who-is-connected-right-now).

### Terminals don't see each other

- Compare the part after `@`, exactly as spelled: `archon@pi-link` and `builder` are in different [groups](#configuration), and so are `a@Team` and `a@team`; they are invisible to each other by design. `pi-link --status` shows every group and settles it.
- Verify both terminals are on the same machine (the link only works on `127.0.0.1`).
- Run `/link` in each terminal to check status.
- Ensure port 9900 isn't blocked or occupied by a non-link process.

### Hub promotion loses state

When the hub exits, a surviving client promotes itself in roughly 2–5 seconds; messages in flight during that gap can be lost, and a terminal that reconnects as a client after running as a hub-assigned variant like `builder-2` may come back under its preferred name, or vice versa. This is by design — see [Hub Promotion](design.md#hub-promotion) for how promotion works and [Limitations](design.md#limitations--design-decisions) for the decision behind it.

---

## Design

The [design document](design.md) covers architecture, protocol, implementation constraints, and design decisions.
Usage and recovery instructions remain in this README.

---

## Fork development

First follow the repository's [test dependency setup](../../dev/README.md#testing-and-probes).
From the dotfiles repository root:

```bash
dev/test-environment bun test tests/pi/pi_link_test.ts
```

The suite is also discovered by the repository's `dev/test` command through `bun test tests/pi`.
Tests use disposable copies and private WebSocket ports, not the live link on port 9900.
Keep fork changes here rather than editing a Pi-installed package checkout.
Bootstrap configuration and the installed upstream package are unchanged.
