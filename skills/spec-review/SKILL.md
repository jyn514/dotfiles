---
name: spec-review
description: Review a design document or specification for consistency, necessity, duplication, completeness, and independent mechanisms with overlapping semantics. Use to critique a single design or a related specification set; not to select among competing proposals or review an implementation change.
---

# Specification Review

Review the requested artifact against its purpose and project constraints.
Report findings; revise the artifact only when requested, except for the TODO comments that `new-tool-development` permits agents to add to human-authored product briefs.

## Read First

- Read the project's design principles, documentation conventions, and canonical
  references relevant to the artifact. Do not import another project's rules.
- Establish maturity: an exploratory sketch, a selected design, or an
  implementation-ready specification. Use its stated scope and open questions
  to set the review threshold.
- Before endorsing a general interface, inspect representative real consumers
  and their existing ownership contracts. Do not infer their requirements solely
  from the subsystem being redesigned; flag conflicts with responsibilities they
  already own.

## Maturity-specific review for new-tool artifacts

For a new-tool workflow, distinguish these artifact maturities:

- **Product brief:** owns the problem, outcomes, scope, non-goals, and human decisions.
- **Requirements:** must trace to an approved brief, be observable and solution-neutral, and flag invented product decisions.
- **Implementation spec:** must cover the requirements, own mechanisms, boundaries, and evidence, and introduce no new product behavior.

Review upstream/downstream consistency and identify dependent artifacts or evidence invalidated by stale upstream decisions. These distinctions supplement the consistency, necessity, duplication, completeness, rationale, orthogonality, and findings rules below; they do not replace them.

## Consistency

Flag contradictions and conceptual mismatches between sections, examples, and
normative rules. Check that names, ownership, and guarantees retain the same
meaning across boundaries. Distinguish an observed conflict from an assumption
that needs evidence.

When a revision moves ownership or simplifies an interface, audit signatures,
lifecycle rules, examples, and open questions throughout the artifact and linked
specifications for responsibilities still assigned to the old owner.

## Necessity

Ask who uses each feature and whether its implementation and maintenance costs
are justified. Identify the concrete consumer or constraint behind each mechanism;
flag machinery supported only by hypothetical needs. Consider whether the same
requirement can be met by an existing primitive or a narrower interface.

Separate required outcomes from proposed mechanisms. Require justification for
each mechanism; do not promote an implementation choice into a constraint when
evaluating simplifications or alternatives.

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

## Rationale and principles

Review against the project's stated principles; distinguish violations from
deliberate, explained tradeoffs. State the current design directly. Remove obsolete
comparisons, but retain rejected alternatives and historical constraints when they
explain a decision or prevent a known failure.

## Orthogonality

Before flagging overlapping interfaces, trace whether they lower to one primitive
or maintain separate semantics. A configuration shorthand that expands to an
existing operation need not be a competing mechanism.

Independent implementations with overlapping semantics need a concrete reason.
A rule such as "X wins over Y" warrants checking whether two mechanisms could
share one owner; it is not proof of a defect. Preserve intentional language
bindings, aliases, and scoped overrides with documented precedence.

## Findings

For each finding, identify the location and evidence, the consequence for a
consumer or implementer, and the smallest useful correction. Separate defects
from open questions and optional improvements; prioritize design consequences
over typos and wording. Cite canonical sections or concrete counterexamples
rather than relying on preference.

Apply the "Principles" section of `architecture-design` when evaluating corrections; use its full procedure when proposing changes to subsystem ownership or interfaces.
When proposing a new mechanism, first show why deleting a requirement,
narrowing an existing mechanism, or moving responsibility to its existing owner
is insufficient.

If no material issue is supported, say so and name the review's limits. Do not
manufacture findings to fill categories or prescribe a rewrite when a local
correction suffices.
