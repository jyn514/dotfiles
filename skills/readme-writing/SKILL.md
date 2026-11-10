---
name: readme-writing
description: Write, substantially revise, or review a repository, package, or tool-entrypoint README that introduces a project and helps readers decide whether or how to use it. Use for introductory READMEs, including those for libraries, integrations, books, and non-executable collections. Not for API-reference-only tasks, general documentation restructuring, implementation, or verification of product claims.
---

# Write a README for someone arriving

Help the reader decide whether this project serves them, then explain how to begin.
Use the source's facts to build an account for that reader.
For review-only work, report findings without editing.

## Find the reader's reason to care

Read the brief and complete existing README, if present.
Establish which files you may change or create; leave others unchanged.
Inspect supplied repository context for facts you need; resolve copied input's links from the original README location.

Keep the human's audience and purpose.
Without a stated audience, write for a project newcomer who has not read related documentation.
Establish what the reader already understands.
Someone choosing among background-job libraries may know the category and want to understand what this particular one offers.
Explain its value and introduce its private names through their meaning.

What does the reader want to do or understand?
What do they supply, what does the project do, and what remains their responsibility?
Distinguish working behavior from aspirations; report missing facts rather than filling gaps with terminology.
Read the [real and constructed examples](references/examples.md) before drafting.

## Decide what you will write

Before drafting, decide what you want to accomplish for this reader and how the writing will accomplish it:

- What should they understand or be able to do afterward?
- What part of the project will you develop to bring them there?
- Which comparisons, examples, explanations, and routes will help them make that progress?

Choose the material, its depth, and its order from those answers, then give it headings that help readers follow or find it.
Keep existing prose that serves the account you've chosen.

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

Hypothetical examples can explain a method, not establish its success.
Label them and stay within supplied capabilities.
Do not invent interfaces, commands, guarantees, measurements, or observed results.
Preserve exact tokens in commands, interfaces, quoted output, and paths.

## Select detail by the reader's task

For the queue's introductory use, the shared database explains how the processes cooperate and the repeated-handler warning guides safe use.
A tracing callback catalog serves readers configuring tracing; give those details an appropriate lookup destination.
Select details for the account you've chosen and describe the operations accurately.
Keep prerequisites, conditions, hazards, and limits beside the actions they govern.
Use tables to make choices comparable or facts easy to look up, and prose to develop relationships.
Give each a distinct purpose.

Link to inspected documentation or source for further detail.
Create supporting pages only when useful and authorized; never promise nonexistent destinations.
Use `reorganize-docs` for extraction, moves, and navigation.
Edit each destination for its own reader task rather than dumping cut prose there.
If supporting edits are outside scope, keep necessary detail here or report the missing owner.
A small project may need no supporting pages.

## Read the whole result, then follow its links

Deliver the complete README without placeholders or process commentary.
Read through the ending and retained reference sections.
Compare the reading with your intentions: what can the reader now explain, choose, or do?
How does each section contribute, and where does the reader need more development or a clearer connection?
Read for cadence, emphasis, and the experience of following the account.
Cut repeated explanations and revise awkward or delayed relationships so the prose rewards attention.

The [shared editorial pass](../holistic-writing/references/editorial-pass.md) can guide this reading without restarting the task.
Use the [documentation reference](../holistic-writing/references/documentation.md) for documentation-specific checks and `tighten-prose` for local polish.

Judge the README before borrowing explanations from linked pages.
For optional source-blind review, supply it without the source or drafting rationale.
Then inspect links relevant to the selected use or changed documentation, judging each page by its task.
Report README prose findings separately from supporting-page and navigation findings, not as a combined score.
Report unread material, unresolved facts, and unperformed checks separately from the README.
Prose review does not establish rendering, working links, or product behavior.
