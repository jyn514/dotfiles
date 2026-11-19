---
name: readme-writing
description: Write, substantially revise, or review documentation for readers new to a project. Use when the document must introduce project-specific concepts, explain how its parts fit together, or help readers choose and perform tasks without prior project context, regardless of filename. Readers may already know the domain. Specialized skills retain technical analysis and design decisions; this skill owns explaining the result to newcomers. Not for bounded wording or command corrections, documentation restructuring alone, implementation, or verification of product claims.
---

# Write for someone new to the project

Help readers understand the project well enough to make the choices or perform the tasks the document serves.
Use the source's facts to build an account for that reader.
For review-only work, report findings without editing.

When another skill owns technical analysis, operating behavior, or design decisions, leave those responsibilities there.
Use its established facts and decisions to explain the result to newcomers; reuse the reader setup and shared editorial pass rather than repeating them.

## Find the reader's reason to care

Read the brief and complete existing document, if present.
Establish which files you may change or create; leave others unchanged.
Inspect supplied repository context for facts you need; resolve copied input's links from the original document location.

Keep the human's audience and purpose.
Without a stated audience, write for a project newcomer who has not read related documentation.
New to the project does not mean new to its domain; establish what the reader already understands.
Someone who has installed the project may still need an introduction to its concepts, codebase, contribution process, or troubleshooting.
Someone choosing among background-job libraries may know the category and want to understand what this particular one offers.
Explain its value and introduce its private names through their meaning.

What does the reader want to do or understand?
What do they supply, what does the project do, and what remains their responsibility?
Check the current intended use against the inherited description; an accurate older feature need not remain the introduction's emphasis.
The [gh2md revision](references/examples.md#lead-with-the-current-use-not-the-inherited-output) shows this choice without changing the basic structure.
Distinguish working behavior from aspirations; report missing facts rather than filling gaps with terminology.
Read the [real and constructed examples](references/examples.md) before drafting.

## Decide what you will write

Before drafting, [choose how the writing will accomplish its purpose](../holistic-writing/references/editorial-pass.md#choose-how-the-writing-will-accomplish-its-purpose).

For a reader familiar with shell filters, jq's comparison can establish its role briefly and lead into documentation or experimentation.
For someone choosing among Python tooling workflows, uv's comparisons help locate familiar tasks; examples then explain how uv performs them.
A queue introduction can develop the relationship between submitting work and running it.
A collection of field guides can help readers recognize their situation and choose a guide.
In each case, the structure serves a particular understanding or action.

## Explain unfamiliar relationships

In the queue example, “durable job coordination with worker orchestration” names mechanisms.
“A web process stores a job in PostgreSQL; a worker reads it and runs the handler you provide” assigns the work and connects the parts.
Now the reader can understand why both processes need the same database.

In that example, ask:

- After adding the job, who performs it?
- Does the library supply that work, or does the application supply a handler?
- If the worker stops or the handler fails, what happens to the job?

For a book or conceptual method, develop the corresponding thought or use.
Introduce private terms through concrete meaning and familiar language.
Make benefits tangible through what readers can do and the effort or limitation the project addresses.
Keep the project's voice and precise specialized terms.

Prefer actual output and representative workflows when demonstrating the project's usefulness.
A constructed fixture can clarify mechanics without being a good showcase; choose the example for what the reader needs to recognize.
Hypothetical examples can explain a method, not establish its success.
Label them and stay within supplied capabilities.
Do not invent interfaces, commands, guarantees, measurements, or observed results.
Preserve exact tokens in commands, interfaces, quoted output, and paths.

## Select detail by the reader's task

Select technical detail by what the newcomer needs to understand, choose, or do.
Introduce project-specific relationships before relying on them.
Link to the canonical owners of exhaustive schemas, algorithm rules, internal invariants, report-field catalogs, and acceptance protocols rather than reproducing them without a reader need.
For each such block, identify the understanding, choice, or action it enables.
If it only catalogs implementation details or exact contracts without developing that understanding, link to its inspected specification, reference, or code owner instead.
Putting task-oriented headings above a specification does not make it a usage guide.

Keep the minimum operational detail needed for the task, including prerequisites, important defaults, failure recovery, and warnings at the point of action.
For an input-directory README, show how to obtain inputs, choose the file to change, and use it; link to exact schemas and source-policy details rather than reproducing them.
Preserve source provenance, licenses, and operative constraints when moving material; do not delete them merely to shorten the README.

For the queue's introductory use, the shared database explains how the processes cooperate and the repeated-handler warning guides safe use.
A tracing callback catalog serves readers configuring tracing; give those details an appropriate lookup destination.
Select details for the account you've chosen and describe the operations accurately.
Explain when a reader would choose a feature, rather than merely listing modes or narrating their mechanics.
Lead with the routine path suited to the intended task; explain when a more expensive or exceptional operation is worth choosing.
Keep prerequisites, conditions, hazards, and limits beside the actions they govern.
Use tables to make choices comparable or facts easy to look up, and prose to develop relationships.
Give each a distinct purpose.

Link to inspected documentation or source for further detail.
Create supporting pages only when useful and authorized; never promise nonexistent destinations.
Use `reorganize-docs` for extraction, moves, and navigation.
Edit each destination for its own reader task rather than dumping cut prose there.
If supporting edits are outside scope, keep necessary detail here or report the missing owner.
A small project may need no supporting pages.

## Establish the command environment once

Use Bash for shell examples rather than adopting the author's personal interactive shell.
Establish installation and execution context once.
Use direct invocation when that context supports it; retain wrappers required for normal use or taught by the example.
Keep commands runnable in the stated context; do not strip a required launcher prefix.
Keep repository names, filenames, and other identifiers consistent across related steps.

## Read the whole result, then follow its links

Deliver the complete document without placeholders or process commentary.
Read through the ending and retained reference sections.
Compare the reading with your intentions: what can the reader now explain, choose, or do?
How does each section contribute, and where does the reader need more development or a clearer connection?
Read for cadence, emphasis, and the experience of following the account.
Cut repeated explanations and revise awkward or delayed relationships so the prose rewards attention.

The [shared editorial pass](../holistic-writing/references/editorial-pass.md) can guide this reading without restarting the task.
Use the [documentation reference](../holistic-writing/references/documentation.md) for documentation-specific checks and `tighten-prose` for local polish.

Judge the document before borrowing explanations from linked pages.
For optional source-blind review, supply it without the source or drafting rationale.
Then inspect links relevant to the selected use or changed documentation, judging each page by its task.
Report prose findings for the document separately from supporting-page and navigation findings, not as a combined score.
Report unread material, unresolved facts, and unperformed checks separately from the reviewed document.
Prose review does not establish rendering, working links, or product behavior.
