---
name: opportunity-scan
description: Find the highest-leverage project improvement without anchoring on recent changes, current work, churn, or already-completed corrective campaigns. Use for broad codebase improvement, project opportunity scans, and deciding what to work on next; not for designing a solution within an already-selected area.
---

# opportunity-scan

## Purpose

Find high-leverage opportunities across an entire software project without anchoring on whatever was touched most recently.

Use this skill for broad goals such as “make this project better”, “what should I work on next?”, or “find the highest-leverage improvement”. Its job is to choose *where to look*, not to design the solution.

## Core rule

Recent activity is evidence of attention, not evidence of importance.

Do not begin from the latest commits, current diff, open branch, or the subsystem already occupying the parent conversation. First build a coarse map of the project and deliberately search across it.

Do not treat open issues, TODOs, roadmap items, or recent work as the opportunity set. First identify improvements that are not already explicitly tracked. Afterward, consult tracked work to detect overlap, supporting evidence, or neglected known problems.

## Inputs

- broad project-improvement goal
- explicit user constraints or priorities
- repository contents and documentation
- repository history when available
- issue/bug/performance/user evidence when available

## Procedure

### 1. Map the project before ranking opportunities

Construct a coarse subsystem map from sources such as:

- top-level source directories and packages;
- architecture/design documentation;
- public APIs and user-facing commands;
- tests and integration suites;
- build/deployment tooling;
- major runtime components;
- long-lived modules visible in repository history.

Aim for roughly 5–12 meaningful areas. Do not make every directory its own subsystem.

For each area, record only enough to orient later investigation:

- purpose;
- major interfaces or responsibilities;
- whether it is user-facing, infrastructural, or internal;
- rough evidence sources available.

### 2. Neutralize recency bias

Before inspecting recent work in detail, sample evidence across the project and across time.

At minimum:

- inspect history from multiple time windows rather than only HEAD-adjacent commits;
- inspect areas with low recent churn as well as high churn;
- distinguish repeated historical pain from a one-off recent refactor;
- treat the current working area as one candidate area, not the default candidate.

If practical, define a recent window such as the last 30–90 days. Evidence confined to that window should not by itself justify “highest leverage”.

Do not mechanically penalize recent work. A recently touched subsystem may still be the best opportunity when there is independent evidence: repeated historical failures, user pain, known architectural limits, or unfinished high-value work.

### 3. Look for opportunity signals

Search each major area for signals such as:

- recurring bugs or regressions;
- repeated cross-module edits or awkward coupling;
- known performance or scalability limits;
- user-facing limitations or missing capabilities;
- fragile or weakly enforced invariants;
- disproportionately complex interfaces;
- duplicated mechanisms;
- maintenance hotspots that recur over long periods;
- neglected important subsystems with little ownership or test coverage;
- capabilities the architecture makes unnecessarily difficult;
- places where a small change would remove recurring work elsewhere.

Do not equate churn with pain. Churn can mean investment, healthy evolution, generated code, or mechanical migration.

### 4. Verify the current gap

Before shortlisting an area, confirm that the historical pain remains an unfinished opportunity in the current tree.

For each candidate:

- inspect current design documents, implementation, tests, and open work;
- identify the concrete behavior, invariant, capability, or cost that remains unresolved;
- distinguish completed corrective campaigns from active gaps;
- check whether recent changes already removed or materially narrowed the problem;
- name the smallest experiment, reproduction, or audit that would prove the remaining leverage.

Do not shortlist an area on historical recurrence alone.
If the current implementation already enforces the proposed invariant, record it as maintained strength or narrow follow-up work rather than a project-level opportunity.

### 5. Produce a cross-project shortlist

Return 3–5 opportunity areas from distinct subsystems when the evidence supports it.

Each opportunity should state:

- the area;
- the concrete current problem or limitation;
- why it matters;
- evidence supporting it;
- existing design, code, tests, or corrective work;
- why it may be high leverage;
- important uncertainty;
- the cheapest check that could disprove or narrow it;
- whether the evidence is recent-only, recurring, user-facing, architectural, or mechanical.

At least one shortlisted opportunity should come from outside the most recently active subsystem unless there is a concrete reason no such opportunity is competitive.

### 6. Rank cautiously

Rank opportunities only after constructing the shortlist and verifying that each gap remains current.

Prefer, roughly in this order:

1. repeated or independently corroborated user/reliability pain;
2. constraints that block multiple valuable changes;
3. recurring maintenance burden or invariant failures;
4. high-leverage simplification with broad downstream effects;
5. speculative cleanliness or aesthetic improvement.

Do not give recent activity an intrinsic positive score.

If the evidence does not support a clear winner, return a small ranked set rather than manufacturing certainty.

## Output

Use a compact structure like:

```text
project map
- parser: ...
- incremental engine: ...
- build-rule DSL: ...
- watcher: ...
- docs/tooling: ...

opportunities
1. <area>: <current problem>
   evidence: ...
   existing work: ...
   remaining gap: ...
   leverage: ...
   uncertainty: ...
   disproof check: ...
   evidence span: recurring | historical | recent-only | user-facing | ...

2. ...

recent-work check
- most recently active area: <x>
- shortlisted because: <independent evidence> | not shortlisted

recommended next investigation
- <area>
- why this beats the alternatives
```

## Handoff

This skill chooses an opportunity area; it does not choose an architecture.

After selecting an area:

- use `cleanup-triage` when cleanup is the selected opportunity and the work must be prioritized or sliced;
- use `pain-axis` to investigate its historical failure/coupling evidence in depth when useful;
- use `architecture-design` when a bounded subsystem and architectural problem are selected without a genuine design fork;
- use `design-space-scout` when there is a genuine design fork;
- use a smaller local workflow when the opportunity is already concrete and does not require architectural exploration.

## Anti-patterns

Do not:

- start with `git log -10` and infer project priorities from it;
- assume the current conversation topic is the most important project problem;
- rank files/directories by churn and call that leverage;
- treat recent unfinished work as automatically deserving completion;
- treat a completed corrective campaign as an unfinished opportunity because its history contains many fixes;
- search only for architectural problems while ignoring user-facing limitations;
- force every subsystem into the shortlist;
- propose solutions before deciding which problem is worth solving;
- choose an opportunity merely because the model can describe it confidently.
