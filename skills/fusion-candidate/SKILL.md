---
name: fusion-candidate
description: Construct at most one explicit synthesis from compatible, separable parts of existing design candidates, with provenance and composition risks. Use only after cross-critique identifies genuinely composable components; otherwise return no fusion.
---

# fusion-candidate

## Purpose

Construct at most one explicit synthesis candidate from cleanly separable parts of existing candidates.

## Inputs

- fixed candidate set
- `cross-critic` output
- original task and constraints

## Procedure

1. Decide whether a fusion is justified at all. `NO_FUSION` is the normal outcome when components are tightly coupled.
2. If constructing D, name exactly which components are taken from which source candidates.
3. Name which conflicting components are rejected or superseded.
4. Explain why the selected pieces compose without contradictory assumptions.
5. Identify new risks introduced by composition.

## Output

Either:

- `NO_FUSION`, with a short reason;

or candidate D with:

- `sources`: candidate → components taken
- `rejected`: source components not carried forward
- `plan`
- `composition_argument`
- `assumptions`
- `new_risks`

## Constraints

- Never say “combine the best parts.”
- D is just another candidate; it has no privileged status.
- Do not add novel architecture unrelated to source candidates.
- If the composition argument depends on an unverified assumption, say so explicitly.
