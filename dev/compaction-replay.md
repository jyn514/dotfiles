# Replay a compaction

A replay makes a live Luna request and may incur model cost.
It uses normal Pi authentication or the sandbox model broker; do not run it through `dev/test-environment`.
Install the [locked dependencies](README.md#testing-and-probes) first.

To compare [compaction instruction](../config/pi-agent/pi-extensions/compaction.md) changes against a saved compaction, run:

```sh
dev/replay-compaction SESSION.jsonl [COMPACTION_ID]
```

By default, the command selects the latest compaction on the session's active branch; an entry ID selects a specific one.
It saves `original.md`, `new.md`, the input and instructions, and token usage in a private temporary directory for manual comparison.
The session file is never modified; failed requests retain the replay inputs.

Replay uses the recorded cut point and previous checkpoint, not today's retention settings.
It uses current instructions, SDK serialization, and the default model budget.
Original custom compaction instructions and generation settings are not recorded and cannot be reconstructed.
Caller-added repository status is excluded from the comparison and input when saved checkpoint metadata identifies it.
Older summaries without that metadata remain intact.

The replay applies the extension's required-header check to generated output; it does not judge semantic retention.
Use the source-backed [retention cases](../tests/pi/fixtures/compaction-replay/README.md) to compare compaction retention.
They cover persistent corrections, conditional permissions, paused work, investigation-only authority, and repeated compaction.
They also compare accepted evidence versus newer experiments.
Their checklists require human comparison against recorded source turns, not a score for prose quality.
Before using replay results to tune instructions, compare `input.txt` with the recorded source history.
For reconstructed fixtures, retain the proposals, reports, corrections, and acknowledgments needed to establish what each statement refers to.
Keep their speakers and order.
If a judgment depends on omitted context, repair the fixture and rerun the comparison; do not count the old output as a retention failure.
Add input-reconstruction regression coverage for that context, not an expected model reply.

The offline [replay tests](../tests/pi/replay_compaction_test.ts) verify input reconstruction, not model retention.
Run them through the isolated test wrapper:

```sh
dev/test-environment bun test tests/pi/replay_compaction_test.ts
```

See the [extension guide](../config/pi-agent/pi-extensions/README.md#compaction) for compaction behavior and instruction updates.
