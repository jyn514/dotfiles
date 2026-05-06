# pi-session-search

A [pi-coding-agent](https://github.com/mariozechner/pi) extension that lets the
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
  `sessionCwd`, `timestamp`, `role`, and a snippet.
- **Tool `read_session`** — read a window around a specific hit (or the start
  of a session). Use after a promising `search_sessions` result to pull more
  context without resuming the session.
- **Command `/find-sessions [flags] <query>`** — manual search from the TUI.
  Flags: `--cwd=substr`, `--role=user|assistant`, `--since=ISO`, `--max=N`.
  Results are printed into the current session as a custom message.

The current session is excluded from results by default (you can override per
tool call). Read-only — never modifies session files.

## Prerequisites

[pi-coding-agent](https://github.com/mariozechner/pi) installed and working.
That's it. No API keys, no extra services.

## Installation

### Option A — clone into your pi extensions directory

```bash
mkdir -p ~/.pi/agent/extensions
cd ~/.pi/agent/extensions
git clone https://github.com/<your-fork>/pi-session-search.git
```

Then `/reload` in pi (or restart). The tools and command will appear.

### Option B — symlink from anywhere

```bash
git clone https://github.com/<your-fork>/pi-session-search.git ~/code/pi-session-search
ln -s ~/code/pi-session-search ~/.pi/agent/extensions/pi-session-search
```

### Option C — one-off

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

## Configuration

Environment variables:

- `PI_SESSION_SEARCH_ROOT` — override the sessions directory (default
  `~/.pi/agent/sessions`).
- `PI_SESSION_SEARCH_MAX_BYTES` — per-file size cap to keep search snappy
  (default 5 MB; oversized files are reported as `skippedFiles`).

## How it works

pi stores every session as a JSONL file under
`~/.pi/agent/sessions/<encoded-cwd>/<timestamp>_<uuid>.jsonl`. Each line is a
JSON object — the first is a `session` header (with `id` and `cwd`), the rest
are `message` entries (and a few other types).

`search_sessions` walks that directory, streams each JSONL file, parses
`message` entries, extracts text content (skipping images and, by default, raw
tool args), and matches against your query. `read_session` parses one file and
emits a Markdown-formatted window centered on a target timestamp.

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
  resolved root, and stat-caps the file size at
  `PI_SESSION_SEARCH_MAX_BYTES` (default 5 MB) so a pathological session
  file can't OOM the pi process.
- **Path containment in `search_sessions`.** Per-subdirectory and per-file
  symlink containment: a `.jsonl` symlinked outside the root is detected at
  `realpath` time and skipped (counted as `skippedFiles` in the result).
- **`maxResults` is bounded.** The schema enforces `[1, 1000]`; the runtime
  re-clamps any out-of-range value (including `0`, negative, NaN, Infinity)
  to the default of 20.
- **Regex flag stripping.** The `/.../flags` form respects user flags
  (including case-sensitivity) **except** `g` and `y`, which are stripped
  because they break match-position bookkeeping (`g` removes `.index`, `y`
  is stateful via `lastIndex`).
- **Per-haystack byte cap.** Each message's text is capped to 256 KB
  before regex matching. Bounds best-case ReDoS but does **not** bound a
  truly catastrophic regex within those 256 KB.

**Accepted risks / things the threat model doesn't try to defend against.**

- **Same-user filesystem attacker.** TOCTOU between the symlink check and
  the `readFile` is theoretically exploitable but the threat model assumes
  the user controls their own home directory.
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
