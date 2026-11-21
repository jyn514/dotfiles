# Replay a compaction

Generating a replay makes a live Luna request and may incur model cost.
It uses the installed Pi's default credential backend through its public model runtime; do not run generation through `dev/test-environment`.
Listing cuts is offline: it creates no model runtime and makes no model request.
Install the [locked dependencies](testing.md#dependencies-and-setup) first.
Generation also requires the normal installed Pi SDK.
The runner resolves `PI_PACKAGE_DIR` when set, otherwise the normal `~/.local/share/pi/node/node_modules/@earendil-works/pi-coding-agent` installation, then `/opt/agent-pi/src/packages/coding-agent` in the guest.
An explicit unusable installation fails; the runner never substitutes the locked SDK's credential backend.

List recorded cuts, including cuts on inactive branches:

```sh
dev/replay-compaction --list-cuts SESSION.jsonl
```

The output is one JSON object per cut, in recorded order, with its ID, timestamp, parent, and first retained entry.
It also reports serialized input characters and whether a previous checkpoint is included.
An unreconstructable boundary is listed with an error instead of hiding that cut.
A session without compactions produces no output.
Listing does not accept a compaction ID, `--instructions`, or `--provider`.

To compare [compaction instruction](../config/pi-agent/pi-extensions/compaction.md) changes against a saved compaction, run:

```sh
dev/replay-compaction SESSION.jsonl [COMPACTION_ID]
dev/replay-compaction --instructions CANDIDATE.md SESSION.jsonl [COMPACTION_ID]
dev/replay-compaction --provider openai-codex --instructions CANDIDATE.md SESSION.jsonl COMPACTION_ID
```

Replay keeps the compaction model ID (`gpt-6-luna`) and chooses the sole configured provider offering it.
It does not inherit the extension's provider pin or copy credentials from another provider.
When more than one configured provider offers that ID, select one with `--provider ID`.
An explicit unavailable provider fails before generation; the runner never substitutes a different model or provider.
The installed runtime resolves the selected provider's existing credentials at request time, as in a normal Pi session.
No credential or auth-file override is passed: this preserves the installed runtime's default backend, including native keychain storage where Pi uses it.
This identifies the normal installed-Pi backend; it does not establish the token identity of a running Pi process.
Run in the environment containing those credentials; if guest tools cannot see host Pi auth, use the normal host command rather than create new guest credentials.
Use the same explicit provider for both sides of a prompt comparison.

By default, the command selects the latest compaction on the session's active branch; an entry ID selects a specific one.
Instructions default to the current production file; `--instructions FILE` supplies its exact UTF-8 text on the same replay path.
It saves `original.md`, `input.txt`, `instructions.md`, and `replay.json` in a private temporary directory.
Once completion returns, it saves `response.json` before checking whether the reply is an acceptable checkpoint.
This diagnostic sidecar contains returned content blocks, usage, stop reason, and any error message; it does not copy request options or credentials.
A returned reply can still be rejected for a provider error, token limit, cancellation, tool call, or missing required heading.
Only an accepted checkpoint produces `new.md` and `usage.json`; an error still exits unsuccessfully and points to the retained directory.
A failure before completion returns leaves no `response.json` and does not establish whether the provider generated a reply.
The session file is never modified; failed requests retain the replay inputs.
Treat returned model content as sensitive when sharing these artifacts.
`replay.json` records source and instruction paths and SHA-256 hashes, the recorded cut, serialized input hash and length, `requestedModel`, and the effective `model` provider/ID.
`model` remains null if selection fails.
After runtime creation, `runtime` records the installed package's real directory, public SDK entrypoint, version, and default-backend selection.
Once the model is selected, it also records the effective token budget, reasoning effort, cache retention, and timeout.
Paths are provenance, not archived source; retain the source session and dependency lock separately if later reproduction matters.

Replay uses the recorded cut point and previous checkpoint, not today's retention settings.
Input reconstruction, authoritative serialization, and the default reserve-token budget use the repository's locked SDK.
Only model catalog, credentials, and provider completion use the installed SDK.
This keeps captured input bytes stable without coupling the locked runtime to a newer credential backend; record both the dependency lock and installed runtime version for comparisons.
Original custom compaction instructions and generation settings are not recorded and cannot be reconstructed.
Caller-added repository status is excluded from the comparison and input when saved checkpoint metadata identifies it.
Older summaries without that metadata remain intact.

## Compare against raw evidence

The replay applies the extension's required-header check to generated output; it does not judge semantic retention.
Use the source-backed [retention cases](../tests/pi/fixtures/compaction-replay/README.md) to compare compaction retention.
They cover persistent corrections, conditional permissions, paused work, investigation-only authority, and repeated compaction.
They also compare accepted evidence versus newer experiments.
The [content-selection cases](../tests/pi/fixtures/compaction-replay/README.md#content-selection) add motivating problems versus implementation progress,
requested versus completed closeouts, corrections with unchanged responsibilities, and complete versus truncated evidence reads.
Their checklists and deliberately wrong decision contrasts require human comparison against source turns, not a score for prose quality.
Offline tests protect those inputs and their boundaries; they do not reject a semantically wrong generated checkpoint.
The saved historical summary is not an oracle for what the source authorized.

Evaluate the summary together with retained messages and recovery pointers.
Judge omissions by their effect on continuation, not by how much history the summary retains.
Before calling an omission a regression, identify the concrete wrong belief, lost obligation, or incorrect next action it would cause.
Omitting completed work or commit details is not itself a failure.

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
Use `replay.json` to check source and input hashes, cut identity, installed runtime, model, and generation settings.
Instruction hashes should differ when testing different prompts; each must match the intended candidate.
Keep model and settings equal for prompt-only comparisons.
Read the replies against the supplied records yourself, preserving adverse results and uncertainty rather than computing a semantic score.
Repeat ambiguous cases; a single favorable generation is not evidence of consistent superiority.
Keep development examples separate from frozen-candidate checks, and distinguish a second cut from the same session from an independent session.

The offline [replay tests](../tests/pi/replay_compaction_test.ts) verify listing, instruction selection, and input reconstruction, not model retention.
They inject the model-registry boundary without requests and check native CLI invocation in isolation.
Provider-selection cases cover automatic selection, explicit selection, ambiguity and unavailable credentials.
A default CLI case resolves a disposable installed-public-SDK fixture and checks that runtime creation receives no credential-backend override; it also checks captured context, settings, runtime provenance, and failure without fallback for an invalid explicit installation.
A separate locked-runtime case reads explicitly supplied disposable credential storage and intercepts completion before any request.
Returned-response cases check diagnostic retention across each rejection path while keeping accepted output files exclusive to validated checkpoints.
Selection, runtime-creation and thrown-request failures leave no completed-response sidecar.
These offline fixtures do not demonstrate live keychain access or model generation.
Run them through the isolated test wrapper:

```sh
dev/test-environment bun test ./tests/pi/replay_compaction_test.ts
```

See the [extension guide](../config/pi-agent/pi-extensions/README.md#compaction) for compaction behavior and instruction updates.
