---
name: technical-docs
description: Create or substantively edit standalone technical documentation, or review it for reader usability and technical correctness. Use for READMEs, tutorials, how-to guides, reference pages, explanations, and design documents. Do not use for prose-only tightening, skill authoring, documentation information architecture, or review-only design/spec consistency or completeness work; route those to their owning skills.
---

# Technical documentation

Write for readers without the originating conversation, investigation, or design session.

## Scope and routing

This skill owns document substance, reader structure, examples, evidence, and technical correctness.

Route narrower work when its owning skill is available:

- `new-tool-development` owns the lifecycle workflow for a new independently invoked tool, CLI, service, or reusable executable subsystem; this skill still owns routed product-brief and implementation-spec writing.
- `requirements-definition` alone owns requirements authoring from an approved product brief.
- `tighten-docs` owns prose-only requests to make existing documentation shorter or clearer without changing its structure or technical content.
- `spec-review` owns review-only consistency and completeness analysis of a design or specification.
- `skill-authoring` owns skills.
- `reorganize-docs` owns multi-page information architecture, consolidation, splits, renames, archives, and navigation.
- `typst` owns Typst markup syntax; this skill still owns the document's content and reader structure. Load both when writing a technical design in Typst.

If a named skill is unavailable, preserve these ownership boundaries. State the limitation, use repository conventions and available validators, and do not claim that the missing specialized review occurred.

A request to review does not authorize edits. For review-only work, report findings, evidence, consequence, and the smallest useful correction. Edit only when the user requests changes.

Route lifecycle work to `new-tool-development` and requirements authoring to `requirements-definition`; do not reproduce their procedures. Draft only the requested stage.

## 1. Identify the reader and document form

Identify:

- who will read the document;
- what background it may assume;
- whether she needs to learn, perform a task, look up facts, understand a design, or review a decision;
- which artifact owns each fact or rule.

Keep Diátaxis forms distinct:

- **Tutorial:** guide a learner through a safe, successful experience.
- **How-to:** help a competent reader accomplish a specific task.
- **Reference:** present accurate, neutral facts structured like the subject.
- **Explanation:** develop understanding through context, reasons, examples, and consequences.

A design document is primarily explanation plus an implementation and verification contract. Within one page, separate mixed needs with clear sections or links. Route a multi-page split or navigation redesign to `reorganize-docs`.

## 2. Inspect before writing or reviewing

Read the current artifact, its entry points, linked documentation, source of truth, and representative consumers. Establish what is observed, selected, provisional, and unresolved.

Do not turn conversation context, search snippets, generated output, or an analysis script into unexplained authority. Preserve provenance for measurements and reconstructed decisions.

## 3. Make every form standalone

Assume the reader opens the document directly months later.

For every form:

- define project-specific terms before consequential use;
- state required background and prerequisites;
- identify authoritative inputs and important limitations;
- avoid references such as “the option we chose” unless the document names and explains that option;
- distinguish facts, decisions, proposals, examples, and unresolved questions.

Adapt the opening to the form:

- **Tutorial:** state what the learner will build or understand, prerequisites, and the safe starting state.
- **How-to:** state the concrete task, prerequisites, expected result, and important hazards.
- **Reference:** state the covered system, version, scope, notation, and lookup organization. Do not force motivation or design goals into neutral reference material.
- **Explanation or design:** explain the problem, goals, named proposal, and a concrete example before detailed machinery.

For explanations and designs specifically:

1. Explain the problem or motivation in ordinary language.
2. State goals and important non-goals.
3. Define the named proposal on first use. A title such as “selective hybrid,” “v2 pipeline,” or “new resolver” is not a definition.
4. Give one concrete example or trace showing the current problem and proposed behavior.
5. Use a glossary when many project-specific terms interact; use inline definitions when only one or two are needed.
6. State the audience and assumed background when either is not obvious.

## 4. Order explanation before machinery

For nontrivial designs, use this progression unless the artifact has a stronger natural structure:

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

## 5. Define evidence rather than displaying numbers

For each important measurement, explain:

- the population or denominator;
- what was counted;
- the input revision, source, or time range;
- the method or policy used;
- what the number demonstrates;
- what it cannot demonstrate;
- whether it is provisional or an acceptance constant.

Prefer a labeled table or definition list over an uninterrupted wall of figures. Comparative claims must include the alternatives and their comparable results, not merely the winning conclusion.

## 6. Keep precision without front-loading density

Include technical precision, but introduce it incrementally.

- Introduce one conceptual layer at a time.
- Put plain-language meaning before formal notation.
- Put a worked example before a general algorithm when practical.
- Explain why a schema or invariant exists before listing its fields.
- Keep requirements, examples, evidence, and unresolved decisions visibly distinct.
- Break long compound requirements into bullets or short paragraphs.
- Give one concept one canonical owner and refer back to it instead of redefining it.
- Preserve exact API, serialization, failure, and lifecycle contracts after the reader has the model needed to understand them.

Do not remove necessary detail merely to shorten a document. Move detail later, label it, or derive it from a clearer authority.

## 7. Write designs for review

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

Write design documents in Typst by default when the `typst` skill and compiler are available. Use Markdown when repository convention, tooling, or the requested destination requires it.

## 8. Review from a fresh-reader position

For create or edit work, perform a standalone-reader pass before completion. For review-only work, use the same questions as review criteria:

- Can the title and opening be understood without session context?
- Is every named policy, architecture, or migration defined?
- Are terms defined before consequential use?
- Does each number have meaning and provenance?
- Do examples appear before the abstractions they explain?
- Are single-item and composed or multistage cases treated consistently?
- Can the reader distinguish facts, decisions, proposals, and unresolved questions?
- Could another engineer implement or review the design without inventing policy?

## 9. Validate and report

For create or edit work:

- validate the final consumer-visible representation, not only source syntax;
- compile or render when an applicable tool exists;
- check links, examples, and repository documentation checks when available;
- do not edit generated output directly;
- report checks run, failures, unavailable checks, skipped surfaces, and residual uncertainty.

After creating or substantially rewriting documentation, invoke `tighten-docs` when available; reject cuts that remove context, definitions, examples, rationale, constraints, or reviewability. If it is unavailable, perform a focused concision pass using the same safeguards and report that limitation.

For review-only work, completion is a prioritized findings report with evidence, consequences, smallest corrections, and explicit review limits. Do not require or imply a rendered artifact unless rendering is relevant to the review.

## Completion condition

Create or edit work is complete when the intended reader can understand and use the document without the originating conversation; consequential claims have an authority or stated uncertainty; applicable validation passes or its limitation is reported; and required repository checks pass.

Review-only work is complete when the requested scope has been inspected, material findings and uncertainty are reported, and no mutation occurred without authorization.
