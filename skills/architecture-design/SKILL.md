---
name: architecture-design
description: "Design, critique, or choose a bounded software architecture: subsystem ownership, dependency direction, data/effect contracts, resource lifetimes, API shape, maintainability gain, and churn. Use for design architecture documents, extraction candidates, unresolved architecture choices, or whether a split/refactor is worth doing. Use architecture-writing for descriptive guides to an existing codebase. Also use when design/specification work requires choosing an approach or changing guarantees, supported cases, or failure behavior, even if framed as documentation. Trace the existing path first and reuse settled contracts. Use operational-lifecycle for operator workflows such as installation, startup, updates, and recovery; use architecture when those expose structural or cross-boundary decisions. Not for broad discovery, implementation planning, recording settled decisions, prose-only edits, routine local edits with settled boundaries, or current-change review."
---

# Architecture design

Choose responsibilities that meet the required outcome and earn their implementation and maintenance cost.
Start with a caller-to-result path, not a proposed component diagram.
Use [Coding judgement](../coding-judgement/SKILL.md) for the common coding obligations and every applicable topic reference before making design or critique decisions.
This skill owns the architecture workflow, not a second coding checklist.
Before endorsing a replacement recommendation during follow-up discussion, use [work-selection](../work-selection/SKILL.md#reconsider-a-recommendation).
For critique, report supported findings, consequences, and the smallest useful corrections; a review request does not authorize edits or require a replacement design.

Use [operational lifecycle](../operational-lifecycle/SKILL.md) to establish installation, recurring operation, startup, update, and recovery workflows.
Use architecture design for unresolved subsystem, interface, or authority boundaries those workflows expose; do not require a decomposition exercise for an operator task.

## Establish the outcome and authority

Identify the subsystem, problem, constraints, non-goals, compatibility, and requested output.
State the minimum observable outcome and its practical purpose before choosing mechanisms.
Stop and use `opportunity-scan` if no subsystem is selected.
Read the repository's relevant architecture, ownership, data/effects, testing, and design-document guidance and nearest subsystem instructions.
For new-tool work, develop the design against governing requirements and integration constraints under [new-tool development](../new-tool-development/SKILL.md).
That workflow distinguishes provisional design from contracts ready to implement; unresolved product choices remain explicit rather than becoming design assumptions.

Use the shared decision-authority rule to distinguish requirements from proposed guarantees.
Before elaborating a mechanism, name its requirement or hard constraint and the case the existing path cannot satisfy.
Identify required variability and its authoritative sources; keep adjacent policy fixed and record deliberate defaults.
Require explicit input when omission could choose the wrong identity, target, scope, or high-consequence action; otherwise choose a sensible default.

Before choosing persistence, establish the data's owner, medium, form, lifetime, readers, and rotation or recovery authority.
Changes to principal, medium, protection, or lifetime change behavior.
Ask about unsettled consequential storage changes before designing dependent mechanisms; continue independent analysis.

## Trace the smallest complete solution

Follow one caller-to-result path through commands, identifiers, defaults, effects, and failures.
Inspect its specification, implementation, callers, and same-path tests; for greenfield work, trace the closest primitive or integration caller.
Compare it with the outcome and required ownership, authorization, compatibility, storage, and supported interfaces.
Before designing an application workaround for a tool limitation, inspect the tool's data model and extension points and establish whether changing the tool is permitted.
Use the cheapest decision-changing check where sufficiency is uncertain.
If the path or a local change suffices, recommend it and stop before proposal-specific inspection or boundary design.

For example, an existing save-and-exit operation and verifiable saved record may preserve sessions through restart without a new receipt protocol.
They cannot acknowledge a specific save while the session continues running.
Read the [contrasting examples](references/simplicity-examples.md) when a proposed mechanism obscures the simpler complete path.


Use the [dependency contrast](../new-tool-development/SKILL.md#let-dependencies-determine-the-order) to distinguish independent work from work awaiting a shared decision.
## Decide whether boundary development is needed

If the trace leaves unmet behavior requiring a choice about ownership, dependencies, interface guarantees, or resource lifetimes, read [Develop a boundary design](references/develop-boundaries.md) before developing or critiquing that choice.
Its gap inspection, ownership principles, contract development, and focused checks are mandatory for applicable boundary work.
Do not invent new boundaries when the existing path or a local change meets the outcome.
Carry settled contracts forward, then assess the gain and report the result below.

## Decide whether the gain earns the cost

Compare demonstrated maintenance or safety gain with affected callers, tests, dynamic state, generated artifacts, inventories, and compatibility surfaces.
For greenfield work, compare implementation and integration cost instead of migration churn.
Moving functions alone is not a benefit.
Challenge the weakest seam: does it improve ownership, hide coupling behind a facade, give a leaf orchestration or policy, or reopen settled contracts?
Use existing evidence when sufficient; delegate one review only for independent evidence or useful parallelism.
Revise the recommendation when evidence challenges it.

Classify the result:

- `RECOMMEND`: demonstrated gain exceeds bounded cost.
- `CONDITIONAL`: one named measurement, consumer, or prerequisite remains.
- `REJECT`: complexity or churn exceeds demonstrated benefit.

Stop extraction when it removes the motivating pain; stop greenfield design when approved requirements are met without unsupported machinery.
Keep speculative hardening outside the recommendation.

## Present or hand off

Report the classification, chosen solution, decisive comparison, gain, costs, risks, verification limits, rejected broader design, and next action.
An early recommendation needs no inapplicable boundary detail or new document.
A requested durable document follows repository conventions and records applicable scope, evidence, contracts, tests, acceptance evidence, and open questions; compile when required and report its path.
Architecture assessment does not itself require implementation tasks or a commit plan.
Use `implementation-plan` only when a repository plan is requested; carry the contract forward.
Use the repository's review process for a current patch.

Open issues only when requested, following tracker guidance and searching by exact title and boundary for duplicates.
Separate independent extractions and record the motivating coupling, boundary contract, checks, exclusions, and stopping point.
Keep conditional work out of an implementation-ready state until its prerequisite exists.
