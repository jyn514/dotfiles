---
name: requirements-definition
description: Author solution-neutral requirements from an approved product brief when explicitly asked to draft requirements. Use for requirements definition and traceability; do not use for product discovery, implementation specifications, architecture, or requirements review.
---

# Requirements definition

## Scope and authority

Use this skill only when both conditions hold:

1. An approved product brief is available as the authoritative product-intent input.
2. A person explicitly asks you to draft or revise requirements.

The approved brief is the primary authority. Additional authoritative sources may clarify or constrain intent within the approved brief, but may not expand or contradict product intent. Do not author a requirement that expands or contradicts the brief: if resolving the conflict is necessary to state the requested requirements, record `NEEDS_PRODUCT_DECISION` and require brief revision and reapproval through `new-tool-development`; otherwise raise the idea only as a non-normative suggestion. Other sources may be used only when identified as authoritative by the requester or governing product documentation. Do not infer approval from a draft, discussion, ticket, request for ideas, or an implementation task.

This skill owns the requirements-definition phase only. It does not discover or approve product intent, invent scope, choose an implementation, write implementation specifications, design architecture, define internal APIs, prescribe files, define exact tests, or plan delivery sequencing. After drafting, route requirements review to `spec-review`; require explicit human approval, then stop. Any later request for an implementation specification returns through `new-tool-development`, not `spec-review`.

If the brief is missing, approval is unclear, or the request is not explicit, stop and report the missing prerequisite instead of drafting.

## Procedure

### 1. Establish the working inputs

Record, separately:

- the approved brief and its goals, constraints, non-goals, assumptions, and authoritative decisions;
- any additional authoritative sources and their authority;
- the explicit drafting request;
- unresolved questions or conflicting sources.

Do not turn examples, preferences, implementation suggestions, or ambiguous language into requirements without authoritative support.

### 2. Build the traceability inventory

Give each brief goal, constraint, and non-goal a stable source label, such as `BG-1`, `BC-1`, or `BN-1`. Preserve existing source identifiers when they are authoritative and stable.

For each proposed requirement or exclusion, identify the exact source label(s) that justify it: positive requirements trace to a brief goal, constraint, or other explicitly authoritative source; exclusions trace to approved non-goals.

If a material unsupported choice would change a requirement's meaning or acceptance, record it as `NEEDS_PRODUCT_DECISION` in a clearly non-normative review-decisions section. Put optional, non-blocking agent suggestions in a clearly non-normative skim packet; never convert either into an invented requirement.

### 3. Draft observable, solution-neutral requirements

Assign each requirement a stable identifier that will remain unchanged during ordinary editing, for example `REQ-001`. Do not reuse an identifier for different behavior.

Write each requirement so that an independent evaluator can determine whether it is satisfied from externally observable behavior. Prefer:

- actors, conditions, inputs, outputs, and state transitions visible to users or authorized external systems;
- explicit defaults and precedence when the brief supports them;
- observable error conditions and user-visible or externally relevant error behavior when supported;
- compatibility, security or trust, performance, and operational constraints only when the brief or authoritative source supports them.

Keep requirements solution-neutral. Exclude implementation mechanisms, file paths, internal APIs, architecture, exact test cases, technology choices, and delivery sequencing unless the item is itself an externally observable, authoritative constraint. Preserve exact identifiers, numbers, error text, and uncertainty from the sources; do not silently normalize or embellish them.

Separate requirements from rationale, evidence, assumptions, and open decisions. Do not hide a product decision inside acceptance wording.

### 4. Define acceptance evidence

For every requirement, state concise acceptance evidence describing what would demonstrate satisfaction. Evidence must be observable and proportionate; it is not an implementation plan and must not prescribe exact tests.

Use evidence that can disprove the requirement, such as an observable scenario, result, boundary, or recorded operational measure when the source supports one. If evidence cannot be defined without inventing behavior, record the missing decision and affected requirement, if any, in the non-normative review-decisions section; do not settle it in the requirement or acceptance evidence.

### 5. Produce the requirements document

Use this compact structure unless the requester requires an equivalent structure:

1. **Status and authority** — approval state, source documents, and scope.
2. **Definitions and source labels** — only terms needed to interpret the document.
3. **Requirements** — one entry per stable ID, containing:
   - statement;
   - source traceability;
   - acceptance evidence;
   - dependencies or notes only when authoritative.
4. **Explicit non-goals** — brief non-goals that prevent scope expansion.
5. **Review decisions and scope, when needed** — non-normative `NEEDS_PRODUCT_DECISION` items naming affected requirements or source labels.
6. **Traceability coverage** — each brief goal, constraint, and non-goal mapped to requirement IDs, exclusions, `NEEDS_PRODUCT_DECISION`, or explicitly no requirement because it is a non-goal.

Provide an accompanying human skim packet with concise lists of uncovered goals, new decisions requiring review, unresolved ambiguity, and an acceptance summary. Keep it outside the normative requirements document.

For a tiny tool, keep the document compact by combining sections or using a small table, but retain stable IDs, source traces, acceptance evidence, and the separate human skim packet.

### 6. Check boundaries and completeness

Before presenting the draft, verify:

- no requirement lacks authoritative traceability;
- every brief goal and supported constraint appears in coverage;
- non-goals are not accidentally restated as scope;
- material unsupported choices affecting requirements are `NEEDS_PRODUCT_DECISION`; optional suggestions remain in the non-normative packet;
- defaults, errors, compatibility, trust, performance, and operations are included only where supported;
- wording is observable and solution-neutral;
- implementation specification has not begun;
- identifiers, numbers, exact errors, and unresolved uncertainty were preserved.

Report inspected sources, excluded or unresolved items, and any ambiguity that prevents a reliable requirement. Do not claim complete coverage when a source was unavailable or conflicting.

### 7. Require approval and stop

Present the requirements as a draft requiring explicit human approval. Route the draft and review questions to `spec-review`, then stop pending explicit human approval. Do not proceed to implementation specification or implementation from this skill. If a later implementation-spec request arrives, return it through `new-tool-development`; `spec-review` does not own implementation-spec progression. Approval of the requirements is not approval of an implementation.

## Output rules

A valid completion consists of the requirements document plus the human skim packet and an explicit approval request. If prerequisites fail, output only the blocking condition and the precise missing authority or decision. If the work reveals a material unsupported choice affecting a requirement, retain `NEEDS_PRODUCT_DECISION` rather than guessing; keep optional proposals in the non-normative packet.
