# Documentation

Use these checks for documentation authoring or usability and correctness review, within the caller's established task.
Routine additions need checks of the changed text and links, not a whole-artifact pass.
Use `readme-writing` for introductory READMEs, `reorganize-docs` for page splits or navigation redesign, and [documentation placement](../../references/documentation-placement.md) for placement alone.

## What does the reader need?

Read the current page, nearest documentation entrypoint, authoritative inputs, and representative uses.
Reuse reader, purpose, evidence, destination, and decisions already established.
For new content, establish its canonical owner and destination.

Choose a form that serves the task:

- **Tutorial:** guide a learner through a safe, successful experience; state what she will build or understand and the starting state.
- **How-to:** state the task, prerequisites, expected result, and hazards for a competent reader.
- **Reference:** organize accurate, neutral facts for lookup; state the system, version, scope, and notation.
- **Explanation:** develop understanding through reasons, examples, and consequences.

Separate mixed needs within a page rather than imposing one template.
For an already selected design or implementation spec, read [design documents](design-documents.md); this does not authorize selecting a design or writing a human-owned brief.

## Can the reader start and finish?

Assume the reader opens the page directly months later.
State background, prerequisites, authoritative inputs, and limitations where needed to begin safely.
Use a glossary when many project-specific terms interact.
Link to each concept's canonical owner instead of copying its procedure.
Keep warnings about cost, destructive effects, and safety beside the affected actions.

Follow the reader's route from its starting state through the task or lookup to the expected result.
Do prerequisites arrive before dependent actions and warnings before hazards?
Are commands, examples, installation or migration instructions, and entrypoints current?
Check supported versions, limitations, and unresolved decisions.
Preserve exact commands, interfaces, paths, conditions, exceptions, and required lookup routes when revising.

Validate changed links, commands, examples, and rendered or compiled output with applicable repository checks.
Report what was actually exercised, what was only reviewed as text, and failed or unavailable checks.
A successful route check does not establish that the complete page reads well.
For review-only work, report findings and the smallest useful corrections without editing.
