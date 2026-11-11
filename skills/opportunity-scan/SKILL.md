---
name: opportunity-scan
description: Find the highest-leverage project improvement without anchoring on recent changes, current work, churn, or already-completed corrective campaigns. Use for broad codebase improvement, project opportunity scans, and deciding what to work on next; not for designing a solution within an already-selected area.
---

# Opportunity scan

Choose which project problem is worth investigating next, not how to solve it.
Start from the improvement goal and explicit user constraints and priorities, then compare opportunities across the project.
Recent activity shows where attention went; it does not establish where more attention would help most.

## Map the project, then sample across it

Build a coarse map from the repository's source, documentation, public entrypoints, tests, and build or deployment tooling.
Aim for roughly 5–12 meaningful areas rather than one per directory.
For each, note its purpose, major responsibilities or interfaces, who uses it, and where evidence of its strengths or limits lives.
Choose initial areas from this map rather than the current diff, branch, or conversation.

Before studying recent work in detail, sample each major area for unmet needs or recurring costs.
Follow a user workflow, a failure, or a repeated maintenance task far enough to see what makes it difficult.
Repeated cross-module edits matter when they expose coupling that makes valuable changes expensive, not simply because many files changed.

Where history is available, inspect multiple time windows and both low- and high-churn areas.
Distinguish repeated pain from investment, generated changes, mechanical migrations, or a one-off refactor.
If practical, define a recent window, such as 30–90 days; evidence confined to it should not alone justify “highest leverage”.
The current subsystem remains eligible, but needs independent evidence such as user pain, repeated failures, or an architectural limit.

Form candidates from this investigation before consulting open issues, TODOs, or roadmaps.
Seek improvements beyond explicitly tracked work rather than treating the backlog as the opportunity set.
Then consult tracked work for overlap, corroboration, and neglected known problems.

## Establish what remains unresolved

Before shortlisting a candidate, inspect its current design, implementation, tests, and open work.
Name the behavior, capability, invariant, or cost that remains unresolved, and check whether recent changes removed or narrowed it.
A history of failures can reveal an important problem—or a successful corrective campaign.
If the current tree already enforces the proposed invariant, treat that as a maintained strength or a narrower follow-up, not a project-level opportunity.

Suppose parser history contains repeated invalid-state bugs, while a quiet watcher subsystem appears to miss updates after reconnecting.
Current parser types and tests now exclude the old failures: the history explains an improvement already made.
The watcher remains a candidate if its current reconnect path leaves changes unseen.
A small reconnect reproduction could confirm or disprove that gap before a wider audit.
Keep unverified behavior explicit rather than reporting a suspected failure as fact.

For each surviving candidate, identify the cheapest reproduction, experiment, or audit that could disprove or narrow its claimed value.

## Compare current opportunities

Build a shortlist of 3–5 areas from distinct subsystems when the evidence supports it.
Include at least one outside the most recently active subsystem unless there is a concrete reason none is competitive.
Rank only after checking that each gap remains current.

Prefer, roughly in this order:

1. Repeated or independently corroborated user or reliability pain.
2. Constraints that block multiple valuable changes.
3. Recurring maintenance burden or invariant failures.
4. Simplification with broad downstream effects.
5. Speculative cleanliness or aesthetic improvement.

Compare the consequences, not just the categories.
If watcher users repeatedly restart to recover updates, that investigation may beat simplifying a build-rule interface with no demonstrated cost.
If the interface instead blocks several needed capabilities, compare those gains with the watcher's recovery burden.
The rough preference order guides that judgment; the project's priorities and evidence decide it.
Recent work earns neither an automatic promotion nor a penalty.
If the evidence does not support a clear winner, return a small ranked set rather than manufacturing certainty.

## Report the choice and next investigation

Show the coarse project map, then give each shortlisted area enough evidence to judge:

- The concrete current gap and why it matters.
- Supporting sources and their span: recent-only or recurring, observed user pain or an inferred architectural limitation.
- Existing design, code, tests, and corrective or tracked work, distinguishing what they solve from what remains.
- The expected leverage, material uncertainty, and cheapest check that could disprove or narrow it.

Identify the most recently active area and explain its inclusion or exclusion using independent evidence.
Recommend the next investigation and say why it beats the alternatives.

After selection, use `cleanup-triage` to prioritize or break down cleanup work, or `pain-axis` when deeper historical failure or coupling analysis is useful.
Use `architecture-design` for a selected bounded architectural problem; its optional alternatives reference covers genuine design forks.
Use a smaller local workflow when the opportunity is already concrete and needs no architectural exploration.
