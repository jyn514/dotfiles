---
name: cross-critic
description: Compare independently generated design plans without choosing, rewriting, or prematurely merging them. Use to expose strengths, assumptions, omissions, incompatibilities, missing design regions, and potentially composable parts before final review.
---

# cross-critic

## Purpose

Compare a fixed set of independently generated plans without collapsing them into one design too early.

## Inputs

- original task and constraints
- candidate plans A/B/C
- optional repository evidence
- scout rejected forks, shown only after the first independent comparison pass

## Procedure

First pass, without scout rejections:

1. Identify each candidate's unique strengths.
2. Identify unsupported assumptions, hidden costs, missing requirements, and likely failure modes.
3. Distinguish real architectural differences from cosmetic ones.
4. Identify any important design region apparently missing from all candidates.
5. Identify components that seem cleanly separable and potentially composable, but do not synthesize yet.

Second pass, after seeing scout rejections:

6. Review rejected forks skeptically; do not assume the scout was correct.
7. Call out any rejection that looks premature or any missing region that should be reconsidered.

## Output

- per-candidate strengths
- per-candidate problems
- decisive comparisons
- missing design regions
- potentially composable components
- missing evidence that could change the ranking
- scout rejections worth reopening

## Constraints

- Do not choose a winner.
- Do not rewrite the candidates.
- Do not create a fusion plan; leave that to `fusion-candidate`.
- Treat candidate ordering and verbosity as irrelevant.
