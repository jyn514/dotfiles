# Replay a compaction

Generating a replay makes a live Luna request and may incur model cost.
It uses normal Pi authentication or the sandbox model broker; do not run generation through `dev/test-environment`.
Listing cuts is offline: it creates no model runtime and makes no model request.
Install the [locked dependencies](README.md#testing-and-probes) first.

List recorded cuts, including cuts on inactive branches:

```sh
dev/replay-compaction --list-cuts SESSION.jsonl
```

The output is one JSON object per cut, in recorded order, with its ID, timestamp, parent, and first retained entry.
It also reports serialized input characters and whether a previous checkpoint is included.
An unreconstructable boundary is listed with an error instead of hiding that cut.
A session without compactions produces no output.
Listing does not accept a compaction ID or `--instructions`.

To compare [compaction instruction](../config/pi-agent/pi-extensions/compaction.md) changes against a saved compaction, run:

```sh
dev/replay-compaction SESSION.jsonl [COMPACTION_ID]
dev/replay-compaction --instructions CANDIDATE.md SESSION.jsonl [COMPACTION_ID]
```

By default, the command selects the latest compaction on the session's active branch; an entry ID selects a specific one.
Instructions default to the current production file; `--instructions FILE` supplies its exact UTF-8 text on the same replay path.
It saves `original.md`, `new.md`, `input.txt`, `instructions.md`, `usage.json`, and `replay.json` in a private temporary directory.
The session file is never modified; failed requests retain the replay inputs.
`replay.json` records source and instruction paths and SHA-256 hashes, the recorded cut, serialized input hash and length, and model identity.
Once the model is selected, it also records the effective token budget, reasoning effort, cache retention, and timeout.
Paths are provenance, not archived source; retain the source session and dependency lock separately if later reproduction matters.

Replay uses the recorded cut point and previous checkpoint, not today's retention settings.
It uses the SDK's authoritative serialization and the default model budget.
Original custom compaction instructions and generation settings are not recorded and cannot be reconstructed.
Caller-added repository status is excluded from the comparison and input when saved checkpoint metadata identifies it.
Older summaries without that metadata remain intact.

## Compare against raw evidence

The replay applies the extension's required-header check to generated output; it does not judge semantic retention.
Use the source-backed [retention cases](../tests/pi/fixtures/compaction-replay/README.md) to compare compaction retention.
They cover persistent corrections, conditional permissions, paused work, investigation-only authority, and repeated compaction.
They also compare accepted evidence versus newer experiments.
Their checklists require human comparison against recorded source turns, not a score for prose quality.
The saved historical summary is not an oracle for what the source authorized.

Before using replay results to tune instructions, compare `input.txt` with the raw session history at the recorded cut.
The current SDK's compaction `utils.ts` serializer keeps only the first 2000 characters of each tool result, then adds a truncation marker.
It does not retain the tail; an authority clause or worker result later in a long tool output may never reach the replay model.
Keep this SDK behavior rather than replacing the serializer, and distinguish absent model-visible evidence from a retention failure.
Later turns outside the cut also cannot support a judgment about that reply.

For reconstructed fixtures, retain the proposals, reports, corrections, and acknowledgments needed to establish what each statement refers to.
Keep their speakers and order.
If a judgment depends on omitted context, repair the fixture and rerun the comparison; do not count the old output as a retention failure.
Add input-reconstruction regression coverage for that context, not an expected model reply.
Reconstructed excerpts, actual long-session cuts, and subsequent execution are different evidence classes.
An inspected replay does not establish reliable behavior in untested sessions or subsequent execution.

## Compare candidate instructions

Freeze each candidate before generation and use `--instructions`, not a copied runner or edits to the production prompt.
Replay the same source session and explicit cut for both baseline and candidate.
Check that paired `input.txt` files match byte-for-byte, and that each captured `instructions.md` matches its corresponding frozen file.
Use `replay.json` to check source and input hashes, cut identity, model, and generation settings.
Instruction hashes should differ when testing different prompts; each must match the intended candidate.
Keep model and settings equal for prompt-only comparisons.
Read the replies against the supplied records yourself, preserving adverse results and uncertainty rather than computing a semantic score.
Repeat ambiguous cases; a single favorable generation is not evidence of consistent superiority.
Keep development examples separate from frozen-candidate checks, and distinguish a second cut from the same session from an independent session.

The offline [replay tests](../tests/pi/replay_compaction_test.ts) verify listing, instruction selection, and input reconstruction, not model retention.
They inject the model-registry boundary without requests and check native CLI invocation in isolation.
Run them through the isolated test wrapper:

```sh
dev/test-environment bun test tests/pi/replay_compaction_test.ts
```

See the [extension guide](../config/pi-agent/pi-extensions/README.md#compaction) for compaction behavior and instruction updates.
