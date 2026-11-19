# Documentation conventions and placement

Read before editing documentation, prose source, or agent instructions, or drafting GitHub discussions or comments.
This applies even when the owner and destination are already known.
Placement alone does not require a whole-artifact writing workflow.
Restructuring existing pages or navigation belongs to `reorganize-docs`.

When changing behavior, update affected documentation, including code comments, in the same change.
For user-facing changes, check canonical documentation, entrypoints, examples, command references,
and installation or migration instructions for stale behavior before declaring the work complete.
Do not duplicate guidance for reminder, reinforcement, or visibility.
Add a link from another entrypoint only when an observed discovery failure needs
one, and do not repeat the guidance there.

1. Name the reader and the decision, action, or understanding the content serves.
   Omit content with no such purpose; do not document a detail merely because it
   changed during implementation.
2. Read the nearest documentation entrypoint and existing owner before choosing
   a destination. Prefer an existing task or subsystem page to a new page.
3. Match the content to its scope:
   - Root README: repository-wide orientation, common starting instructions, and
     routes to specialized tasks—not an inventory of subsystem internals.
   - Subsystem or task documentation: usage, prerequisites, observable contracts,
     hazards, recovery, and reader-relevant limitations.
   - Code documentation: caller-facing purpose and usage contracts beside declarations;
     implementation rationale, algorithm summaries, and non-obvious constraints beside the relevant code.
     Keep operator instructions and guarantees between independently maintained components in their documentation.
4. Link to the owner from relevant entrypoints rather than copying its content.
   Keep safety constraints needed at the point of action; do not make a reader
   follow a link to discover that a command costs money or can destroy data.

For example, document compaction replay cost and failure recovery in operator
instructions. Keep a saved checkpoint offset's encoding beside the code that
reads and writes it; document the resulting replay limitation for operators. An
internal capture timeout belongs in a README only if readers need it to diagnose
or operate the system.

For a small addition to an established section, validate the changed text and links.
A new heading alone does not require a whole-artifact workflow.
Use [holistic-writing](../holistic-writing/SKILL.md) for whole-artifact authoring,
substantial revision, or editorial review, including documentation usability or
correctness reviews and prose outside documentation.
Its [documentation reference](../holistic-writing/references/documentation.md)
covers documentation-specific reader tasks, forms, prerequisites, and workflow checks.
Use `readme-writing` for documentation whose audience is new to the project, regardless of filename or stage of use.
No sequence of writing skills is required.

## Documentation is for humans, skills are for agents

Keep project policies in human-facing documentation.
Keep procedures in `AGENTS.md`, skills, or skill references.
Reuse existing supported commands or scripts for human-executed procedures.
Creating missing automation requires implementation authorization.
Document an overview of what the command or script does and why.
If the procedure cannot be scripted, use `ask_user` to ask what to do.

### Keep session state out of maintained documentation

Document reusable behavior, current contracts, adopted decisions and their rationale in impersonal terms.
Describe the resulting rule, not who approved it or the conversation that selected it.
Do not include agent or session identifiers, approval-message quotations, conversational instructions, worker status, or a session's temporary workspace names, one-off debugging commands and repair chronology.
Source citations, adoption dates and product versions belong only when they serve the reader's task; approval transcripts are not a substitute for stating the decision.

A documented command must serve a maintained, repeatable reader workflow with declared inputs and prerequisites.
Do not copy a successful session command into a guide merely because it worked once.
Use the workflow's supported interfaces and parameters rather than a session's temporary paths or helper scripts.
Do not turn a temporary helper into a maintained tool just to justify documenting it.

Do not include per-run build or test receipts, test-count summaries, or completion histories in maintained documentation, even when a future reader could use them.
Extract the reusable finding, limitation or instruction that belongs to the page's purpose.
Keep necessary supporting receipts in the owning issue or report, and link to them rather than copying them.
Use [durable records](durable-records.md) to decide which investigation and authorization evidence merits retention and where it belongs.

## Prose source formatting

In prose source, use one sentence per line when rendering joins those lines into paragraphs, so diffs are easier to review.
For GitHub discussion or comment text where newlines become visible breaks, keep each prose paragraph on one source line instead.
When using sentence-per-line formatting, semicolons may count as a line break.
Try to keep those source lines under 150 columns wide.

## Agent instruction files

Treat `AGENTS.md` as an early routing and correction layer.
Keep agent operating instructions, task routes, and execution constraints here.
Link to canonical project policies instead of copying them into agent instructions.
