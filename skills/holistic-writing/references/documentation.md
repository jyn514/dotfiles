# Documentation

Use this reference for documentation-specific authoring decisions and usability or correctness reviews.
It supplements the whole-artifact writing guidance, not a separate workflow to restart.
Routine additions to an established section need validation of changed text and links, not a whole-artifact pass.
Use `readme-writing` for an introductory README; it remains independently usable.
Use `reorganize-docs` for existing page splits, renames, consolidation, archives, or navigation redesign.
For placement alone, use [Documentation placement](../../references/documentation-placement.md).

## Establish the reader's task

Read the current page, nearest documentation entrypoint, authoritative inputs, and representative consumers.
Reuse the established reader, purpose, evidence, destination, and decisions when another procedure has already supplied them.
Identify whether the reader needs to learn, perform a task, look up facts, understand a design, or review a decision.
Establish the canonical owner and destination for new content; retain the destination in a review unless relocation is requested.
Do not select a design or author a human-owned product brief as incidental documentation work.

## Choose the form

Keep these needs distinct without imposing a fixed page template:

- **Tutorial:** guide a learner through a safe, successful experience.
  State what she will build or understand, prerequisites, and the safe starting state.
- **How-to:** help a competent reader accomplish a specific task.
  State the task, prerequisites, expected result, and important hazards.
- **Reference:** present accurate, neutral facts structured like the subject.
  State the covered system, version, scope, notation, and lookup organization.
  Do not force motivation or design goals into neutral reference material.
- **Explanation:** develop understanding through context, reasons, examples, and consequences.
  Explain the problem, goals, and important non-goals before the proposal.

A design document combines explanation with an implementation and verification contract.
For an already selected design or implementation spec, use [Design documents](design-documents.md).
That reference does not choose the design or impose its progression on other documentation.
Within a page, separate mixed reader needs with clear sections or links.
Route a multi-page split or navigation redesign to `reorganize-docs` rather than treating it as incidental prose editing.

## Make starting points and routes usable

Assume the reader opens the page directly months later.
State required background, prerequisites, authoritative inputs, and important limitations where needed to begin safely.
Use a glossary only when many project-specific terms interact; state the audience and assumed background when either is not obvious.
Keep each concept's canonical owner clear and link from relevant starting points rather than copying its procedure.
Keep action-specific warnings beside the actions they govern: cost, destructive effects, and safety conditions must not be hidden behind links.
Check command references, examples, installation or migration instructions, and entrypoints for stale behavior.
Preserve exact commands, interfaces, paths, conditions, exceptions, and required lookup routes when revising.

## Validate the reader's workflow

Follow the intended reader's route from its starting state through the task or lookup to the expected result.
Check that prerequisites arrive before dependent actions and warnings before their hazards.
Check authoritative owners, supported versions, limitations, and unresolved decisions.
A successful route check does not substitute for judging the complete reading experience.
Validate changed links, commands, and examples and the final rendered or compiled representation with applicable repository checks.
Distinguish textual usability review from verified operational behavior; report failed or unavailable checks, skipped surfaces, and residual uncertainty.
Finish when the reader can start, find authoritative information, and complete the intended task without session context.
Review-only work reports findings and the smallest useful corrections without unauthorized edits.
