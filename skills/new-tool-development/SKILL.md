---
name: new-tool-development
description: Orchestrate lifecycle and stage gates for a newly introduced independently invoked tool, CLI, service, or reusable executable subsystem. Use when initiating or governing product brief, requirements, implementation-spec, or implementation handoff work; do not use for substantive requirements, architecture, design, or implementation procedures.
---

# New tool development

## Scope and authority

Use this skill as the lifecycle orchestrator for a new independently invoked tool, CLI, service, or reusable executable subsystem. It owns stage entry, status, approval, invalidation, routing, and implementation readiness—not the substantive contents of the brief, requirements, or specification.

Keep three logically separate canonical artifacts:

- **Product brief — why and scope:** problem, users, intended outcome, boundaries, and non-goals.
- **Requirements document — observable what:** user-visible behavior, constraints, acceptance conditions, and quality requirements.
- **Implementation specification — how:** design, interfaces, execution details, operational treatment, and verification plan.

Do not duplicate normative content across artifacts. Link to the upstream owner instead. Compact artifacts are allowed for tiny tools, but compaction must not waive review, approval, invalidation, or implementation-authority gates.

Do not begin implementation without both a **ready implementation specification** and a **separate explicit implementation authority**. Approval of one artifact never grants authority to implement.

## Initial triage

1. Confirm the request concerns a new tool/subsystem or a lifecycle decision for one.
2. Record the requested activity explicitly: `brief`, `requirements`, `implementation-spec`, optional `implementation-plan`, or `implementation`.
3. Record known stakeholders, existing artifacts, approved non-goals, dependencies, and unresolved decisions. Distinguish observed facts, assumptions, decisions, and unknowns.
4. If the requested activity is absent or the safe scope cannot be determined, stop and ask for clarification; do not infer an activity.
5. Inspect upstream canonical artifacts and their status before drafting or routing downstream work.

## Status model

Use only the statuses needed by each artifact:

- product brief and requirements: `draft`, `approved`, `blocked`, or `invalidated`;
- implementation specification: `draft`, `ready`, `blocked`, or `invalidated`.

A `draft` means the artifact exists and is pending review or approval. Use `blocked` only when progress cannot continue because a prerequisite, authority, or blocking decision is missing; ordinary pending approval remains `draft`. Use `ready` only when the implementation specification is complete, required reviews passed, and its prerequisites remain valid. A status names its evidence: reviewer or approver, date, packet or decision record, and unresolved questions.

A draft is not approved. A review request is not authority. Approval permits the next stage but does not automatically create or draft it.

## Stage gates and routing

### Product brief

Briefs **must be written by a human**.
Agents may review briefs, and may add `TODO: <summary of suggested changes>` comments, but they must not author or edit the brief otherwise.

Briefs must be explicitly approved by a human before an agent can draft a requirements document.

Briefs must be reviewed by an agent before they can be approved.
Ask yourself: are the goals of this tool clear? Do you have enough information to draft a requirements document?
What open questions remain?

### Requirements document

Draft only requirements when `requirements` is explicitly requested and the approved brief is current. Route authorship to **`requirements-definition`**. The review packet is a skim packet: a concise summary of scope, observable behaviors, acceptance conditions, constraints, changed assumptions, and unresolved questions, with a link/reference to the canonical requirements artifact.

Require explicit human approval after the skim packet. Do not treat agent review, a comment, or approval of the brief as requirements approval. While approval is pending, keep requirements `draft`; use `blocked` only when review cannot proceed. Without approval, do not start the implementation specification.

### Implementation specification

Draft only the implementation specification when explicitly requested and the approved requirements are current. The specification is mostly agent-owned.

Use these normal contributors:

- **`technical-docs`** for document substance and reader usability;
- **`design-for-change`** for ordinary code, API, schema, and test design;
- **`spec-review`** to review the completed specification.

Use these conditional contributors only when their trigger holds:

- **`architecture-design`** for consequential subsystem decomposition or architecture boundaries needing separate analysis;
- **`design-deliberation`** for a genuine design fork with materially different viable options;
- **`boundary-declaration`** for consequential or unclear interfaces and ownership boundaries;
- **`second-user`** for reusable machinery, plugin hooks, or configurable dimensions;
- **`dependency-review`** for proposed third-party dependencies.

Escalation has an explicit authority boundary:

- A change to scope, outcome, or a non-goal requires revision of the brief and explicit human reapproval. Block or invalidate the specification until the approved brief is restored.
- A change to observable behavior, defaults, errors, or compatibility requires revision of the requirements and explicit human reapproval. Block or invalidate the specification until the approved requirements are restored.
- High-consequence technical decisions that remain within approved scope, outcomes, non-goals, and requirements may be escalated and resolved within the specification.

Also escalate unresolved security, trust, destructive-boundary, dependency/operational-cost, reusable-framework, or other blocking decisions; record the escalation and decision rather than silently choosing.

A spec becomes `ready` only after required routed work, validation, and resolution of blocking questions. `ready` does not itself authorize implementation.

### Implementation plan

Draft an implementation plan only when `implementation-plan` is explicitly requested and the implementation specification is `ready`. Route the plan to **`implementation-plan`**. It is an optional activity, not an artifact stage and not an approval gate; it must not be created speculatively or treated as implementation authority.

### Implementation handoff

Accept implementation only when:

- brief and requirements are approved and current;
- the implementation specification is `ready`;
- no invalidation trigger is outstanding; and
- a separate human or governing process has granted implementation authority.

If any condition fails, stop at handoff and report the exact missing condition. Route substantive implementation to its own procedure; this skill does not prescribe coding, deployment, or operational execution.

## Invalidation and change control

A normative change to an upstream artifact invalidates all downstream artifacts that depend on the changed content. The same applies when a specification draft proposes a change outside its authority boundary: stop and route the required upstream revision and human reapproval before continuing.

Upstream invalidation rules:

- changed brief invalidates requirements and implementation specification;
- changed requirements invalidates the implementation specification;
- changed implementation details invalidate only the affected specification status or review evidence unless they reveal an upstream normative change.

Mark affected artifacts `invalidated`, record the source change, date, impacted sections, and required re-review, then stop downstream work until the gate is re-established. Non-normative editorial changes do not invalidate unless they alter meaning; state that determination explicitly.

## User-facing packets and completion

Every transition request must include a user-facing packet covering current status, requested activity, canonical artifact, evidence and provenance, required approvals, changes since the last gate, unresolved questions, invalidation impact, and the exact next permissible action. Do not defer a requested review or reapproval merely to batch revisions: show each meaningful change in context for independent human approval and commit.

When a concrete improvement could affect the pending decision, put it in a clearly labeled, non-normative **Suggestions** section of the skim/transition packet. Include an example, tradeoff, and decision owner; suggestions are neither approved nor normative by default. If adopted, route the idea through the human-owned brief, requirements, or implementation specification and its applicable approval gate.

Report ambiguity, blocked decisions, skipped checks, and unexamined scope plainly. Completion means the requested activity was drafted or gated exactly as requested, its status and evidence were recorded, downstream stages were not created automatically, and no implementation authority was implied.
