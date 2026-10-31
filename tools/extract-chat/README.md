# Export readable agent conversations

[`extract-chat`](../../bin/extract-chat) extracts user and assistant turns from local Pi, Codex, or Claude JSON/JSONL sessions.
It supports session lookup, `--final-only`, and per-session Markdown.

Use it to read a local conversation without resuming an agent.
It requires Babashka (`bb`); native HTML exports also require Pi on PATH, and Codex branch exports require Python 3.
Codex session-ID exports additionally require Node and an installed Codex with `thread/turns/list` support.
With no paths, it scans `~/.codex/sessions`, or the corresponding directory under `CODEX_HOME`.
Exports can contain private conversations.
Writing an existing export path replaces it.

```sh
extract-chat --session SESSION_ID
extract-chat --final-only path/to/session.jsonl
extract-chat --extract-dir exports path/to/sessions
extract-chat --branches --native --extract-dir exports SESSION_ID
```

## Input selection and output files

`--session ID` finds the current Codex rollout and reads its displayed conversation through Codex's history API.
The API result must select that same rollout; a mismatch fails instead of exporting another history.
Session lookup prefers Codex sources over imported Pi copies with the same ID, falling back to Pi when no Codex source matches.
A bare session UUID also implies `--session`, so `extract-chat ID --branches --native` works directly.
Existing paths take precedence over UUID lookup, and positional UUIDs can be mixed with file or directory inputs.
With `--extract-dir`, output names retain the source basename with `.md` or `.html`.
Distinct sources targeting the same destination, including `.json`/`.jsonl` stem collisions, fail the whole batch before any exports or native calls.
Existing exports can still be replaced by rerunning a single source or a noncolliding batch.

## Codex ancestry and message selection

Session IDs use an owned app-server's `thread/read` and paginated `thread/turns/list` calls without resuming the thread or starting a turn.
Codex supplies conversation order, inherited history, user/assistant text, and assistant phases for active and archived sessions.
Tools and other known non-message items are omitted; unsupported user content, unknown item types, and incomplete pagination fail before writing exports.
The displayed transcript can differ from retained model context after imports or compaction.
API errors do not silently fall back to the offline reader.

Explicit files, directory scans, and `--branches` retain the offline reader for copies and superseded rollouts that the API cannot select by ID.
These exports follow `history_base` references through active and archived rollouts, including inherited fork history only up to the saved byte and ordinal cutoffs.
References use physical rollout IDs, so later parent edits and reverted turns stay out of the selected history.
Explicit file paths export that rollout's history; copied histories need their ancestor files alongside them or in the configured Codex home.
Missing ancestors, reference cycles, and invalid cutoffs fail instead of producing a partial transcript.
Offline Markdown exports omit standalone injected `<skill>` instruction blocks; skill invocations and discussion remain visible.

## Native HTML exports

For Pi, `--native` uses `pi --export` to produce HTML (`pi` must be on PATH); other formats remain Markdown.
Native Pi exports include the full session regardless of `--final-only`; without `--extract-dir`, Pi writes to the current directory.
For Codex, `extract-chat --session ID --branches --native` uses `codex-to-pi --branches` and Pi's native exporter to produce a navigable HTML conversation tree.
This requires Python and Pi on PATH and local paginated Codex history; `--branches` requires `--native`.
Codex HTML uses the source rollout's basename with `.html` in `--extract-dir` or the current directory; temporary Pi sessions are removed after success or failure.
Native Codex exports use the converter's user/assistant message selection and ignore `--final-only`.

## Pi metadata and empty scans

Pi Markdown includes saved goal status, objective, and token budget; provider/model switches and assistant or shell cancellations appear in session order, and partial replies remain visible.
These events remain with `--final-only`; goal usage counters and continuation prompts are omitted.
Empty file/directory scans report the searched source paths on stderr and exit 0, without creating or removing export files.
