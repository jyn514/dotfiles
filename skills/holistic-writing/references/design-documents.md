# Writing selected designs and implementation specs

Use this reference when documenting an already selected design or writing an implementation spec.
It does not select a design, author requirements, or replace a specialized lifecycle or design-review owner.
Use `new-tool-development` for its tool lifecycle and brief restrictions, `requirements-definition` for requirements from an approved brief, and [spec review](../../spec-review/SKILL.md) for auditing the specification's contract.

## Explain before machinery

For a selected nontrivial design, consider this progression when it helps the reader understand the proposal.
Do not use it as a mandatory writing workflow or heading template:

1. **Motivation:** what is difficult today and why it matters.
2. **Goals:** observable outcomes and protected behavior.
3. **Proposal in plain language:** what the named design means and does not mean.
4. **Terms and examples:** vocabulary and representative cases.
5. **Evidence:** what was measured, using which inputs and limitations.
6. **Scope and boundaries:** ownership, authority, effects, compatibility, and non-goals.
7. **Detailed design:** data model, algorithms, lifecycle, failure behavior, schemas, and interfaces.
8. **Delivery:** implementation sequence, migrations, documentation changes, and commits.
9. **Proof:** tests, acceptance checks, unresolved decisions, and completion condition.

This is guidance, not a mandatory heading template; preserve the dependency: readers should understand the problem, proposal, and examples before encountering solver models, schemas, hashes, or APIs.

Explain a nontrivial mechanism as:

1. the problem;
2. a concrete example or trace;
3. the solution and its invariant.

## Organize implementation contracts

For implementation specs, outline independently implementable contracts before drafting details.
Order sections by dependency.
Before filling them in, check whether sections bundle separate decisions or make readers reconstruct a contract across distant passages; reorganize as needed.
Within each contract, make inputs, required behavior, failure cases, and examples or acceptance evidence easy to locate.
Distinguish rationale from normative behavior.
This is structural guidance, not a fixed template.

Preserve exact API, serialization, failure, and lifecycle contracts after the reader has the model needed to understand them.

## Make the selected design reviewable

A selected design should make these reviewable without reconstructing hidden decisions:

- motivation and success criteria;
- exact meaning of the named design;
- rejected alternatives that explain the boundary;
- authoritative and derived representations;
- ownership and approval;
- normal behavior, errors, ambiguity, and recovery;
- compatibility and migration effects;
- representative single and composed cases;
- implementation order;
- verification tied to requirements;
- blocking decisions and completion condition.

Write design documents in Typst by default when the `typst` skill and compiler are available.
Use Markdown when repository convention, tooling, or the requested destination requires it.

