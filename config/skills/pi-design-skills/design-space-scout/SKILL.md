---
name: design-space-scout
description: Map a software-design space into up to three viable, materially distinct briefs based on concrete decision axes. Use before detailed planning when a task has genuine architectural alternatives and weak variants should be rejected rather than fabricated.
---

# design-space-scout

## Purpose

Produce three viable, materially distinct design briefs before implementation planning begins. Diversity should come from different underlying decisions, not wording or role-play.

## Inputs

- the design task or question
- explicit user constraints
- relevant repository context
- optional evidence from `pain-axis`

## Procedure

1. Identify the few decisions that actually define the design space: ownership, persistence, synchronization, representation, lifecycle, compatibility, consistency, abstraction boundary, etc.
2. Remove forks only when there is a concrete reason:
   - violates an explicit requirement;
   - internally inconsistent;
   - duplicates another region closely enough to add no useful diversity;
   - strictly dominated on the stated criteria.
3. Produce exactly three briefs, A/B/C, that occupy materially different viable regions.
4. Each brief should be small: key decisions, rationale, important assumptions, and what would make the brief invalid.
5. Record rejected forks and reasons separately.

## Output

For each brief:

- `id`: A | B | C
- `key_decisions`: short list of concrete decisions
- `rationale`: why this region is viable
- `assumptions`: assumptions that matter
- `invalid_if`: evidence that would rule it out
- `why_distinct`: concrete comparison against the other briefs by decision axis

Also return `rejected_forks` with reasons.

## Constraints

- Do not write complete implementation plans.
- Do not invent weak alternatives merely to fill three slots.
- Unconventional is not the same as bad.
- `why_distinct` must name specific differing decisions, not vague style labels.
- If fewer than three genuinely viable regions exist, say so rather than fabricating one.
