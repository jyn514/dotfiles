# Pi extension bundle

`index.ts` is loaded by the existing `config/pi-agent/settings.json` settings as
`./pi-extensions/index.ts`, relative to the installed agent directory. Keep the
whole directory available because the entry point imports sibling modules. This
installation needs no separate `ask-user.ts` setting or package install. After
updating the bundle, run `/reload` in Pi. To test a checkout temporarily:

```sh
pi -e ./config/pi-agent/pi-extensions/index.ts
```

Do not load `ask-user.ts` independently alongside the bundle.

`openrouter-output-cap.ts` limits OpenRouter chat requests to 10,000 output tokens.
Start Pi with `--openrouter-max-tokens 6000` to choose another cap (minimum 2048).
An invalid cap reports an extension error but leaves the request uncapped by this extension because [request-hook failures do not abort requests](../README.md#request-hook-failures).
Restart with a valid flag value or omit the flag to restore the default cap.
Smaller existing limits remain unchanged; model capability metadata and other providers remain unchanged.
The cap includes reasoning on providers that count reasoning against output.
Explicit thinking budgets are lowered when needed to leave Pi's 1024-token answer allowance; adaptive thinking and effort settings are preserved.
Requests without an output-limit field are unchanged.
This reduces maximum request cost but does not guarantee sufficient credit for the prompt and output.
Run `/reload` to load the extension in an existing session.

`pi-notify.ts` sends an OSC 777 desktop notification when an interactive run settles.
Inside tmux, it also sends a standalone bell so tmux can mark background windows with a bell alert.
The desktop notification uses DCS passthrough and requires `set -g allow-passthrough on` (already in this repository's tmux config).
With `on`, tmux forwards desktop notifications only from visible panes; `all` also permits hidden panes.
The outer terminal must support OSC 777 for desktop notifications; tmux's bell alert does not require that support.
Run `/reload` after changing the extension, then finish a turn to test delivery in the host terminal.

The footer adapts Pi's `custom-footer.ts` example. Its second line shows context
percentage/capacity and cumulative price, with model and thinking level on the
right. It omits `(auto)`, `(sub)`, and token/cache statistics. Context turns yellow
above 70% and red above 90%; unknown usage shows `?`. The provider appears when
multiple providers are available and space permits. Directory, branch, session
title, and extension statuses remain visible. Run `/reload` to activate it.

Transport tracing is disabled by default. Start `PI_TRANSPORT_DIAGNOSTICS=1 pi`
to enable `transport-diagnostics.ts`, which records Codex Responses HTTP attempt
summaries in `~/.pi/agent/logs/transport-<pid>.jsonl`. Start Pi without the variable
to disable it. Existing ordinary sessions stop tracing after `/reload`;
sessions launched with the opt-in variable need a new process without it.
Disabling tracing preserves existing log files. Successful and failed
attempts are logged, with private directory/file permissions. Each record includes the Pi
session ID, destination origin/path, elapsed time, response status and header
timing when available, `x-request-id`, `cf-ray`, error codes, and available socket addresses
and byte counters. Request bodies, authorization headers, URL credentials/query
strings, and free-form error messages/stacks are omitted.

`requestHeaders` records allowlisted headers at Undici's send boundary;
`responseHeaders` records the same allowlist from received headers. It includes
`user-agent`, `originator`, `openai-beta`, `accept`, `content-type`, `content-length`,
`x-client-request-id`, `x-request-id`, `cf-ray`, `server`, and `date`.
Authorization, cookies, account IDs, and all other headers are excluded.
Parsed events use Pi's `onProviderStreamEvent` callback; reload after updating Pi
or this extension before relying on response-ID and terminal-event correlation.

For a sustained IPv4 comparison, start a new host Pi with `PI_HTTP_FAMILY=4 pi`
and use the same model, SSE transport, and normal workload as the baseline.
This explicit experiment also enables tracing.
The diagnostics extension supplies Pi's installed Undici fetch with IPv4 DNS
connections and automatic family fallback disabled for Codex HTTP/SSE requests.
It uses five-minute header/body timeouts; use the default five-minute baseline
for this comparison. Authentication and WebSocket requests use their normal
connectors. It does not change OS networking or existing Pi processes.
Confirm model attempts report `addressFamily: 4` in the transport log before
counting results. Compare failures per attempt over several hours; a short clean
run is inconclusive. Start Pi without the variable to return to the default.

`lastChunkAgoMs` measures milliseconds from the last received HTTP body chunk to
attempt completion or failure, using a monotonic clock. It is `null` when no chunk was observed.
Chunks are transport chunks, not parsed SSE events; their contents are not logged.
Records also include first-chunk timing, maximum gap between received chunks,
chunk count, and per-request received body bytes. Socket byte counters are cumulative
and may include other requests. `socketId` and `observedRequestsOnSocket` identify
reuse observed since the extension loaded; a count of one does not prove a fresh
connection. `addressFamily` is 4 or 6 for an observed IP peer.

The resolved Codex provider is decorated to correlate its authoritative parsed
events and cancellation signal with each HTTP attempt. Auth, catalog, options,
callbacks, and the returned stream are preserved. Summaries are written after
the provider call completes, with model/provider, last event type, terminal event
type, response ID, `callStopReason`, and `signalAborted`. `callStopReason` describes
the entire provider call, including any retries. `operationId` groups that call's
attempts; `attempt` gives their order. `transportOutcome` separates
`http_complete`, `reader_cleanup` after a terminal SSE event, and `error`.
Raw requests outside this decorated provider have no parsed-event or signal context.
Wall-clock start/end timestamps, process/session IDs, and attempt IDs support
cross-agent comparisons; elapsed times use a monotonic clock.

This observes Node's Undici diagnostic channels without changing parsing or
retries. It covers HTTP/SSE, not WebSocket requests or transports that do not use
Undici. A peer address identifies the connected endpoint, not why it closed.
Files are not automatically rotated; remove old logs when no longer needed.
If writing fails, logging stops for that extension instance and reports the log
path once on stderr. Shutdown and `/reload` unsubscribe and flush pending writes.
The decorated provider is restored on shutdown so reload cannot stack wrappers.

`/transport-probe` resolves `chatgpt.com` and tests TCP/TLS connections to the first
resolved address of each family. It shows and saves a `network_probe` record with
DNS, TCP, and total timing, typed errors, and outcome. Each connection has a
10-second deadline; DNS uses the system resolver. No HTTP request, credentials,
or model call is sent. Run it on the affected host near a failure: a successful
handshake does not establish that a long Responses stream will survive, and this
direct probe does not test a custom proxy path.

Active requests also measure event-loop scheduling delay at 20ms intervals.
Each attempt's `eventLoop` summary includes maximum delay, maximum delay since
its last body chunk, count/total delay for stalls of at least 100ms, and Node's
event-loop utilization delta. These are process-wide measurements over the
request's lifetime, not CPU time attributable to that request. An overdue sample
is checked at chunk arrival and attempt completion too. Timers stop when idle.

`socket_event` records observe Node's `end`, `error`, and `close` events, keyed by
`socketId`; close includes `hadError`, and errors include typed codes.
`end` indicates readable EOF at the Node socket boundary; it does not prove a
wire-level FIN or identify who initiated closure. No data listener is attached.

On Linux, `ss -tinHO` samples active connection tuples once per second.
`tcp_sample` records include socket/attempt/session IDs, sampling start/end time,
TCP state, send/receive queues, and available numeric TCP_INFO counters.
`rtt` is `[RTT, variance]` in milliseconds; `retrans` is `[current, total]`;
`bytes_retrans` is a cumulative socket counter. Missing fields remain absent.
Samples can miss changes between polls and sockets that close before a poll.
They do not capture packet flags or packet-by-packet retransmission timing.
Only matching tracked connection tuples are logged; raw command output is discarded.
`ss` must be installed and able to read the host's network namespace. A failed
sample logs `tcp_sampling_status` once and disables TCP polling until `/reload`.
Other platforms still get socket events and event-loop measurements.

Run the native Node regression (Bun uses a different fetch transport):

```sh
dev/test-environment node --test tests/pi/native_transport_diagnostics.mjs
```

The bundle adds the current date and Pi's host OS to the system prompt. On Linux,
the OS name comes from `/etc/os-release`, or `/usr/lib/os-release` when the former
cannot be read. Without a display name, and on other platforms, it uses the OS
and kernel release. This describes the host running Pi, not its guest shell tools;
send a prompt, then use `/system-prompt` to inspect the captured prompt.

The bundle requires a Pi build with the mutable `systemPromptOptions.sections` API.

Prompt additions use named sections: `current_date`, `host_os`,
`instruction_includes`, and `web_search`. Each extension owns its section;
web-search guidance disappears
when the active provider does not support it. Pi patches changed sections on
later turns unless another extension forces a full-prompt replacement.
`guest-tools.ts` remains an explicit exception: it rewrites paths in the rendered
prompt, including Pi's generated docs section, then replaces the full prompt.
Section-only updates do not apply while that guest-routing hook is active.

Web search uses stock request-payload and provider-event hooks, not the fork's
`registerProviderTool()` API. It adds native search to Anthropic Messages,
OpenAI/Azure/Codex Responses, and Google/Vertex requests without replacing local
tool declarations. OpenAI search uses medium context; search options supplied by
an earlier payload handler remain unchanged. On OpenAI/Azure/Codex Responses,
finalized URL annotations convert provider citation markers into ordinary Markdown
links on the same stored assistant message. Conversion requires an unambiguous
match between the final provider text, its annotation positions, and Pi's text
block; missing, invalid, or ambiguous annotations leave the text unchanged.
Other sources are appended in a `Sources:` list without repeating URLs already
in the answer. Streaming text can still show raw markers until the message ends.

On OpenAI/Azure/Codex Responses, a live widget above the editor shows provider-reported web activity.
Operations appear muted while running, green when completed, and red when failed or incomplete.
Status-only events show “Web operation: details not reported” until the provider supplies the action, query, or URL.
The widget clears when the assistant message finishes or the run ends.
Visible `web-activity` custom messages preserve the final queries, URLs, find patterns, and observed operation statuses in the transcript and model context.
They do not start another model turn; Pi inserts them after the current turn's tool results.
Repeated notifications for one call produce one record; separate calls to the same URL remain separate.
These records survive session reload and are included in later model requests without retaining page contents.
`completed` means the provider reported completion, not that the model read the whole page or interpreted it correctly.
Failed and incomplete operations remain recorded even without citations; unfinished operations keep their observed status.
An absent activity record does not prove that no retrieval happened.
Other providers retain their existing citation behavior without inferred activity records.

Run `/reload` to activate this in existing Pi processes; saved old messages are
not rewritten. Both the installed SDK's `provider_event` and v0.99's
`provider_stream_event` are supported.
The selected model must identify a supported API; virtual selectors that hide the
routed provider's API receive neither search injection nor search guidance.

`task-directed-docs.ts` replaces Pi's blanket complete-file reading rules in the
`docs` section. Read relevant sections, check shipped examples for a reusable
starting point, and follow references that define a needed API or constraint.
Read whole files only when the task needs whole-file understanding.
Pi still supplies documentation paths and topic routes. The hook runs before guest
routing and leaves missing docs sections or unrecognized policies unchanged. Its
native regression checks Pi's rendered format and rule wording when Pi is updated.

Tool descriptions and parameter schemas retain input and lifecycle contracts.
Prompt guidelines add workflow rules rather than repeat those contracts. Parameter
defaults do not replace observation sequencing or user-authorization requirements.

## Prompt inspection

`Ctrl+R` or `/history-search` opens previous prompts from the current branch and saved sessions.
Search matches all whitespace-separated terms, ignoring case, anywhere in the prompt.
Pi's `SelectList` displays results and handles arrow navigation; `Ctrl+R` selects the next result.
Enter restores the original prompt text, including line breaks, and Escape leaves the editor unchanged.
Saved history loads in the background without changing the selected prompt.
Run `/reload` after updating the picker extension.

`/system-prompt` shows the last prepared Pi system prompt, with the selected model
and capture time. Both this viewer and `/context-breakdown` retain a shared snapshot
from `before_provider_request`; Pi's idle getter otherwise loses per-run changes.
The snapshot includes expanded instructions and guest path rewriting. It is not the
final serialized request: context-message and provider-payload rewrites are excluded.

Session start, resume, fork, and `/reload` clear the snapshot. Until the next provider
request, both commands report that no prompt has been captured instead of showing
an untransformed base prompt. Captures are in memory only and never persisted.

`/context-breakdown` estimates the captured prompt alongside the current persisted
conversation and active tool schemas. Its source labels use current base prompt
inputs; extension additions appear in the remainder rather than as separate rows.
These are local estimates, not provider token accounting.

## Session titles

`session-title.ts` adds the saved title to successful `read_session` transcript results.
The reader should return the resolved absolute path in `details.sessionFile`, including for ID-only reads.
The hook prefers that path and falls back to the input's `sessionFile` for older reader versions.
It does not resolve session IDs itself or pick a file from a version list.
Pi files use Pi's session API.
Codex files use the header's thread ID to read `threads.name` from `$CODEX_HOME/state_5.sqlite`, defaulting to `~/.codex/state_5.sqlite`.
The database opens read-only with a 100ms lock timeout; it is never created, migrated, or updated.
This depends on Codex's private schema, not a stable public API.
Custom SQLite storage outside `CODEX_HOME` is not discovered.

An empty or null name is a valid unnamed session.
A missing thread row quietly leaves the result unchanged: absent metadata does not establish that a session is untitled.
An unreadable database, changed schema, invalid title value, or malformed header produces a UI warning
and a model-visible warning with `details.sessionTitleWarning`; the transcript and its details remain available.
Failures are not labeled `(untitled)`.
ID-only reads without a resolved path and version lists remain unchanged.
Format detection reads only the first JSONL header, with a 5 MiB limit.
Run `/reload` in Pi to load this hook change.

`set_current_session_title` and `edit_session_title` still change Pi titles only.
Test title enrichment with the installed Pi and real SQLite fixtures:

```sh
dev/test-environment node --test tests/pi/native_session_title.mjs
```

For the real reader-plus-title-hook check, set `PI_SESSION_SEARCH_PACKAGE_DIR` to an installed session-search package or checkout:

```sh
PI_SESSION_SEARCH_PACKAGE_DIR=/path/to/pi-session-search \
  dev/test-environment node --test tests/pi/native_session_reader_title.mjs
```

This loads both extensions through Pi and feeds actual reader results into the title hook, using disposable recordings and SQLite fixtures.
Cases cover named, unnamed, and missing-title ID reads, version lists, and selected-child titles in inherited context.
`dev/test` includes this check when the variable is set; otherwise it reports the integration test as skipped.
It never fetches the reader package or assumes a neighboring checkout.

## Subscription usage: `/usage`

`/usage` fetches your ChatGPT account limits, credit balance, and additional limits
such as Luna Reserve. Bars show the percentage **left**, with reset times in the
host's local time zone. Missing limits or balances are not treated as zero.

Use Pi's `/login` with OpenAI Codex first. The command uses Pi's resolved provider
credentials and token refresh; it does not read Codex CLI credentials. It requires
the direct ChatGPT provider, not a custom authentication proxy. This is account-wide
subscription usage, unlike the session token counts in `/session`.

The command fetches only when invoked, makes no model request, and stores nothing
in the session or on disk. It is interactive-only. It uses the same account-usage
endpoint as Codex CLI; this is an undocumented backend API and can change.
On the host, run `./setup dotfiles` from the repository root to link the new module.
Then run `/reload` in Pi, followed by `/usage`.

## Skill validation: `validate_skill`

Call `validate_skill({ "path": "skills/example/SKILL.md" })` to check whether
Pi's own loader accepts a skill file. Paths are relative to the current working
directory or absolute; `~/` paths also work. The result contains `loaded`, `name`
when accepted, and Pi's `diagnostics`. Warnings do not necessarily prevent loading.

This checks only the supplied path, not whether the current session discovers or
uses the skill. It does not reload or change the session.

In a sandbox, validation runs through the attached guest worker's Pi loader.
Absolute paths, `~/` paths, symlinks, and diagnostics use the guest filesystem;
relative paths use the worker's working directory. Outside a sandbox, validation
uses the local Pi loader and session working directory. Guest attachment or
transport failures return tool errors, never host validation results.

Updating guest validation requires a new worker. Close existing sandbox panes
and start a new sandbox to deploy the host extension and worker together;
`/reload` alone cannot replace the worker.

## Commit-boundary warning

The selected `commit-boundary.ts` design records one working-copy boundary after an editing response fully settles, including automatic continuation.
The harness takes an ordinary wrapped Jujutsu snapshot and saves immutable `@` as a JSON string, for example `"0123..."`, in the ignored, working-copy-local `target/jj-split/commit-boundary.json`.
The record must never enter a Jujutsu snapshot.
Guarded native and guest writes, including root and fresh workers with the integration loaded, use that same record; no manager handoff or per-session memory owns it.
Reloads, session changes, and worker or manager exits do not clear it. Read-only responses do not replace it.

Before a later supported structured `edit` or `write`, the harness asks the existing read-only `agent-split --check-file` operation whether the recorded changes in that file remain separately selectable.
`preserved` permits the write and keeps the record.
`would-lose` leaves the target unchanged, returns a warning with the path, and forgets the checked boundary.
The warning does not expose the splitter's concrete rejection reason; that reason remains in the checker reply.
The agent can commit first if authorized, or retry the edit to proceed; there is no automatic commit, acknowledgment tool, or special retry state.
`unusable`, including an already-lost or unavailable boundary, permits ordinary editing and forgets the checked boundary.
A late result can forget only a record with the same revision it checked, never a different replacement.
Unexpected producer errors are normal nonzero checker-command failures. The harness catches them, conditionally forgets the checked boundary, reports the actual error once, and permits ordinary editing through the same target-verification and cancellation finalization.

The boundary includes pre-existing dirty changes and does not establish authorship or authorize committing them.
The record contains only the immutable revision, not source copies, parent/root identity, tokens, timestamps, or host/guest paths. A missing or empty record means no boundary.
Capture atomically renames a fresh temporary inode; forgetting reads, compares, and truncates the same open `r+` descriptor, never unlinking or writing another ID in place. A newer capture therefore survives a late clear.
Version one checks regular UTF-8 files and ordinary file creation, not symlinks, binary content, or file-kind conversions; shell commands are not intercepted.
Native observed target bytes are retained for the check, not reread by the checker.
Skipped or unusable comparisons still pass through cancellation and target-state verification before writing.

This uses the repository's `bb agent-split` wrapper and Jujutsu, not a second TypeScript containment implementation, new service, or extra public tool.
The [splitter reference](../../../tools/agent-split/README.md#advisory-commit-boundary-api) documents the read-only JSON check; checkpoint capture uses ordinary wrapped Jujutsu commands, not a splitter `--checkpoint` mode.
The [design](commit-boundary/design.typ) defines the shared record, exact request/reply contract, lifecycle, and finalization behavior.
Native tools check the local file; sandbox tools check the file actually being written inside the guest, using common harness record operations rather than checkpoint transport metadata.
Remote filesystem operations do not redirect the Pi SDK's local edit preview.
Guest edits therefore render a header-only call and the actual guest result through the SDK's public result renderer; native edit previews remain unchanged.
The public-renderer regressions in [`tests/pi/commit_boundary_operations_test.ts`](../../../tests/pi/commit_boundary_operations_test.ts) cover guest refusals, successful edits, mismatches, and missing files without host previews.

The integration must be loaded for these checks to apply. The normal sandbox-subagent wrapper explicitly injects guest tools despite `--no-extensions`, so fresh Luna sandbox workers need no special template once the integration is loaded.
Native nonsandbox subagents intentionally disable extension discovery, and the current native configuration does not list these extensions; native children do not universally load the guard automatically.

The implementation and integration tests are complete, and jyn manually verified the feature in a sandbox session; this does not establish global activation or universal extension loading.
It does not activate global configuration or authorize setup or deployment.
An existing internal guest lifecycle capture request may call the same common capture and storage operations; it is not a new model-facing tool or splitter CLI mode.

## Compaction

`compact_session({ report: "..." })` replaces preceding conversation context with a checkpoint written by the active agent, then continues in the same session.
Read [`compaction.md`](compaction.md) before preparing the report; the tool description points to its source location in the agent's filesystem.
Sandbox descriptions use the launcher's resource path mapping; host-side Luna reads still use the host source path.
Call the tool alone after other tools finish, not in a parallel batch or through another tool.
The report is used unchanged, with a caller-produced recovery appendix; no additional summarizer request is made.
The tool checks the required heading, not the report's accuracy or completeness.

Replacement happens at Pi's completed-turn boundary, after its tool result is saved.
Cancellation or session/branch replacement discards a pending request.
The transcript is retained: use `read_session` with the supplied session identity to recover preceding messages.
In-memory sessions have no saved transcript to recover.
System instructions, tools, goals, and worker state keep their existing owners; compaction does not authorize work or change goal status.
This tool requires Pi's actionable `turn_end` boundary and `CompactionEntryDraft.firstKeptEntryId: null` APIs.
Run `/reload` after updating extension code.

Manual and automatic compaction still use the Luna extension and [`compaction.md`](compaction.md) to produce one checkpoint covering history and any split-turn prefix.
Its three sections are **Objective and authority**, **Current work**, and **Recovery**.
Checkpoints carry forward the last established user request when no newer request is recorded.
Each activity keeps its permission, unmet outcomes or questions, evidence, decisions, owning session or agent, holds, and recorded next action together.
Generated checkpoints must include an `Objective and authority` Markdown heading; the extension does not evaluate the meaning of their prose.
If Luna fails, omits that header, or is unavailable, the active model uses the same instructions.
If generation fails, session history is kept.

Both paths append a short `jj status` excerpt, working directory, capture time, and recovery locator, with a recorded-target count when target metadata is available.
Oversized status retains the beginning and end of text fields, marks omissions, and sets `truncated: true`.
The end preserves revision information without parsing individual status lines.
Failed captures report unknown state; omitted paths do not establish a clean working copy.
Status can become stale and is not evidence of task completion.

The complete status remains in `details.repositoryState`; all recorded edit/write targets remain in `details.modifiedFiles`.
Luna collects targets from tool-call arguments, including failed attempts and already committed work, not from current dirty status.
They do not prove successful edits, authorship, current ownership, or commit coverage.
Self-authored compaction carries already-recorded targets forward without collecting intervening calls; an absent collection is not an observed empty list.
Targets from the matching previous checkpoint carry forward, but no target inventory is appended to model-visible context.
The caller appendix is excluded from later compaction requests using `details.checkpointLength`.
Task-specific ownership and uncertain-operation paths still belong beside the relevant activity in the generated checkpoint.

### Recover a compaction capture

The visible `recovery` object identifies the session by `sessionId` and `sessionFile`, and the raw capture by `captureId`.
The capture ID is also saved as `details.captureId`; it does not depend on the generated prose or timestamp.
Set `session_file` and `capture_id` to the corresponding visible values, then read the matching raw JSONL entry:

```sh
jq --arg capture "$capture_id" \
  'select(.type == "compaction" and .details.captureId == $capture) | .details' \
  "$session_file"
```

Select a specific field or status range when the complete capture would exceed tool-output limits.
If the path uses a different host/guest namespace, find the JSONL filename containing `recovery.sessionId` under this environment's Pi session root.
For example, with `session_root` and `session_id` set to that root and visible ID:

```sh
find "$session_root" -type f -name "*_${session_id}.jsonl"
```

Use the local path for the raw query; `read_session` omits capture details and does not show its resolved path in model-visible output.
A null `recovery.sessionFile` means an in-memory session with no saved file to query.
Older compactions have no capture ID; inspect their raw entries by native entry ID instead.

Luna reads the instructions afresh for each generated checkpoint; instruction-only edits need no reload.
After changing extension code, use `/reload` as described above.
Follow the [testing guide](../../../dev/README.md#testing-and-probes) for locked dependencies and offline compaction tests.
These include native extension loading, persisted-context reconstruction, and recovery of full captures through their visible locators.
See [compaction replay](../../../dev/README.md#replay-a-compaction) to compare instruction changes against saved sessions.

## Side conversations: `/split`

Under tmux, `/split` opens another host Pi pane on the same guest worker and
copies the active branch's completed context into a fresh saved session. It does
not stop the source; pending tool batches and live
extension/child state are not transferred. Compaction summaries remain intact;
if a retained range starts at an omitted entry, its boundary advances to the
first surviving entry. An empty range retains only its summary, not older
messages. Panes share files, not later messages.

The worker remains until its last Pi attachment closes; ordinary subagents remain
parent-owned. `/split [prompt]` focuses the new pane and automatically sends the
optional prompt there. Without a prompt, the new pane starts idle.

New splits record the immediate parent's session ID and, when available,
saved session file. On every turn, model guidance distinguishes copied history
from a new assignment and asks the agent to check the parent's current work
before writing or delegating. This guidance survives compaction and resume;
it is not a filesystem lock or an automatic work-ownership check. A nested
`/split` names its immediate source, and native forks do not inherit this guidance.
Older snapshots without this metadata are unchanged.
Use `read_session({ sessionId: "PARENT_ID" })` to inspect a saved parent within the reader's configured session root.
Its recorded absolute file path may use a different host/guest namespace; do not weaken the reader's root restriction to follow it.

It is unavailable to ordinary subagents
or outside an interactive sandbox. Native `/clone`, `/fork`, and `/resume` are
unchanged.

Refused startup removes only its unpublished snapshot. If the host connection
fails after submission, the outcome is unknown: retain the snapshot and do not
retry. Check tmux before invoking `/split` again.

## Asynchronous questions: `ask_user`

The model queues one batch per tool call. `ask_user` returns question IDs
immediately; it does not open the panel or wait for answers. Titles, question text,
and supplied options must be non-empty. Options are optional, and free-text
answers are always available.

For consequential approvals or questions that require substantial context, the tool's prompt guidance routes the model
to [`human-review-packets`](../../../skills/human-review-packets/SKILL.md).
Simple preference questions, routine confirmations, and requests for missing facts do not need that skill.

```json
{
  "questions": [
    {
      "title": "Output format",
      "question": "Which output format should the export use?",
      "options": ["JSON", "CSV"]
    },
    {
      "title": "Scope",
      "question": "Which directories should be included?"
    }
  ]
}
```

A pending count and **Alt+A** hint appear above the normal editor; the extension
does not modify that editor.

### Cancelling obsolete questions

The model can call `cancel_ask_user({ "question_ids": ["<ID from ask_user>"] })`
when later work makes a question unnecessary. Cancellation removes only those
pending questions and their drafts in the active session. It preserves unrelated
questions and drafts, switches away from a cancelled selection, and closes an
empty panel immediately.

The result reports `cancelled` and `notPending` IDs. Duplicate IDs are processed
once; unknown, already answered, or already cancelled IDs are reported as not
pending. Cancellation persists before changing the panel; a synchronous save
failure leaves the questions and drafts intact. Reload restores the saved queue
without cancelled questions. Cancellation does not recall an answer already
dispatched, supply an answer, or grant permission to do dependent work.

### Panel controls and drafts

- **Alt+A** opens the last-viewed pending question, or the oldest if none was viewed.
- The header shows **Question N of M — title**. **Alt+Left / Alt+Right** cycle
  through pending questions, wrapping at either end.
- **Up / Down**, then **Enter**, choose an option. Choose “Type a free answer…” or
  start typing to enter text; **Tab** switches between options and text.
- **Enter** submits free text. **Shift+Enter / Ctrl+J** insert a newline using
  Pi's default editor bindings.
- **Escape** closes the panel without answering or cancelling questions.

Text and option-selection drafts survive cycling and closing/reopening the panel.
New tool calls append questions without moving the open panel's selection.
Submission removes that question, advances to the next pending question (wrapping),
and closes the panel when none remain.

### Delivery and model guidance

A submission sends the question ID, title, original question, and answer through
`pi.sendUserMessage(..., { deliverAs: "steer" })`. Pi owns the transcript, normal
editor, message queue, and model-turn delivery; the extension owns pending
questions, drafts, and panel selection.

The transcript quotes the original question, then shows the unaltered answer as
normal Markdown. A display-only Markdown transformer hides the ID and
JSON-encoded title header in the TUI; the original steering message retains both
in session storage and model context. Rendering needs no pending state, including
on reload or resize. Historical label-based messages remain unchanged because
their multiline boundaries are ambiguous.

While questions are unanswered, the model may continue **only independent work**.
Silence, closing the panel, and successful queueing are **not an answer or
permission**. Work requiring an answer must wait for the corresponding steering
message.

`sendUserMessage` returns **void**, not a delivery acknowledgement. The panel
removes a question when the call returns without a synchronous exception. A
synchronous exception preserves the question and draft for retry with Enter. Pi
reports asynchronous delivery errors separately; the extension cannot guarantee
model receipt or automatically restore an answer after such an error. Users can
resend the answer as a normal message, including the question ID from the queued
tool result. Panel closure does not prove delivery.

### Persistence and errors

Unresolved questions are persisted as versioned Pi custom-entry snapshots through
`appendEntry`; the latest snapshot on `getBranch()` is authoritative. Reload or
resume restores pending questions from the active branch, and tree navigation and
forks follow that branch's saved state. Snapshots are not LLM messages. Storage
follows Pi's session persistence; an ephemeral session is not a durable disk backup.

Draft text, option selection, and last-viewed selection are **memory-only**. They
survive panel cycling and close/reopen, but not `/reload`, session replacement, or
tree navigation. Session shutdown closes an open panel and invalidates callbacks
so old answers cannot be submitted into a replacement session.

Print, JSON, and RPC modes produce an explicit tool error and queue nothing.
Cancelled calls, invalid inputs, and synchronous queue-persistence errors also
queue nothing. Invalid saved snapshots trigger a notification rather than
restoring malformed questions. If saving after dispatch fails, the answer is not
offered for duplicate submission; a notification warns reload may restore that
question. Asynchronous delivery remains Pi's responsibility.
