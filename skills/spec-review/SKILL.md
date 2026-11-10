---
name: spec-review
description: Review what a supplied specification promises, against its own statements and governing requirements. Audit internal consistency, traceability, unsupported restrictions, and completeness appropriate to its declared stage. For an unqualified request to review a specification, start with its contract; do not automatically add separate design or editorial reviews. Not for choosing an architecture, comparing implementation with a specification, auditing completion of an owned change, or reviewing only the explanation and reading experience.
---

# Specification review

Review supported cases, ownership, interfaces, failure behavior, and verification obligations against governing requirements and the specification's own statements.
Report findings; edit only when asked, except for the TODO comments `new-tool-development` permits on human-authored product briefs.
Use the shared [evidence standards](../references/review-evidence.md) for findings and inspected-scope reporting.

## Establish authority and review depth

Read the artifact, its governing decisions, and the project's relevant principles and documentation conventions—not another project's rules.
Inspect representative consumers when their needs or responsibilities could change the assessment; do not infer those needs from the draft alone.

Judge gaps against the artifact's stated scope and open questions:

- **Sketch:** establish important ownership and guarantees; transport and algorithms may remain open.
- **Selected design:** settle decisions that change the architecture.
- **Implementation-ready specification:** leave no incompatible observable behaviors for implementers to choose between.

In a staged new-tool workflow, distinguish decision authority:

- **Product brief:** problem, outcomes, scope, non-goals, and human decisions.
- **Requirements:** observable, solution-neutral obligations traced to an approved brief.
- **Implementation specification:** mechanisms, boundaries, and evidence covering those requirements, without new product behavior.

Flag invented product decisions and identify dependent artifacts or evidence invalidated by upstream changes.

## Follow promises through cases

For declared inputs, results, failures, and lifecycle transitions, ask: what is admitted, who acts, what result is promised, and what evidence would establish it?
Do not demand a full API catalog or implementation plan from a sketch.

For example, suppose a specification promises that cancelling an export prevents publication.
Its lifecycle section says the worker publishes as soon as computation finishes.
Follow a cancellation arriving between computation and publication: which rule controls the destination file?
If both sections require incompatible results, report a contradiction.
If neither says who decides, report the missing ownership or cancellation rule at the depth this artifact needs.
The finding concerns the promised behavior; it does not require choosing a new worker architecture.

For a concrete lifecycle, effect, or failure question, consult the relevant [design-risk check](../architecture-design/references/design-risks.md#applicability).
Match it to the contract and maturity; do not start a separate design workflow.
For requirements and implementation specifications, apply the [non-narrowing check](references/non-narrowing.md): downstream agreement can conceal a shared restriction unsupported upstream.

Trace required features, restrictions, and prescribed mechanisms to governing outcomes or constraints.
Flag obligations supported only by hypothetical needs or the draft's own assertions.
An approved implementation choice is not necessarily a product requirement.

## Compare sections and owners

Check that names, responsibilities, and guarantees agree across rules, signatures, examples, lifecycle descriptions, and open questions.
After an ownership change, check linked specifications for duties still assigned to the old owner.
Give normative rules one canonical owner, with references and enough local context to apply them.

Flag contradictory ownership or precedence, not multiple names alone.
Preserve intentional language bindings, aliases, shorthands, and scoped overrides with documented precedence.
Distinguish principle violations from deliberate, explained tradeoffs.
Retain rationale, historical constraints, and rejected alternatives that explain decisions or prevent known failures; cut obsolete comparisons.

## Return findings

Prioritize contract consequences over wording preferences; cite governing sections or concrete counterexamples.
If no material issue is supported, say so and name the limits.
Do not manufacture findings or prescribe a rewrite when a local correction suffices.
