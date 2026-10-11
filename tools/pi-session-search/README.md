# pi-session-search

A [pi-coding-agent](https://github.com/earendil-works/pi) extension that lets the
active LLM (and you) search prior pi session transcripts on disk **without
resuming them**.

> When a topic comes up that you've discussed in a previous session, you don't
> want to dig through `~/.pi/agent/sessions/` by hand or fully resume an old
> session just to peek. This extension gives the model a tool to grep prior
> sessions and pull a window of context, so it can say "yes, we hit this on
> 2026-04-21 in `~/workspace/foo`" mid-conversation.

## What you get

- **Tool `search_sessions`** — the LLM can call this itself when the user
  references a prior conversation. Substring or `/regex/flags`, optional
  filters by `cwd`, time range, role, and tool calls. Returns a JSON list of
  hits with `sessionFile` (relative to the sessions root), `sessionId`,
  `sessionCwd`, `timestamp`, `role`, a snippet, and `entryId` when the record has one.
- **Tool `read_session`** — read around a specific hit, from the start or end,
  or after a previous read. Use after a promising `search_sessions` result to pull more
  context without resuming the session. Provide exactly one of `sessionFile`
  (absolute or relative to the configured root) or `sessionId` (the exact header
  ID). ID reads work when a parent path names a different machine or sandbox;
  the session must still exist under the configured local root.
- **Command `/find-sessions [flags] <query>`** — manual search from the TUI.
  Flags: `--cwd=substr`, `--role=user|assistant`, `--since=ISO`, `--max=N`.
  Results are printed into the current session as a custom message.

The current session is excluded from results by default (you can override per
tool call). Read-only — never modifies session files.

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

The result contains the last ten eligible messages in file order, not timestamp order.
Without a positioning option, reads still start at the beginning.

Each read returns `nextCursor`, including when no new messages exist.
Pass it back unchanged to continue after that read:

```json
{"sessionId": "<same session ID>", "after": "<nextCursor>", "maxMessages": 10}
```

`hasMore` means more eligible messages remain in that call's file snapshot.
A false value does not mean the session has ended: call again with the cursor to check later appends.
Cursors refer to file positions, not timestamps, so equal or out-of-order timestamps do not lose messages.
A cursor fails explicitly if its consumed file prefix changes, the file shrinks past its position, or another file replaces it.
Start a new read without `after` to recover.
Cursors are opaque and local to the selected session file; they are not portable bookmarks between machines or copied sessions.
Changing `PI_SESSION_SEARCH_MAX_BYTES` also invalidates a cursor because it can change which records count as messages.
Incomplete trailing JSON waits for a later call rather than advancing the cursor past it.

Use at most one of `tail: true`, `after`, `aroundEntryId`, and `aroundTimestamp`.
`maxMessages: 0` returns no messages and preserves the starting cursor position.
With `tail: true`, it instead selects the safe end of the file so you can follow only future messages.
Each message shows its actual eligible-message position, role, timestamp, and entry ID when present.
Structured details return the message metadata, cursor, `hasMore`, and skipped-record counts, without echoing the requested selector or limits.

Reads include nonempty user/assistant text and assistant tool-call summaries, not the entire raw transcript.
They omit tool results, thinking-only messages, and custom entries.
Tool-call summaries mark truncated arguments with an ellipsis.
Positions count only eligible messages and exclude oversized records.

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

Both search entrypoints always exclude text-only user messages whose whole text
is a `<pi_goal_continuation goal_id="…">…</pi_goal_continuation>` envelope.
Mentions, quoted examples, partial envelopes, surrounding prose, and messages
with images remain searchable. This recognizes a format, not authorship: a
human-pasted whole envelope is excluded too. Custom messages are already outside
the user/assistant search scope.

Search also collapses matching copied records across session files when their
nonempty entry ID and timestamp, complete message value, and hit kind agree.
Independent repetitions, incomplete identities, changed message values, and
repeated records within one file remain distinct. Scope filters apply first;
the retained hit points to the first encountered eligible file, not necessarily
the original session. Assistant text and tool-call hits remain separate.

Results report `excludedGoalContinuations` and `duplicateHitsSuppressed`; the
command shows these counts when nonzero. Counts cover only scanned records:
search still stops at `maxResults` retained hits, not after scanning the archive.
With `maxResultsPerSession`, counters exclude the unsearched remainder of capped files.
Neither filter marks coverage incomplete. Identity tracking stores at most
`maxResults` fingerprints of complete bounded messages, not transcript contents.
`read_session` remains unfiltered so you can inspect the actual surrounding
messages.

## Configuration

Environment variables:

- `PI_SESSION_SEARCH_ROOT` — override the sessions directory (default
  `~/.pi/agent/sessions`).
- `PI_SESSION_SEARCH_MAX_BYTES` — per-record raw-byte cap (default 5 MiB,
  5,242,880 bytes). It is enforced before decoding/parsing and excludes the LF
  delimiter. Existing overrides still apply, but revisit old file-size
  overrides: this setting now limits one record's memory use, not whole files.
  Files have no whole-file size ceiling. Oversized records are skipped through
  the next newline, then reading continues. `search_sessions` reports
  `skippedRecords` and `incompleteCoverage`; `read_session` and
  `/find-sessions` show an incomplete-coverage warning.

## How it works

pi stores every session as a JSONL file under
`~/.pi/agent/sessions/<encoded-cwd>/<timestamp>_<uuid>.jsonl`. Each line is a
JSON object — the first is a `session` header (with `id` and `cwd`), the rest
are `message` entries (and a few other types).

`search_sessions` walks that directory, streams each JSONL file, parses
`message` entries, extracts text content (skipping images and, by default, raw
tool args), and matches against your query. It retains only hits and stops at
`maxResults` or cancellation.
The optional `maxResultsPerSession` skips each file's remaining records once its retained-hit cap is reached.
See [Let the LLM drive](#let-the-llm-drive) for result-limit and coverage fields.
Skipped-record counts cover only the portion actually scanned.

For `sessionId`, `read_session` scans the same encoded-cwd directories as search
and reads only each file's first record to find its header ID. Filenames do not
establish identity. Only valid headers within the configured record limit
participate; malformed or oversized headers cannot resolve an ID. If distinct
files have the same ID, the read fails and asks for `sessionFile`. Symlink aliases
of the same resolved file do not create ambiguity. ID lookup adds a header scan
on each call; there is no persistent index or cache.

`read_session` streams a snapshot bounded by the file's initial byte length, so later appends wait until the next call.
It counts eligible messages, selects the requested window, and retains only that window.
Cursor validation checks the consumed prefix without retaining the transcript in memory.
`contextMessages` and `maxMessages` accept non-negative safe integers, including `0` (defaults 6 and 30).
Memory use depends on one bounded record plus retained hits or the requested window, not the transcript's total size.

No model is called. No external network. No session is mutated.

## Trust model & security notes

**This tool is read-only and intended for a single trusted local user.** It
gives the active LLM the ability to grep every prior pi conversation on
disk. That makes it a powerful productivity tool *and* a meaningful
exfiltration primitive if the active LLM is operating on untrusted input.

**Trust boundary.**

- The user owns `~/.pi/agent/sessions/` and trusts its contents.
- The configured sessions root (default: that directory) is the only
  filesystem region this tool will ever read.
- Anything inside the root — user messages, assistant messages, tool calls,
  tool results — is treated as readable by the active model.

**Mitigations actually in place.**

- **Read-only.** No tool here writes, deletes, or transmits anything.
- **Path containment in `read_session`.** Resolves symlinks on both the file
  and the configured root, rejects any path that doesn't end up under the
  resolved root. ID lookup checks containment on every directory and file
  before reading its header, then applies the same path check to the selected
  file. It never rewrites a foreign absolute path to a local path.
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
- **`PI_SESSION_SEARCH_ROOT` accepts any path.** If you set it to a
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
