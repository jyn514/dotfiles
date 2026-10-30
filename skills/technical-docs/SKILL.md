---
name: technical-docs
description: Author or substantially revise documentation using documentation-specific decisions about reader tasks, tutorial/how-to/reference/explanation forms, prerequisites, authoritative owners, starting points, routes, and warnings at action. Use also for documentation usability or correctness reviews. Placement-only decisions and routine additions do not require this workflow. Introductory README writing belongs to readme-writing; whole-artifact prose authoring and editorial review belong to holistic-writing; tree restructuring belongs to reorganize-docs. Do not select designs or author human-owned product briefs.
---

# Technical documentation

Help readers learn, act, look up facts, or understand a system without reconstructing the originating session.
This skill owns documentation-specific authoring decisions, not a mandatory prose or style template.

## Scope and routes

Routine additions to an established section need validation of changed text and links, not this workflow.
Do not load this workflow merely because a new heading is needed.
Use `readme-writing` for an introductory README; it is independently usable, not a required first stage of this workflow.
Use `reorganize-docs` for restructuring existing pages or navigation, including consolidation, splits, renames, archives, and multi-page information architecture.
Use `holistic-writing` for general whole-artifact authoring, substantial revision, or editorial review of prose, including after substantial documentation drafting.
A routed editorial pass uses established decisions; do not restart documentation authoring or require all three writing skills for every README.
Use `tighten-prose` for bounded local polishing.

### Subject-matter authority

These owners retain authority over substance; they are not required workflow stages:

- `new-tool-development` owns the lifecycle of a new independently invoked tool, CLI, service, or reusable executable subsystem.
  Product briefs are human-authored; agents may review and add only the TODO comments it permits, not write or rewrite brief prose.
- `requirements-definition` alone owns requirements authoring from an approved product brief.
- `human-review-packets` owns human decision questions and approval handoffs.
- `skill-authoring` owns skill behavior, discovery, and procedure.
- [Design review](../review/references/design.md) owns review-only consistency and completeness analysis of designs or specifications.

If a named owner is unavailable, preserve its boundaries, state the limitation, and do not claim its specialized review occurred.
A review request does not authorize prose edits; report findings and the smallest useful correction unless changes are requested.
The permitted TODO comments in human-authored product briefs remain governed by `new-tool-development`.

## 1. Establish the reader, owner, and task

Read the current page, nearest documentation entrypoint, authoritative inputs, and representative consumers.
For new content, establish the destination and canonical owner before drafting.
For review, retain the destination unless relocation is requested.
When the task or intended reader is unclear enough to change the document, ask rather than inventing a scope.

Identify the reader's background and whether she needs to learn, perform a task, look up facts, understand a design, or review a decision.
Identify which artifact owns each fact or rule and distinguish observed behavior, selected decisions, proposals, and unresolved questions.
Preserve provenance and limitations rather than treating conversation context, generated output, or analysis as unexplained authority.

When changing boundaries between human documentation, agent instructions, and skills, consult [Process engineering](https://ai-maintainers.jyn.dev/general/process-engineering.html) for rationale.
Keep operative procedures in their canonical owners rather than reproducing that guide locally.

## 2. Choose the documentation form

Keep these needs distinct without forcing a fixed page template:

- **Tutorial:** guide a learner through a safe, successful experience.
  State what she will build or understand, prerequisites, and the safe starting state.
- **How-to:** help a competent reader accomplish a specific task.
  State the task, prerequisites, expected result, and important hazards.
- **Reference:** present accurate, neutral facts structured like the subject.
  State the covered system, version, scope, notation, and lookup organization.
  Do not force motivation or design goals into neutral reference material.
- **Explanation:** develop understanding through context, reasons, examples, and consequences.
  Explain the problem, goals, and important non-goals before the proposal.
  Define a named proposal on first use and show the problem and proposed behavior before detailed machinery.

A design document combines explanation with an implementation and verification contract.
When writing a selected design or implementation spec, use [Design documents](references/design-documents.md) for conditional structure and reviewability guidance.
That reference does not choose the design or impose its progression on other documentation.
Within one page, separate mixed reader needs with clear sections or links.
Route a multi-page split or navigation redesign to `reorganize-docs` rather than performing it as incidental prose editing.

## 3. Make starting points and routes usable

Assume the reader opens the page directly months later.
State required background, prerequisites, authoritative inputs, and important limitations where needed to begin safely.
Explain unfamiliar project-specific terms before consequential use while preserving precise established terms.
Avoid “the option we chose” unless the page names and explains that option.
Use a glossary only when many project-specific terms interact; state the audience and assumed background when either is not obvious.

Keep each concept's canonical owner clear and link to it from relevant starting points rather than copying its procedure.
Keep action-specific warnings beside the actions they govern; do not hide cost, destructive effects, or safety conditions behind links.
Check command references, examples, installation or migration instructions, and entrypoints for stale behavior.
Preserve exact contracts, conditions, exceptions, and required lookup paths when revising.
When consolidating instructions, use the [consolidation check](../holistic-writing/references/consolidation.md).

## 4. Review and validate the documentation

Follow the intended reader's route from its starting state through the task or lookup to the expected result.
Check that prerequisites arrive before dependent actions and warnings before their hazards.
Check that authoritative owners, supported versions, limitations, and unresolved decisions remain clear.
For substantial drafting or rewriting, use `holistic-writing` for the complete reading experience; do not substitute this task-route check for prose judgment.

Validate the final consumer-visible representation with applicable renderers or compilers and repository documentation checks.
Check changed links, commands, and examples; do not edit generated output directly.
Report what was inspected, failed or unavailable checks, skipped surfaces, and residual uncertainty.
Distinguish textual usability review from verified operational behavior.

For creation or edits, finish when the reader can start, find the authoritative information, and complete the intended task without session context.
Applicable validation must pass or have a reported limitation; required repository checks must pass.
For review-only work, finish with prioritized findings, evidence, consequences, smallest corrections, and explicit review limits, without unauthorized edits.
