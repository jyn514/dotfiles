---
name: second-user
description: Establish concrete justification before adding a mechanism for hypothetical needs or reusable machinery whose consumers or constraints are unclear. Use for proposed abstractions, plugin hooks, configurable policy, automation, safeguards, workflows, or supporting artifacts that may exceed the current task. Do not load for ordinary local implementation or reuse whose independent consumers and shared invariant are already established.
---

# second-user

## Purpose

Own the complexity justification check: a mechanism needs a current requirement, independent consumer, reproduced failure, or pre-existing hard constraint. “Might be useful later” is insufficient.
This skill establishes necessity; the shared instructions' Decisions and authorization rule owns approval when the mechanism expands scope.

## Inputs

- proposed mechanism and the concrete problem it claims to solve
- current implementation task and explicit requirements
- repository callers and consumers

For reusable machinery, evaluate separately whether variability is required and whether it requires an abstraction or hook.

## Procedure

For a speculative mechanism, identify the current requirement, reproduced failure, or hard constraint that needs it. If none exists, defer it and stop. If the justification needs no reusable machinery or configurable policy, report the smallest direct solution and stop. Otherwise, continue below.

1. Identify the first concrete consumer: the current use.
2. State exactly what must vary and what related behavior can remain fixed.
3. Decide whether each variable dimension is required by the task, compatibility, or another repository constraint. Defer variability without such evidence.
4. Independently evaluate the proposed implementation mechanism. Search for a second pre-existing or independently mandated consumer with materially shared behavior.
5. If no independent second consumer exists, challenge the mechanism:
   - can the required variability remain concrete or local?
   - what actual duplication would exist without the abstraction?
   - does a separate hard constraint require the abstraction or hook?
6. Keep reusable machinery without a second consumer only when that constraint requires it; state the constraint.

## Output

For the early stop above, report the mechanism, its evidence or missing justification, and the decision to keep or defer it. Use the remaining fields only for reusable machinery or configurable policy.

- `KEEP_VARIABILITY` or `DEFER_VARIABILITY`
- required variable dimensions and their evidence
- behavior that remains deliberately fixed
- `KEEP_ABSTRACTION` or `DEFER_ABSTRACTION`
- first consumer
- independent second consumer, if any
- materially shared behavior
- separate hard constraint, if that justifies the abstraction

## Constraints

- “might be useful later” is not a second user.
- Multiple possible values are not multiple consumers.
- A consumer introduced only by the proposed design is not independent evidence.
- A second consumer justifies only the narrowest mechanism required by the materially shared behavior.
- A hard constraint must be pre-existing or independently mandated, cite its authoritative source, and not arise from the proposed mechanism.
- Required variability does not by itself justify a reusable implementation mechanism.
- One required configurable input does not justify making adjacent policy configurable.
- Two syntactically similar call sites are not enough if their semantics differ.
- Do not force duplication when a real shared invariant already exists.

## Routing examples

- Load: a retry service proposed for a command that has no observed transient failure; a plugin hook justified by a possible future backend.
- Do not load: a local condition required by the current task; extracting two existing callers that must obey the same established invariant.
