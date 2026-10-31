---
name: spec-review
description: Review what a supplied specification promises, against its own statements and governing requirements. Audit internal consistency, traceability, unsupported restrictions, and completeness appropriate to its declared stage. For an unqualified request to review a specification, start with its contract; do not automatically add separate design or editorial reviews. Not for choosing an architecture, comparing implementation with a specification, auditing completion of an owned change, or reviewing only the explanation and reading experience.
---

# Specification review

Use [evidence standards](../references/review-evidence.md) to support findings and state what each check establishes.

Audit the specification's contract: its declared requirements, supported cases, ownership, interfaces, failure behavior, and verification obligations.
For an unqualified specification-review request, start with this contract audit.
Consult design or editorial guidance only for a concrete design or explanation question; do not automatically run adjacent review workflows.
Report findings; revise the artifact only when requested, except for the TODO comments that `new-tool-development` permits agents to add to human-authored product briefs.

## Read First

- Read the project's design principles, documentation conventions, and canonical
  references relevant to the artifact. Do not import another project's rules.
- Establish maturity: an exploratory sketch, a selected design, or an
  implementation-ready specification. Use its stated scope and open questions
  to set the review threshold.
- Inspect representative consumers when needed to establish whether the declared
  inputs, effects, ownership, and guarantees match governing requirements.
  Do not infer consumer requirements solely from the specification being audited.

## Maturity-specific review for new-tool artifacts

For a new-tool workflow, distinguish these artifact maturities:

- **Product brief:** owns the problem, outcomes, scope, non-goals, and human decisions.
- **Requirements:** must trace to an approved brief, be observable and solution-neutral, and flag invented product decisions.
- **Implementation spec:** must cover the requirements, own mechanisms, boundaries, and evidence, and introduce no new product behavior.

Review upstream/downstream consistency and identify dependent artifacts or evidence invalidated by stale upstream decisions. These distinctions supplement the consistency, necessity, duplication, completeness, rationale, orthogonality, and findings rules below; they do not replace them.

## Non-narrowing check

For requirements and implementation specs, apply the [non-narrowing check](references/non-narrowing.md) to establish upstream permissions before assessing downstream eligibility rules.
Use it to check population and phase distinctions, permitted explanation modes and their sufficient evidence, competing readings, and downstream rejection conditions.
The focused reference is part of this audit; other callers may consult it without starting a full specification review.

## Consistency

Flag contradictions and conceptual mismatches between sections, examples, and
normative rules. Check that names, ownership, and guarantees retain the same
meaning across boundaries. Distinguish an observed conflict from an assumption
that needs evidence.

When a revision moves ownership or simplifies an interface, audit signatures,
lifecycle rules, examples, and open questions throughout the artifact and linked
specifications for responsibilities still assigned to the old owner.

## Necessity

Trace each required feature, restriction, and prescribed mechanism to a governing outcome or constraint.
Flag obligations supported only by hypothetical needs or by the draft's own assertions.
Distinguish an approved implementation choice from an unsupported product requirement.
A mechanism appearing in the specification does not establish that upstream requirements demand it.

## Duplication

Give normative behavior one canonical owner and use direct references elsewhere.
Flag independently maintained definitions that can drift. Preserve local context
needed to understand a rule where it is applied.

## Completeness

Judge completeness against maturity. A sketch may leave transport and algorithms
open if it states the important ownership and guarantees. A selected design must
settle decisions that change its architecture; an implementation-ready spec must
not leave incompatible observable behaviors for implementers to choose between.

Look for missing inputs, results, failure behavior, lifecycle ownership, and
acceptance evidence where they affect the design's claims. Do not demand a full
API catalog or implementation plan from a high-level sketch.

For a concrete question about a declared lifecycle, effect, or failure guarantee, consult the corresponding
[design-risk check](../architecture-design/references/design-risks.md#applicability).
Use only checks relevant to the contract and artifact's maturity; they do not require a separate design workflow or new mechanisms.

## Rationale and principles

Review against the project's stated principles; distinguish violations from
deliberate, explained tradeoffs. State the current design directly. Remove obsolete
comparisons, but retain rejected alternatives and historical constraints when they
explain a decision or prevent a known failure.

## Orthogonality

Check whether separately named operations or options make distinct promises or restate the same contract.
A documented alias or shorthand need not be a competing operation.
Flag contradictory ownership or precedence rules, not multiple names alone.
Preserve intentional language bindings, aliases, and scoped overrides with documented precedence.

## Findings

Use the shared evidence standards for finding structure and checked-scope reporting.
Prioritize design consequences over typos and wording; cite canonical sections or concrete counterexamples rather than preference.

If no material issue is supported, say so and name the review's limits. Do not
manufacture findings to fill categories or prescribe a rewrite when a local
correction suffices.
