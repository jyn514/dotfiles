# Convert a Codex conversation to Pi

[`codex-to-pi`](../../bin/codex-to-pi) converts a Codex session ID, JSONL path, or ChatGPT share URL to Pi v3 JSONL.

It requires Python 3; local history conversion also requires Babashka (`bb`) on PATH.
Session-ID conversion additionally requires Node and an installed Codex with `thread/turns/list` support.
Share URLs require network access and the [share-page extractor](../extract-chat-share/README.md).
Conversion writes a new Pi session file; it does not resume a session or replay tools.

```sh
codex-to-pi SESSION_ID -o conversation.jsonl
codex-to-pi SESSION_ID --branches -o branches.jsonl
```

Choose an output path that is safe to replace.

## Message selection

Session-ID conversion uses the same [history reader](../../libexec/chat-history.clj) as `extract-chat`.
It starts an owned Codex app-server, reads thread metadata, and pages full turn items in conversation order without resuming the thread or starting a turn.
Both active and archived sessions use Codex's displayed conversation, which can differ from its retained model context after imports or compaction.
User and assistant text, repeated occurrences, and assistant phases are preserved; tools and other non-message items are omitted.
Unsupported user content or unknown history item types fail before writing the destination.
Recorded turn times are used when available; these are not original per-message timestamps.

Explicit file paths and `--branches` retain the offline rollout reader, including ancestor cutoffs and superseded rollouts that the ID-based API cannot select.
Directory scans in `extract-chat` also remain offline.
The offline reader omits injected skill instructions while preserving skill invocations and discussion.
An API failure does not silently fall back to parsing message records.

## Output and path options

Use `codex-to-pi SESSION -o FILE` to choose the destination; otherwise it writes to Pi's session directory.
`--archived` searches archived sessions; `--normalize` rewrites macOS paths for sandbox sessions.

## Import a conversation tree

`codex-to-pi SESSION --branches -o FILE` imports related forks and superseded rollouts into one Pi tree; use `/tree` to navigate it.
Discovery includes active and archived history, ancestors, sibling forks, and descendants, while excluding spawned subagent sessions.
Branch endpoints carry Codex thread and rollout labels, and the requested rollout is selected when Pi opens the file.
Shared source records appear once; repeated messages from different records remain distinct.
Branch import requires local paginated history and all referenced ancestors; legacy sessions and share URLs are rejected.
Without `--branches`, conversion and Markdown extraction follow only the selected thread.
