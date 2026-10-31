# Convert a Codex conversation to Pi

[`codex-to-pi`](../../bin/codex-to-pi) converts a Codex session ID, JSONL path, or ChatGPT share URL to Pi v3 JSONL.

It requires Python 3; local history conversion also requires Babashka (`bb`) on PATH.
Share URLs require network access and the [share-page extractor](../extract-chat-share/README.md).
Conversion writes a new Pi session file; it does not resume a session or replay tools.

```sh
codex-to-pi SESSION_ID -o conversation.jsonl
codex-to-pi SESSION_ID --branches -o branches.jsonl
```

Choose an output path that is safe to replace.

## Message selection

Local conversion uses the same read-only [history reader](../../libexec/chat-history.clj) as `extract-chat` and requires `bb` on PATH.
It also omits injected skill instructions while preserving skill invocations and discussion.

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
