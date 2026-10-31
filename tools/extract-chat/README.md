# Export readable agent conversations

[`extract-chat`](../../bin/extract-chat) extracts user and assistant turns from local Pi, Codex, or Claude JSON/JSONL sessions.
It supports session lookup, `--final-only`, and per-session Markdown.

Use it to read a local conversation without resuming an agent.
It requires Babashka (`bb`); native HTML exports also require Pi on PATH, and Codex branch exports require Python 3.
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

`--session ID` selects the newest matching Codex rollout by filename timestamp and rollout UUID, including replacement rollouts created by revert.
Session lookup prefers Codex sources over imported Pi copies with the same ID, falling back to Pi when no Codex source matches.
A bare session UUID also implies `--session`, so `extract-chat ID --branches --native` works directly.
Existing paths take precedence over UUID lookup, and positional UUIDs can be mixed with file or directory inputs.
With `--extract-dir`, output names retain the source basename with `.md` or `.html`.
Distinct sources targeting the same destination, including `.json`/`.jsonl` stem collisions, fail the whole batch before any exports or native calls.
Existing exports can still be replaced by rerunning a single source or a noncolliding batch.

## Codex ancestry and message selection

Codex exports follow `history_base` references through active and archived rollouts, including inherited fork history only up to the saved byte and ordinal cutoffs.
References use physical rollout IDs, so later parent edits and reverted turns stay out of the selected history.
Explicit file paths export that rollout's history; copied histories need their ancestor files alongside them or in the configured Codex home.
Missing ancestors, reference cycles, and invalid cutoffs fail instead of producing a partial transcript.
Markdown exports omit standalone injected `<skill>` instruction blocks; skill invocations and discussion remain visible.

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
