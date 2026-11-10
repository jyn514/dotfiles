# Writing selected designs and implementation specs

Use this reference to explain an already selected design or write an implementation spec.
Design selection, requirements authoring, and specification-contract review belong to their specialized owners.
Use `new-tool-development` for its lifecycle and human-owned brief restrictions, `requirements-definition` for requirements from an approved brief, and [spec review](../../spec-review/SKILL.md) for contract audits.

## Explain before machinery

For a nontrivial mechanism, start with the problem and a concrete example or trace.
Then explain the solution and its invariant.
What does the named design mean, and what does it change?
Readers need that model before solver notation, schemas, hashes, or APIs.

For a nontrivial design, consider this progression rather than treating it as required headings:

1. The difficulty today, desired outcomes, and behavior to preserve.
2. The proposal in plain language, with terms and representative cases.
3. Evidence: inputs, measurements, and limitations.
4. Boundaries: ownership, authority, effects, compatibility, and non-goals.
5. Details: data model, algorithms, lifecycle, errors, recovery, and interfaces.
6. Delivery and verification: implementation order, migrations, documentation, tests, and completion conditions.

Keep exact API, serialization, failure, and lifecycle contracts after the explanation needed to understand them.
Explain which representations are authoritative or derived and which rejected alternatives account for the boundary.
Include single and composed cases, required approvals, and unresolved decisions that block implementation.

## Organize implementation contracts

Outline independently implementable contracts before drafting their details, then order them by dependency.
Does one section bundle unrelated decisions, or must a reader reconstruct one contract across distant passages?
Reorganize where needed.
Make each contract's inputs, required behavior, failure cases, and acceptance evidence easy to locate.
Distinguish rationale from normative behavior and tie verification to requirements.

Write design documents in Typst by default when the `typst` skill and compiler are available.
Use Markdown when repository convention, tooling, or the requested destination requires it.
