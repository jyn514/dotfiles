# Manual compaction replay fixtures

Four cases cover persistent corrections, conditional permission,
investigation-only authority, paused work, and repeated compaction. Offline tests
check **input reconstruction only**, never generated replies or semantic scores.
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
  `/owned/dotfiles`. No private hostnames, credentials, original home paths,
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
