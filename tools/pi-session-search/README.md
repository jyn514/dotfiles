# pi-session-search

A [pi-coding-agent](https://github.com/earendil-works/pi) extension for searching
prior Pi and Codex transcripts on disk **without resuming them**.

> When a topic comes up that you've discussed in a previous session, you don't
> want to dig through `~/.pi/agent/sessions/` by hand or fully resume an old
> session just to peek. This extension gives the model a tool to grep prior
> sessions and pull a window of context, so it can say "yes, we hit this on
> 2026-04-21 in `~/workspace/foo`" mid-conversation.

## What you get

- **Tool `search_sessions`** — the LLM can call this itself when the user
  references a prior conversation. Substring or `/regex/flags`, optional
  filters by `cwd`, time range, role, and tool calls. Returns a JSON list of
  hits with `sessionFile` (relative to the Pi root, absolute for subagents and Codex),
  `sessionId`, `sessionCwd`, `timestamp`, `role`, a snippet, and `entryId` when present.
- **Tool `read_session`** — read around a specific hit, from the start or end,
  or after a previous read. Use after a promising `search_sessions` result to pull more
  context without resuming the session. Provide exactly one of `sessionFile`
  (any readable file, absolute or relative to the configured Pi root) or `sessionId` (the exact header
  ID). ID reads work when a parent path names a different machine or sandbox;
  the session must still exist under a configured local root.
  Ambiguous Codex IDs return an indexed version list with previews, not full transcripts.
- **Command `/find-sessions [flags] <query>`** — manual search from the TUI.
  Flags: `--cwd=substr`, `--role=user|assistant`, `--since=ISO`, `--max=N`.
  Results are printed into the current session as a custom message.
- **CLI `pi-session-search`** — expose the same search and read operations to
  scripts and agents outside Pi. Successful operations return structured JSON.

The Pi tool excludes the current session from results by default (you can
override per tool call). The CLI has no active session; use
`--exclude-session-id` when needed. All interfaces are read-only and never
modify session files.

## Prerequisites

Node.js **>=22.19.0** and
[`@earendil-works/pi-coding-agent` 1.0.2](https://github.com/earendil-works/pi)
installed and working. This extension requires no API keys or extra services.

If you use the deprecated `@mariozechner/pi-coding-agent`, migrate to the
maintained CLI before installing or reloading this extension. For an npm-global
installation, remove the old package first because both CLIs provide `pi`:

```bash
npm uninstall -g @mariozechner/pi-coding-agent
npm install -g --ignore-scripts @earendil-works/pi-coding-agent@1.0.2
```

## Installation

### Option A — install from npm (recommended)

```bash
pi install npm:@adobe/pi-session-search
```

Then `/reload` in pi (or restart). The tools and command will appear. Update
later with `pi update npm:@adobe/pi-session-search`.

### Option B — clone into your pi extensions directory

```bash
mkdir -p ~/.pi/agent/extensions
cd ~/.pi/agent/extensions
git clone https://github.com/adobe/pi-session-search.git
```

Then `/reload` in pi (or restart).

### Option C — symlink from anywhere

```bash
git clone https://github.com/adobe/pi-session-search.git ~/code/pi-session-search
ln -s ~/code/pi-session-search ~/.pi/agent/extensions/pi-session-search
```

### Option D — one-off

```bash
pi -e ~/code/pi-session-search/index.ts
```

## Usage

### Use the CLI

Search both Pi and Codex sessions from a shell:

```bash
pi-session-search search --cwd cocoa --role user --max-results 5 "dictionary evidence"
```

Read context around a returned entry without resuming its session:

```bash
pi-session-search read \
  --file '<sessionFile from search>' \
  --around-entry-id '<entryId from search>' \
  --max-messages 5
```

`search` returns `SearchResult` as JSON and `read` returns
`ReadSessionResult` as JSON. Pass each `sessionFile`, `entryId`, and
`nextCursor` back unchanged. Run `pi-session-search --help`,
`pi-session-search search --help`, or `pi-session-search read --help` for the
complete option list.

Errors write one diagnostic to stderr and leave stdout empty. Exit status `2`
means invalid command syntax, `1` means the session operation failed, and `130`
means `SIGINT` cancelled the operation.

### Let the LLM drive

Just mention prior sessions in plain English:

> "Have we ever debugged the vault-overseer ingress before?"
>
> "What did we decide about the Okta migration plan last week?"
>
> "Find any session where I got an `ExternalSecret` error."

The model picks up the cue, calls `search_sessions`, and (optionally) follows
up with `read_session` for the most promising hit.

To compare several sessions without letting one long conversation fill the response, set `maxResultsPerSession`:

```json
{"query": "diff-check", "role": "assistant", "maxResults": 20, "maxResultsPerSession": 2}
```

The option accepts integers in `[1, 1000]` and has no per-session limit when omitted.
It counts retained hits per session file, after scope filtering and copied-record suppression.
Once a file reaches the cap, search stops reading that file and moves to the next; `maxResults` still limits the total.
Matches are retained in encounter order and only the retained hits are sorted newest-first.
This is not a selection of the newest or most relevant matches in each session.
Use `read_session` to inspect promising hits in context.

### Search coverage

Results distinguish three kinds of limits:

- `sessionsAtLimit` counts session files that reached the per-session cap, including when both caps coincide or the last record reaches it.
  Remaining records in those files were not searched; the count does not imply that additional matches exist.
- `truncated` means the total hit limit stopped the search.
- `incompleteCoverage` means records or files were skipped, or the search was cancelled.
  Intentional hit limits do not set it.

### Read and follow a session

Use a search hit's `sessionFile` and `entryId` to read the exact matching entry:

```json
{"sessionFile": "<hit.sessionFile>", "aroundEntryId": "<hit.entryId>", "maxMessages": 3}
```

These placeholders represent values from the search result.
For older records without entry IDs, use `aroundTimestamp` with the hit's timestamp instead.
Timestamp reads select the nearest eligible message and break ties in file order; invalid timestamps fail.

Centered reads keep the target whenever `maxMessages` is positive, then fit surrounding context within the limit.
`contextMessages` defaults to six on each side.
With an interior target at message 100, a limit of one returns message 100; a limit of three returns messages 99–101.
An even-sized window favors preceding context when both sides have enough messages.

To read recent activity without searching first:

```json
{"sessionId": "<session ID>", "tail": true, "maxMessages": 10}
```

The result contains the last ten eligible messages in conversation order, not timestamp order.
Without a positioning option, reads still start at the beginning.

Each transcript read returns `nextCursor`, including when no new messages exist.
A Codex version list returns `versions` instead of a cursor; choose a listed `sessionFile` before continuing.
Pass `nextCursor` back unchanged to continue after that read:

```json
{"sessionId": "<same session ID>", "after": "<nextCursor>", "maxMessages": 10}
```

`hasMore` means more eligible messages remain in that call's history snapshot.
A false value does not mean the session has ended: call again with the cursor to check later appends.
Cursors refer to file positions, not timestamps, so equal or out-of-order timestamps do not lose messages.
A cursor fails explicitly if consumed history changes, a consumed file shrinks past its position, or another file replaces it.
For Codex this includes consumed inherited prefixes; later changes outside an inherited cutoff do not invalidate the cursor.
Start a new read without `after` to recover.
Cursors are opaque and local to the selected session file; they are not portable bookmarks between machines or copied sessions.
Changing `PI_SESSION_SEARCH_MAX_BYTES` also invalidates a cursor because it can change which records count as messages.
Incomplete trailing JSON waits for a later call rather than advancing the cursor past it.
Cursors issued before custom-message support keep their original byte boundary and do not replay earlier custom messages.
Start a new read to include those earlier messages.

Use at most one of `tail: true`, `after`, `aroundEntryId`, and `aroundTimestamp`.
`maxMessages: 0` returns no messages and preserves the starting cursor position.
With `tail: true`, it instead selects the safe end of the file so you can follow only future messages.
Each message shows its actual eligible-message position, role, timestamp, and entry ID when present.
Structured details include `sessionFile`, the resolved absolute realpath of the selected transcript, alongside message metadata,
the cursor, `hasMore`, and skipped-record counts.
Both file and ID selectors return this path, including empty reads; version lists omit the top-level `sessionFile`.
The ID selector and positioning options are not echoed.

Reads include nonempty user/assistant text, assistant tool-call summaries, and text from Pi `custom_message` entries.
Custom messages participate in every read mode, including when Pi hides them in the TUI (`display: false`).
Their headers and structured message metadata preserve `role: "custom"` and the original `customType`.
`aroundEntryId` accepts a custom message's entry ID just like a user or assistant entry ID.
Search still matches only user/assistant messages.
Ordinary reads omit tool results, thinking-only messages, images, custom state entries (`type: "custom"`), and custom-message `details`.
An explicit Pi tool-result or compaction `aroundEntryId` read also makes that source record inspectable.
It shows tool-result text and persisted nested calls, or the checkpoint summary and modified-file list, as a centered custom entry.
These records do not enter ordinary message pagination; the inspection cursor resumes with ordinary messages.
Tool-call summaries mark truncated arguments with an ellipsis.
Positions count only eligible messages, including readable custom messages, and exclude oversized records.

### Find earlier edit candidates with codemode

Use `view: "edit_candidates"` to find recorded Pi edit/write paths before inspecting earlier work.
Unlike ordinary reads, which still return a string to codemode, this view returns a structured page:

```js
const page = await tools.read_session({
  sessionId: "<session ID>",
  view: "edit_candidates"
});
const candidates = page.candidates.filter(candidate =>
  candidate.targets.some(target => target.path.includes("skills/autonomous-work/"))
);
const inspections = await Promise.all(candidates.map(candidate =>
  tools.read_session({ ...candidate.source, maxMessages: 1 })
));
return {
  candidates,
  inspections,
  nextCursor: page.nextCursor,
  hasMore: page.hasMore,
  incomplete: page.incomplete
};
```

Each candidate represents one source record and has `source: { sessionFile, aroundEntryId }`, `timestamp`, and `targets`.
Targets retain their recorded paths and distinguish `kind: "tool_call"`, `"nested_call"`, and `"checkpoint"`.
Direct and nested targets come from `edit`/`write` arguments and include the tool name and call ID when recorded.
Checkpoint paths come only from `compaction.details.modifiedFiles`; they do not establish a new edit at that checkpoint.
No shell commands, script text, prose, tool outcomes, or current working-copy state are interpreted.
A failed edit is still a candidate, not evidence of successful work, authorship, ownership, or completion.

`maxMessages` counts whole candidate records, not targets; one record's nested-call targets stay together.
The serialized candidate list is limited to 64 KiB, plus navigation metadata.
A record that cannot fit intact, or lacks an exact entry ID for inspection, is omitted and counted in `skippedRecords`.
Oversized raw records and malformed complete JSON records also count as skips.
`incomplete` is true when the snapshot has skips or incomplete nested-call evidence, including omitted edit/write arguments.
An affected candidate also has `incomplete: true`; missing arguments never produce invented paths.
False does not certify an exhaustive edit inventory, especially for older transcripts without persisted nested calls.

When `hasMore` is true, request the same file/session and view with `after: page.nextCursor`.
Cursors cannot cross views; ordinary append, stale-prefix, tail, and centered-selection behavior still applies.
Candidate reads support Pi transcripts only; Codex candidate reads fail explicitly rather than returning an empty shortlist.

### Codex versions and inherited history

Search includes retained Codex versions, including versions superseded by revert.
A session ID can therefore name several files, not consecutive pieces of one conversation.

```json
{"sessionId": "<Codex thread ID>"}
```

When several versions match, this returns a successful indexed list with each version's timestamp, cwd,
first local user-message preview, and absolute `sessionFile`.
Structured details contain `versions`, an empty `messages` list, and no top-level `sessionFile` or `nextCursor`.
Pass a listed path unchanged to read that version:

```json
{"sessionFile": "<version.sessionFile>", "tail": true, "maxMessages": 10}
```

The reader follows that version's `history_base` references, retaining only the specified byte and ordinal prefixes of ancestor files.
Windows and cursors cross those file boundaries in conversation order.
It does not concatenate same-ID files or guess which version Codex currently selects.
Missing, cyclic, non-paginated, or unreadable ancestry fails explicitly instead of returning partial history.
Pi-only duplicate IDs still fail and ask for `sessionFile`.

### Drive it yourself

```
/find-sessions vault-overseer
/find-sessions --cwd=OneAdobe --since=2026-04-01 ExternalSecret
/find-sessions --role=user --max=5 "okta migration"
```

Use slashes around a query for regex. The regex form respects user flags
including case-sensitivity — `/Foo/` matches `Foo` but not `foo`. The `g`
and `y` flags are stripped (they break match-position tracking).

```
/find-sessions /ACPCSRE-\d+/
/find-sessions /ExternalSecret/i        # explicit case-insensitive
/find-sessions /^assistant says/m       # multiline mode preserved
```

### Automatic filtering

For Pi, both search entrypoints always exclude text-only user messages whose whole text
is a `<pi_goal_continuation goal_id="…">…</pi_goal_continuation>` envelope.
Mentions, quoted examples, partial envelopes, surrounding prose, and messages
with images remain searchable. This recognizes a format, not authorship: a
human-pasted whole envelope is excluded too. Custom messages are already outside
the user/assistant search scope.

Search also collapses matching copied records across session files when their
nonempty entry ID and timestamp, complete message value, and hit kind agree.
Independent repetitions, incomplete identities, changed message values, and
repeated records within one file remain distinct.
Pi and Codex identities remain separate.
Scope filters apply first;
the retained hit points to the first encountered eligible file, not necessarily
the original session. Assistant text and tool-call hits remain separate.

Results report `excludedGoalContinuations` and `duplicateHitsSuppressed`; the
command shows these counts when nonzero. Counts cover only scanned records:
search still stops at `maxResults` retained hits, not after scanning the archive.
With `maxResultsPerSession`, counters exclude the unsearched remainder of capped files.
Neither filter marks coverage incomplete. Identity tracking stores at most
`maxResults` fingerprints of complete bounded messages, not transcript contents.
Pi reads retain goal-continuation envelopes and copied messages so you can inspect surrounding context.
Codex search and reads omit duplicate event records, developer instructions, reasoning, and tool results.
Valid, complete `content_item_kinds` metadata excludes classified non-user context from user messages.
Missing or malformed classifications, `user.*`, empty classifications, and `unknown` remain readable.
Older unclassified injected context can therefore appear as user text.

## Configuration

Environment variables:

- `PI_SESSION_SEARCH_ROOT` — override the sessions directory (default
  `~/.pi/agent/sessions`).
- `PI_SESSION_SEARCH_SUBAGENT_ROOT` — override the Pi subagent transcript directory.
  Defaults to `$PI_CODING_AGENT_DIR/pi-codex-subagents/runs`, or `~/.pi/agent/pi-codex-subagents/runs` when unset.
  Set this override when the subagent extension uses a custom `storageDir`.
  A missing subagent directory is an empty source.
- `PI_SESSION_SEARCH_CODEX_ROOT` — override the Codex sessions directory.
  Defaults to `$CODEX_HOME/sessions` when `CODEX_HOME` is set, otherwise `~/.codex/sessions`.
  A missing Codex root is an empty source; it does not prevent Pi searches.
  In a sandbox, mount the sessions you want to search and point this variable at that mount.
- `PI_SESSION_SEARCH_MAX_BYTES` — per-record raw-byte cap (default 5 MiB,
  5,242,880 bytes). It is enforced before decoding/parsing and excludes the LF
  delimiter. Existing overrides still apply, but revisit old file-size
  overrides: this setting now limits one record's memory use, not whole files.
  Files have no whole-file size ceiling. Oversized records are skipped through
  the next newline, then reading continues. `search_sessions` reports
  `skippedRecords` and `incompleteCoverage`; `read_session` and
  `/find-sessions` show an incomplete-coverage warning.

## How it works

Pi stores each session as a JSONL file under
`~/.pi/agent/sessions/<encoded-cwd>/<timestamp>_<uuid>.jsonl`. Each line is a
JSON object — the first is a `session` header (with `id` and `cwd`), the rest
are `message` entries (and a few other types).

`search_sessions` walks the Pi sessions directory and the subagent store, then recursively walks the Codex root.
Subagent transcripts use `<parent-key>/<child-id>.jsonl`; their headers supply cwd and date filters.
Subagent hits return absolute paths so they round-trip without changing the normal Pi root.
It streams JSONL records, extracts conversation text (skipping images and, by default, tool calls), and matches your query.
Codex `session_meta` supplies thread identity, cwd, and date filtering; `response_item` supplies messages and function/custom tool calls.
Duplicate `event_msg` representations are ignored.
Search retains only hits and stops at `maxResults` or cancellation.
The optional `maxResultsPerSession` skips each file's remaining records once its retained-hit cap is reached.
See [Let the LLM drive](#let-the-llm-drive) for result-limit and coverage fields.
Skipped-record counts cover only the portion actually scanned.

For `sessionId`, `read_session` scans the configured roots and reads bounded first-record headers to find matching IDs.
Malformed or oversized headers cannot resolve an ID.
Symlink aliases of one resolved file do not create ambiguity.
Codex rollout filenames identify physical history references, not thread identity.
See [Codex's upstream lineage reader][codex-lineage] for inherited-history resolution, pinned to the revision inspected for this implementation.
ID lookup adds a header scan on each call; there is no persistent index or cache.

`read_session` streams snapshots bounded by initial file sizes and inherited-prefix cutoffs, so later appends wait until the next call.
It counts eligible messages, selects the requested window, and retains only that window.
Cursor validation checks the consumed prefix without retaining the transcript in memory.
`contextMessages` and `maxMessages` accept non-negative safe integers, including `0` (defaults 6 and 30).
Memory use depends on one bounded record, retained hits or the requested window, and file/history metadata, not transcript contents.

No model is called. No external network. No session is mutated.

## Trust model & security notes

**This tool is read-only and intended for a single trusted local user.** It
gives the active LLM access to prior Pi and Codex conversations, including subagent transcripts and explicitly selected files.
That makes it a productivity tool *and* a meaningful exfiltration primitive with untrusted input.

**Trust boundary.**

- The user owns and trusts the configured search roots and explicitly selected transcript files.
- Explicit file reads can open any file readable by the process, including symlink targets outside the search roots.
  Search roots control discovery, not filesystem access; use operating-system or sandbox permissions to restrict access.
- Anything in a selected transcript — user messages, assistant messages, tool calls,
  tool results — is treated as readable by the active model.

**Mitigations actually in place.**

- **Read-only.** No tool here writes, deletes, or transmits anything.
- **Explicit file selection in `read_session`.** Resolves the supplied path and selects the Pi or Codex decoder from the header.
  Relative paths resolve from the configured Pi root; absolute paths are never rewritten to another location.
  ID and Codex ancestor discovery still check containment on every directory and file before reading headers.
- **Path containment in `search_sessions`.** Per-subdirectory and per-file
  symlink containment: a `.jsonl` symlinked outside the root is detected at
  `realpath` time and skipped (counted as `skippedFiles` in the result).
- **Bounded record parsing.** Both tools enforce the configured raw-record
  limit (default 5 MiB, 5,242,880 bytes) before UTF-8 decoding or JSON parsing.
  Oversized records are discarded up to the next newline, even if they contain
  images or tool results rather
  than searchable text. Skips are counted and reported; window message
  indexes and totals exclude skipped records.
- **`maxResults` is bounded.** The schema enforces `[1, 1000]`; the runtime
  rejects explicit invalid values (including `0`, negative, NaN, Infinity).
  The default is 20.
  The optional `maxResultsPerSession` uses the same range and runtime validation without raising the total cap.
- **Regex flag stripping.** The `/.../flags` form respects user flags
  (including case-sensitivity) **except** `g` and `y`, which are stripped
  because they break match-position bookkeeping (`g` removes `.index`, `y`
  is stateful via `lastIndex`).
- **Per-haystack byte cap.** Each message's text is capped to 256 KB
  before regex matching. Bounds best-case ReDoS but does **not** bound a
  truly catastrophic regex within those 256 KB.

**Accepted risks / things the threat model doesn't try to defend against.**

- **Same-user filesystem attacker.** TOCTOU between the symlink check and
  opening the stream is theoretically exploitable, as is rewriting a file
  between window-reading passes. The threat model assumes the user controls
  her own home directory.
- **Prompt injection from past content.** Anything text-shaped in a previous
  session can land back in the active model's context as tool output. If
  hostile instructions were ever pasted into a prior chat, an LLM that
  reads them later may try to follow them. **Treat this tool's output like
  web-search output: signal, not orders.** The same applies to secrets
  pasted into past sessions — they will be echoed back in snippets.
- **Session-root overrides accept any path.** If you set one to a
  non-sessions directory (or an attacker can influence your environment),
  the tool will dutifully grep that directory for whatever the model asks
  for. **Never expose `search_sessions` to a model operating on untrusted
  user input** — it can read every line of every prior conversation, and
  with a redirected root, of any text file at all.
- **ReDoS within 256 KB.** No catastrophic-backtracking guard beyond the
  haystack cap. A trusted local user is unlikely to weaponise their own
  shell against themselves; for any other deployment add an external
  timeout.

## Limitations

- Codex support reads plain JSONL `session_meta` / `response_item` records and paginated `history_base` references.
  Inter-agent `agent_message` records are currently omitted.
  Compressed `.jsonl.zst` files and Codex's SQLite-selected active-version pointer are not read.
  Archived files outside the configured Codex root are not searched or followed.
  Put required ancestors under that root; the reader does not bypass containment to find them.
  Byte offsets and ordinals must fit JavaScript's safe-integer range.

- Large transcripts take proportionally longer to scan even though memory
  use is bounded. Tool calls support cancellation between records and reads;
  a synchronous regex still cannot be interrupted mid-match.

- The encoded cwd directory name is decoded with a naive `-`→`/` rewrite.
  Sessions started in a path containing literal `-` will look slightly odd in
  `sessionCwd` but the `cwd` from the session header (used when present) is
  exact.
- Tool *results* are not searched by default. They tend to be enormous (file
  contents, command output) and would dominate matches. You can search tool
  *call names/args* with `includeToolCalls: true`.
- Old sessions without a header `cwd` field show the directory-decoded path
  instead.
- Branched sessions (multiple leaf paths) are scanned linearly; matches from
  abandoned branches will appear alongside live ones.

## Versioning

This project follows [Semantic Versioning](https://semver.org/). Notable
changes are recorded in [CHANGELOG.md](CHANGELOG.md). While the version is
`0.x`, breaking changes may land in minor bumps; once it goes `1.0`, breaking
changes will only land in major bumps.

## License

Apache License 2.0. See [LICENSE](LICENSE).

[codex-lineage]: https://github.com/openai/codex/blob/ce0323f2f2d3b25e82806cd555237da3db4e1897/codex-rs/thread-store/src/local/rollout_lineage.rs
