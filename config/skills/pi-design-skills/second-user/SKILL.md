---
name: second-user
description: Challenge a proposed abstraction by requiring a second concrete consumer or another hard constraint that justifies generalization. Use during design or implementation when reusable machinery may be based only on hypothetical future needs.
---

# second-user

## Purpose

Prevent agents from introducing abstractions justified only by hypothetical future reuse.

## Inputs

- proposed abstraction or generalization
- current implementation task
- repository callers/consumers

## Procedure

1. Identify the first concrete consumer: the current use.
2. Search for a second existing or immediately-required consumer with materially shared behavior.
3. If no second consumer exists, challenge the abstraction:
   - can the current use remain concrete/local?
   - what actual duplication would exist without the abstraction?
4. Allow an abstraction without a second user only when another hard constraint independently requires it, and state that constraint.

## Output

- `KEEP_ABSTRACTION` or `DEFER_ABSTRACTION`
- first user
- second user, if any
- shared behavior that justifies the abstraction
- independent constraint, if that is the justification

## Constraints

- “might be useful later” is not a second user.
- Two syntactically similar call sites are not enough if their semantics differ.
- Do not force duplication when a real shared invariant already exists.
