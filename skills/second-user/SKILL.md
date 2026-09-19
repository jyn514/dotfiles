---
name: second-user
description: Challenge a proposed abstraction, plugin hook, or configurable dimension by separating required variability from justification for reusable machinery. Use during design or implementation when runtime-variable or reusable machinery may be based only on hypothetical future needs.
---

# second-user

## Purpose

Prevent agents from turning required variability or one concrete use into unjustified reusable machinery.

## Inputs

- proposed abstraction, plugin hook, or configurable dimension
- current implementation task and explicit requirements
- repository callers and consumers

Evaluate separately whether variability is required and whether it requires an abstraction or hook.

## Procedure

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
