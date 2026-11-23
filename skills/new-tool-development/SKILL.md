---
name: new-tool-development
description: Coordinate development of a new independently invoked tool, CLI, service, or reusable executable subsystem. Use when initiating or coordinating its brief, requirements, design, construction, or implementation handoff; check dependencies, authority, and acceptance against intended use. Specialized skills own substantive requirements, design, and implementation methods. Exclude private build or deployment hooks that only extend an existing workflow without introducing a standalone tool or subsystem.
---

# New tool development

When coordinating tool development, act as its executive under [delegation](../delegation/SKILL.md) and the [executive policy](../delegation/references/executive.md).
Organize the work around the original requested outcome.
Delegate substantive work and run independent work in parallel by default.

Start from the approved product intent and the requested deliverable.
Identify who uses the result, what they do with it, and what outcome acceptance must establish.
Use representative inputs and existing consumer evidence; keep unresolved product choices explicit.
A requested specification can be the finished deliverable.

## Connect intended use to the contract

Trace the intended use through requirements, design, and acceptance checks.
For example, an expert comparing source drawings with an overlay needs faithful content, correct alignment, and readable marks from meaningfully related drawings.
Check shared interfaces along that path: an extracted crop can be correct locally but misplaced during composition if units, origin, or orientation differ.
Do not invent acceptance thresholds where the brief leaves a product choice open.

Keep the reasons for a constraint visible.
A particular aligner may need a particular input representation; that does not establish that the expert's activity needs that aligner.
Compare changing the mechanism with satisfying the extra dependencies it introduces.
Preserve explicit product requirements while reconsidering agent-selected means.

## Let dependencies determine the order

Suppose extraction behavior and the shared coordinate convention are settled and reviewed, while registration research continues.
The implementation owner can build and check extraction without knowing which registration algorithm will win.
Comparing extracted content with its source establishes useful fidelity evidence, and later registration work can consume the agreed representation.
The unfinished registration design does not make that extraction contract unfinished.

Change one fact: extraction and registration still disagree about the shared coordinate convention.
Building them independently now could embed incompatible assumptions throughout both components.
Resolving and reviewing that convention first can prevent more rework than early construction would reveal.
More design also wins when a consequential algorithm or interface remains unspecified, or available evidence already shows the proposed mechanism cannot meet a requirement.
Implementation should not inherit incompatible behaviors or an impossible promise as local choices.

When deciding whether work can start, name the unresolved decision that would change its required behavior, shared interface, or correctness-critical mechanism.
An unfinished document or pending unrelated review is not itself a dependency.
Hold work affected by a consequential unresolved dependency and continue independent work.
Keep contract details and dependencies in the existing specification or assignment; do not add a separate readiness table.
When construction is appropriate, start with a usable path through the intended consumer rather than accumulating disconnected helpers.
Experiments are optional and should resolve a decision; component success does not establish whole-tool acceptance.

## Check results against intended use

As results arrive, compare them with the sources and required consumer activity:

- A source comparison can show that extraction preserves the inspected marks.
  It leaves cross-drawing alignment and coverage of other drawing families untested.
  Use it to support extraction decisions, not to declare the overlay tool complete.
- A rendered overlay can expose unreadable overlapping labels even when every source mark is present and correctly positioned.
  File validity and geometric correctness do not explain how the expert can make the comparison.
  Reconsider the presentation mechanism; if the approved acceptance contract leaves interpretability unresolved, raise that requirements decision too.
  Do not accept unusable output simply because it passes existing tests.
- An inventory can reveal a required drawing family that the current registration approach cannot handle.
  Many successful examples from other families do not resolve that omission.
  Reconsider the approach or the work still needed for coverage, rather than silently excluding the family.
  If the brief does not settle whether the family belongs, ask for that product decision.

Select checks that can distinguish the proposed explanation from a plausible failure.
For the overlay, comparing output only with another candidate-generated image can repeat the same extraction error.
Source drawings and independently established expectations give the check a basis outside the candidate.
Use focused checks for local decisions and assembled consumer checks for interactions and overall usefulness.
Plan representative real-input checks before expanding repeated work; a successful easy example does not establish coverage.

An experiment or prototype supplies evidence only for the conditions it exercised.
Record decisive inputs, findings, and limitations where the design can reference them.
A prototype may be discarded or developed further; neither disposal nor promotion to production follows from its label.
Production use still requires the applicable contract, review, and verification.

## Approvals and readiness

Apply these boundaries to the affected work, not merely to whole documents:

- **Product intent:** a human writes and explicitly approves the brief after agent review.
  Agents may review it and add `TODO: <summary of suggested changes>` comments, but otherwise may not author or edit it.
  An approved, current brief is required before requirements drafting.
- **Requirements:** obtain explicit human approval of affected requirements before implementation.
  Use [human review packets](../human-review-packets/SKILL.md) for consequential approvals so the behavior, acceptance, and unresolved choices are reviewable.
  Approval of the brief or agent review does not approve requirements.
- **Provisional design:** after substantive human feedback on requirements, identify which parts are settled enough to support specification drafting while requirements revision or approval continues.
  Start drafting those parts if already authorized; otherwise ask to draft them in parallel now, rather than waiting for the whole requirements document to be approved.
  Specification drafting may also proceed from approved requirements.
  The brief must remain approved and current; keep unapproved requirements and assumptions explicit.
- **Implementation:** require an implementation-ready affected contract and explicit implementation authority covering the work.
  Readiness requires independent technical feedback from at least one other agent, applicable contract review, resolved consequential decisions, settled dependencies, and a concrete verification strategy.
  Settle required behavior, interfaces, invariants, and correctness-critical mechanisms while leaving ordinary local choices to implementation.
  Identify expected-result sources and checks that can expose plausible partial implementations, including the first usable consumer result.
  Plan these checks before implementation; do not require the finished tool as evidence of design readiness.

Implementation permission covers reviewed components as they become ready within the agreed scope and resources.
Do not add formal human approval of the whole specification or each component unless explicitly required.
Honor explicit waits, start times, stop instructions, and budget boundaries.

Before waiting for research, review, or approval, check both the current activity and the next development activity for work that can advance without that answer.
Start work whose dependencies are settled.
Bring missing approval or implementation-permission decisions forward now, naming the proposed work, resource limits, and unresolved prerequisites.
Continue independent work while the answer is pending.

If new evidence changes product scope or outcomes, return the affected intent to the human-owned brief for revision and reapproval.
If it changes required observable behavior, defaults, errors, or compatibility, revise the affected requirements and obtain human reapproval before dependent implementation.
Trace the change through shared interfaces and affected review or verification evidence.
Hold only affected work; technical changes within approved requirements need affected technical review, not another product approval.

## Activities and routing

Use the procedure that owns the substantive activity; these routes do not require a separate document, agent, or full team for every topic.
Keep product intent, observable obligations, and implementation decisions distinguishable, with one canonical home for each promise.
They may share a file or occupy topic-oriented sections.
Preserve consequential rationale, uncertainties, and evidence beside the decisions they explain.

- For requirements authorship from the approved brief, use [requirements definition](../requirements-definition/SKILL.md).
- For unsettled mechanisms, subsystem boundaries, or consequential interfaces, use [architecture design](../architecture-design/SKILL.md).
  Use its [alternatives](../architecture-design/references/alternatives.md) and [boundary-contract questions](../architecture-design/references/boundary-contracts.md) when those choices need analysis.
  Ordinary API, schema, and implementation choices use [coding judgement](../coding-judgement/SKILL.md) and its topic references.
- For implementation-spec explanation, use [design-document guidance](../holistic-writing/references/design-documents.md).
  After substantial drafting, use the [shared editorial pass](../holistic-writing/references/editorial-pass.md).
  Use [specification review](../spec-review/SKILL.md) to check affected promises against requirements, including when other contracts remain unfinished.
- For verification strategy, expected results, and consumer checks, use [testing with evidence](../references/testing.md).
  For proposed third-party dependencies, use [dependency review](../dependency-review/SKILL.md).
- When interaction or learning choices remain unsettled, use [UX design](../ux-design/SKILL.md).
  Use [UI design](../ui-design/SKILL.md) for concrete rendered behavior, and [operational lifecycle](../operational-lifecycle/SKILL.md) for setup, updates, recovery, recurring work, and removal.
- Use [implementation planning](../implementation-plan/SKILL.md) only when a plan is requested; an already actionable contract needs no extra planning artifact.
  When dividing work, use [delegation](../delegation/SKILL.md) to carry the consumer purpose and changing dependencies to their owners.

Finish against the requested outcome and its acceptance conditions.
For a specification, distinguish decisions supported by review or evidence from behavior still awaiting implementation checks.
For a tool, demonstrate the intended use and required coverage, including the operational obligations its mechanism introduces.
Report unresolved work without treating document completion, a passing component, or an artifact count as the requested result.
