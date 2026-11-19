---
name: architecture-writing
description: Write, substantially revise, or review a descriptive ARCHITECTURE document or codebase guide for developers. Use for a current-system mental model, code and dataflow map, boundaries, invariants, and where to make changes, whether or not the file is named ARCHITECTURE. Not for selecting or critiquing a proposed architecture (use architecture-design), requirements or implementation specifications, implementation plans, introductory READMEs, or a bounded prose edit.
---

# Architecture writing

Help a developer understand the implementation well enough to find the relevant code and reason about a change.
A descriptive guide explains the system that exists; it does not choose a new design or turn implementation details into product requirements.
A review request authorizes findings, not edits.
Use [holistic-writing](../holistic-writing/SKILL.md) for the whole guide: establish its reader and purpose, develop the explanation, and follow its editorial pass and documentation checks.
Reuse the context established here rather than repeating the task setup.
For an unresolved design choice use [architecture-design](../architecture-design/SKILL.md); for an introductory README use [readme-writing](../readme-writing/SKILL.md).

## Establish the guide's job

Identify its intended readers, system or subsystem, their likely changes or investigations, and the requested scope.
Read the existing guide, repository documentation entrypoint and relevant contracts; follow repository instructions about documentation and authorized edits.
Use the existing destination unless a new one is requested or needed; link to the owners of commands, requirements and detailed contracts rather than reproducing them.
Do not make a user-facing task guide into an implementation specification.

## Trace the actual system

Follow representative inputs from an entry point through the major transformations to an observable consumer or effect.
Inspect the implementation, callers and relevant boundary tests, not just names or existing prose.
Trace other paths when they explain materially different behavior or reader tasks; a small subsystem may need only one path.
Identify important data representations, ownership and dependencies, where state lives, and which interfaces cross a real boundary.
Distinguish current behavior, supported contracts, intended invariants, and unresolved discrepancies; investigate consequential conflicts and report gaps instead of inventing guarantees or rationale.
Use the code and tests to support claims about behavior, and project decisions or authoritative documentation for why a deliberate constraint exists.
An absent feature is not necessarily a deliberate architectural choice.

## Build the reader's map

Select and organize material around what developers need to understand and change, not a required template or inventory of every file.
Start with an operation the reader can recognize and explain what it accomplishes before naming the internal representations that implement it.
Introduce unfamiliar concepts when the explanation needs them, after the prerequisites that make them intelligible; familiar domain terms need no textbook definition.
Use a connected, evidence-supported example to show how the operation moves through the important boundaries and why a distinction matters.
Give mechanisms the space the reader needs rather than equal space for each module or type.

A bird's-eye model, entry points, a code and dataflow map, boundary responsibilities and invariants, cross-cutting concerns, and routes from common changes to their owners and tests can all help when they serve that explanation.
Explain deliberate absences where evidence establishes them and where they affect a reader's decision.
Name concrete paths, symbols, and data at the level needed to navigate; explain why the boundaries matter and what a reader should not assume across them.

For example, if a compiler constructs candidates per input and later selects among them globally, trace one candidate through both stages.
A developer debugging a missing candidate starts in construction; one debugging a collision starts in selection.
Describe that distinction only if the actual implementation supports it; a different system may need an entirely different map.

Keep durable explanations and relevant constraints, not per-run receipts, approval history, agent-specific paths, or speculative deployment warnings.
Link to operational instructions and technical contracts where readers need details; preserve point-of-action warnings when the guide itself asks readers to perform an action.

## Review and finish

Follow a developer's route from a likely change or question to the named entry point and through the relevant code; verify representative claims, paths, links and examples against the current implementation and applicable repository checks.
Check that the guide says what exists, distinguishes uncertainty and contracts, and leaves the reader able to find the next useful place without session context.
For review, report supported findings and consequences; for writing, report the resulting path, verification and any unresolved factual gaps.
