---
name: ratchet
description: Define enforcement policy for an established invariant or check. Use when deciding how to block new violations while reducing an existing baseline, preserve violation identity or counts, bound exceptions and their expiry, or change an existing rule's enforced scope or guarantees. Do not load merely to choose types versus tests, design a test oracle, add regression coverage, or protect a newly implemented behavior; those decisions belong to design-for-change.
---

# ratchet

## Purpose

Own the policy for which violations a check rejects, which existing violations
it temporarily permits, and how that permitted set shrinks. Use
[design-for-change](../design-for-change/SKILL.md) for implementing checks,
choosing regression cases, and validating test oracles. Load both only when the
task contains separate policy and implementation decisions.

For example, introducing a lint rule with existing violations needs a baseline
and exception policy. Reproducing a Docker mount failure with a real container
needs test design, so use `design-for-change` alone.

## Inputs

- The established invariant and the check's scope
- Current enforcement rules, violations, and exceptions
- The requested policy change and authority to change it

## Procedure

1. Inspect the owning check, its scope, and current violations. Name the
   unresolved enforcement-policy decision. If only implementation or oracle
   design remains, stop this workflow and use `design-for-change`.
2. Define violation identity and multiplicity before comparing results.
   Distinct occurrences, paths, or owners must not collapse because their
   normalized text or fingerprint is equal. Set membership is insufficient
   when the invariant constrains counts, ownership, or one-to-one correspondence.
3. Treat baselines as bounded debt:
   - preserve multiplicity or explicit occurrence identity
   - fail on additions and report removals as stale
   - keep regeneration deterministic and show semantic deltas
   - never let regeneration silently bless new debt
4. Give each exception a scope, owner, and expiry or removal condition. Record
   which violations it permits; a baseline entry must not authorize unrelated
   future violations.
5. When changing a rule's enforced scope or guarantees, compare the old and new policy.
   Preserve existing guarantees unless explicit human approval or stronger
   replacement evidence justifies the change. Do not remove or weaken a check
   merely to make progress.
6. Verify the policy on a new violation, a resolved baseline entry, and distinct
   violations with equal normalized text. Include exception expiry when used.
   Follow `design-for-change` for oracle validation; record any policy outcome
   that cannot yet be verified rather than claiming it is enforced.

## Output

- Invariant and enforced scope
- Violation identity, baseline update rules, and bounded exceptions
- Preserved guarantees or the authority/evidence for replacing them
- Policy checks run, observed outcomes, and unverified cases

## Constraints

- Do not certify paths outside the inspected and verified scope.
- Do not expand permitted violations through automatic baseline regeneration.
