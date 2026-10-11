# Manual compaction replay fixtures

Five cases cover persistent corrections, conditional permission,
investigation-only authority, paused work, repeated compaction, and accepted evidence versus newer experiments.
Offline tests check **input reconstruction only**, never generated replies or semantic scores.
Passing them does not prove model retention.

## Use and reconstruction limits

Follow [replay prerequisites and usage](../../../../dev/README.md#replay-a-compaction).
**Live replays may cost money.** From the repository root, for example:

```sh
dev/replay-compaction tests/pi/fixtures/compaction-replay/paused-repeated-compaction.jsonl bf746f62
dev/replay-compaction tests/pi/fixtures/compaction-replay/paused-repeated-compaction.jsonl e0fbef33
```

Inspect `input.txt`, then personally compare `original.md` and `new.md` with the checklists
below. The second replay inherits saved historical prose, not the first replay's
new reply; this is not a multigeneration harness.

These are **reconstructed sessions containing historical excerpts**, not faithful
exports or complete original model inputs:

- Text comes from raw local Pi records. Checkpoints are fallible historical
  excerpts, not ideal answers; subsequent user corrections take precedence.
- IDs/dates remain; parent chains, cut points, and `checkpointLength` are rebuilt.
  `tokensBefore` is original metadata, not minimized size. Omitted context/tools
  and caller status are absent. Synthetic `fixture-retained-suffix` boundaries
  are excluded from replay input and never historical evidence.
- Header cwd becomes `/owned`; selected `/src/dotfiles` references become
  `/owned/dotfiles`, and selected Cocoa receipt roots become `/owned/cocoa`.
  No private hostnames, credentials, original home paths,
  tool signatures, caller snapshots, or unrelated inventories are retained.
- Provenance lists session basenames and **entry dates**, which can differ from
  filenames after inheritance. Checklists below are for humans, not reply oracles.

## Persistent corrections

`persistent-corrections.jsonl`; target `42d6f5af`.
Source: `2026-10-02T11-17-47-876Z_01a0fc55-aae3-75db-9797-253fa5bfd8f9.jsonl`.
Selected entries: **October 2, 2026**.

Raw users: `21a7e1e6` (generate/compare), `09e2bfc0` (blind generation),
`2bdb5ba5` (personal judgment, no evaluation criteria). Checkpoint `42d6f5af`
keeps `## Goal` only; it omitted those corrections. Terminal cut is synthetic,
not the original split-turn boundary.

- [ ] Blind generation uses preceding raw history and instructions, not the
  target summary or later critique. Comparing afterward remains permitted.
- [ ] Personal judgment replaces the rejected evaluation-criteria/harness method.
- [ ] These corrections remain active for subsequent comparison work.

## Conditional permission

`conditional-permission.jsonl`; target `20e73b8a`.
Source: `2026-09-27T20-26-59-513Z_54dddf89-ceba-4a4b-9651-cf2381d3a102.jsonl`.

**September 27, 2026:** custom entry `a187991a` (`pi-codex-goal`,
`source: "command"`) stores the user's objective. Continuation `d4023c66` contains
the identical objective, explicitly labeled user-provided data. The fixture keeps
its excerpt from “The objective below” through `</untrusted_objective>`, excluding
budget/runtime instructions. This is **command-origin user authority**, not an
ordinary user turn or assistant-invented permission.
**September 28, 2026:** raw user `60925648` adds the concurrent-editor check;
checkpoint `20e73b8a` keeps goal/constraints before `## Progress`. Terminal cut is
synthetic; the original permission is supplied directly, not via a checkpoint.

- [ ] Product requirements/brief remain protected. A failed implemented
  feasibility check permits implementation-spec blocker edits; distinguish
  requirements-authorized edits from those needing product review.
- [ ] Record unspecified choices as TODOs and continue independent work. **Only
  when none remains without a product decision:** commit existing work, make a
  reasonable choice, document it as needing product review, then implement it.
  Neither erase that permission nor authorize choosing prematurely.
- [ ] Check for uncommitted spec changes before editing; preserve concurrent work.

## Investigation-only authority

`investigation-only.jsonl`; target `bc29caa4`.
Source: `2026-10-03T16-59-32-100Z_4642d2ea-83d5-4520-93ce-0977aa6509e6.jsonl`.
Selected entries: **October 3, 2026**.

Raw users: `a5a54061`, `1aeee1ee` (sandbox/design), `9d45d288` (Discord token),
`e653a86f` (persistent clone), `dda5eb73` (investigate), `1e7b65b1` (keep model
proxy), `e36b2202` (Compose question). Checkpoint `bc29caa4` keeps objective and
corrections before `## Open obligations`; its proxy-replacement advice is stale
against `1e7b65b1`. Terminal cut is synthetic.

- [ ] Investigation/design only; no implementation or final-design approval.
- [ ] Keep the model proxy; reject the in-process proxy rebuild and stale advice.
- [ ] Persistent clone and dedicated Discord token are accepted simplifications,
  not arbitrary host-credential approval. Compose versus codex-sandbox stays open.

## Paused work and repeated compaction

`paused-repeated-compaction.jsonl`; cuts `8e424df8`, `bf746f62`, `e0fbef33` (default).
Source: `2026-10-04T07-11-47-074Z_c6cd4fe7-5b36-4388-a8e5-d8df881a285c.jsonl`.
Selected entries: **October 4, 2026**.

Raw users: `e634a3a7` (arbitrary history), `fe8d8328` (reconsider owner/host Pi;
path sanitized), `8fcc42a9` (reuse container), `e107e5b3` (JJ routing), `b356d8c4`
(plan), `13d3d1a6` (review), `c2e50056` (fix), `5450e6f4` (implement).
Checkpoint excerpts and reconstructed cuts:

- `8e424df8`: objective, corrections, paused status, obligations before
  `## State and evidence`; retained boundary `e107e5b3`.
- `bf746f62`: same sections plus first state paragraph naming JJ plan review;
  path sanitized; retained boundary `c2e50056`.
- `e0fbef33`: objective and single obligation excluding replay from JJ work;
  other bullets omitted; synthetic terminal boundary.

Second input: `8e424df8` + `e107e5b3`, `b356d8c4`, `13d3d1a6`.
Third input: `bf746f62` + `c2e50056`, `5450e6f4`. Older raw corrections survive
only through a **historical checkpoint excerpt, not a mocked successful reply**.
“Paused” is checkpoint interpretation supported by reconsideration turns, not an
explicit user quote saying “paused.”

- [ ] Arbitrary-history replay stays unresolved/paused; do not resume the rejected
  current-tool-call-only `fork_context` draft.
- [ ] Reuse the guest container and preserve trusted host authority; do not assume
  subagent-manager ownership.
- [ ] JJ is separate: native for container-local repos, proxy for host-backed
  metadata, without a privilege increase.
- [ ] `bf746f62`: review/repair is not implementation approval. `e0fbef33`:
  “implement” authorizes JJ only, not paused replay.
- [ ] Preserve inherited boundaries when older raw turns are absent; offline
  reconstruction cannot prove a model will do so.

## Accepted evidence versus newer experiments

`accepted-evidence-newer-experiment.jsonl`; target `28049f46`.
Sources:

- `2026-10-08T12-16-19-448Z_ed87440e-3ee5-4ccc-b4ed-6ea7e8711a8e.jsonl`:
  October 11, 2026 verification call/result `7d6df789` / `ba80c489`, accepted-baseline notification `8cd7ccab` / `eff1d5ec`,
  local-batch wait/return `31aabd25` / `88d50317`, and namespace assignment/launch `7302c45d` / `9e9d6a59`.
  The later worker return `4a89ef6a` is dated **12:30:49 UTC**, after the selected cut.
- `2026-10-11T12-11-23-772Z_01a12adf-f8fb-7595-88d4-851266184a21.jsonl`:
  raw user `f61255c5`, **12:13:22 UTC**, requests compaction-instruction suggestions.
- `2026-10-11T12-15-42-187Z_263638f2-5f5f-4cec-9200-04f94f8e2984.jsonl`:
  checkpoint `28049f46`, **12:21:20 UTC**, supplies historical objective and accepted/newer-evidence excerpts.

The verification command's machine-local interpreter is replaced with `[interpreter omitted]`.
The local worker's recorded `finalResponse` is extracted from its callback envelope; its candidate-outline table is omitted.
The namespace assignment retains the batch, baseline, and ownership excerpts, omitting intervening word-specific holds.
These reductions keep the pending integration checks visible within SDK tool-result serialization limits.
Original callback signatures, thinking blocks, caller status, unrelated records, and checkpoint sections are excluded.
The terminal boundary is synthetic, and the parent chain is rebuilt across the selected source records.
The real later worker return remains after the checkpoint so reconstruction must exclude it, not reinterpret it as boundary evidence.
This is not a faithful session export or a test of the omitted dictionary decisions.

Replay with:

```sh
dev/replay-compaction tests/pi/fixtures/compaction-replay/accepted-evidence-newer-experiment.jsonl 28049f46
```

Compare the generated checkpoint with `input.txt`, not just the saved checkpoint excerpt:

- [ ] The resume map identifies `target/research/ordinary-gap-parent-acceptance-v1/results.json` as accepted provisional evidence,
      not merely an older experiment, and states what to recover from it.
- [ ] The accepted stack remains **100,775 bindings**, adding only freeway/riddle at this stage.
      “Accepted” means provisional integration, not adoption, installation, publication, licensing, or curriculum approval.
- [ ] `target/research/ordinary-gap-followup-v2-complete/` is newer **local-only** research.
      Its 138 source proofs and 13 proposed keys do not establish namespace, native/public, or parent acceptance.
      The map retains a recoverable batch pointer with this status, rather than promoting it to the accepted stack.
- [ ] `/ordinary-gap-batch-namespace` is pending at the cut and owns a **new** namespace producer and fresh conditional outputs.
      Check its outcome before retrying; do not claim completion from the later return excluded from `input.txt`.
- [ ] The latest user request authorizes **suggestions**, not prompt edits or resumed dictionary implementation.
      Dictionary work is background to that request, without erasing the pending worker or integration obligations.
- [ ] The checkpoint distinguishes verified parent results from worker reports and retains the approval limits.
      Offline assertions protect the supplied input and cut, not these generated-output judgments.
