---
name: readme-writing
description: Write, substantially revise, or review a repository, package, or tool-entrypoint README that introduces a project and helps readers decide whether or how to use it. Use for introductory READMEs, including libraries, integrations, books, and non-executable collections. Not for API-reference-only tasks, general documentation restructuring, implementation, or verification of product claims.
---

# Write a README for someone arriving

Write the account the reader needs, not an introduction attached to the old manual.
The source supplies facts, not a requirement to reproduce every feature, section, or contract.
For an introductory brief, select one useful operation or thought and develop it through the whole README.
A shorter, self-contained replacement is valid; retaining the source's complete reference is not the default.

This skill is sufficient to begin a README; do not load every broader writing workflow by default.
Use `holistic-writing` for general whole-artifact reading guidance and `tighten-prose` for bounded local polish.
Use [documentation placement](../technical-docs/references/placement.md) to choose owners for new documentation.
Use `reorganize-docs` when extracting or moving existing material, or judging navigation and the documentation set.
Those routes do not expand the task's write permission.

## Understand the project and the brief

Read the human brief and the complete source README, if one exists.
Establish which files the task authorizes you to change or create before writing.
For review-only work, report findings without editing.
Follow supplied repository context when you need to establish what the project does or how an operation works.
Resolve relative links from the original README location, not the storage location of a copied input.
Keep the human's reader, purpose, and request; do not replace them with a more convenient brief.
For an introduction with no stated audience, consider a project newcomer who has not read the related documentation.
Do not make that reader learn the whole field, but do not assume familiarity with the project's private names.

Establish what someone wants to do, what they provide or choose, what the project supplies, and what happens as a result.
Distinguish working behavior from plans and aspirations.
If the source cannot establish the basic purpose, report the specific missing fact rather than filling the gap with terminology.

Read [the examples](references/examples.md) before drafting.
They show complete introductory development as well as sentence-level choices; they are not templates every README must copy.

## Build an explanation, then select the detail

Choose a useful action or line of thought that develops the purpose.
Begin with that account rather than inheriting the source's section order.
Keep effective existing prose when it already serves the reader.

Explain relationships through actions: who does what, what changes, and why the next step follows.
Naming a mechanism does not explain it.
If a definition depends on several other unfamiliar terms, develop one use in ordinary language before introducing the classification.
The reader should gain understanding as the explanation proceeds, not keep translating one project term into another.

Use a concrete illustration where it makes a relationship understandable.
For a conceptual method, an explicitly hypothetical situation can show the intended operation without claiming a successful experiment.
Keep its actions within what the supplied material supports.
Do not invent interfaces, commands, capabilities, guarantees, measurements, or observed results.
An illustrative scenario is not a product feature or evidence that a method works.

Let the benefit emerge from what the reader can do and what effort or limitation it addresses.
Do not substitute promotional adjectives for that account.
Keep the project's appropriate voice; clear writing need not be chatty, cheerful, or simple-minded.
Use concrete subjects and verbs, and retain specialized terms when they do precise work.
Avoid making the reader pass through abstract classifications to reach an ordinary action.

Select details by the use you chose, not by whether the source documents them.
Keep the prerequisites, conditions, hazards, and limits needed for that use at the point of action.
Preserve exact tokens in commands, interfaces, quoted output, and paths when you use them.
Preserving product behavior means describing it accurately; it does not require documenting every other operation's contract here.
Keep requirements from the human brief, even when they require a broader account.
Use inspected existing documentation or source destinations for later tasks.
When useful and authorized, create linked supporting documents with complete content for their own reader tasks.
Not every README needs multiple files.
Move migration procedures, configuration catalogs, and other specialized detail to real supporting owners when that improves the introduction.
Use `reorganize-docs` for that extraction; preserve the constraints needed for the README's selected use beside its actions.
Never invent a destination or link to a promised page without creating it.
If supporting-file edits are outside the authorized scope, keep necessary detail here or report the missing owner rather than silently widening scope.

Choose sections after you know what they develop.
A table is useful for actual choices or lookup, not as a replacement for explaining how parts work together.
Do not follow a table with the same list rewritten as a summary.
Retain repetition that helps this reader; remove repeated explanations that demand attention without adding understanding.

## Finish the whole artifact

Produce the complete README you selected, not a partial replacement followed by the old manual.
When copying an existing file for modification, use `cp` and verify it with `cmp` before editing the copy.
A new account need not inherit the old structure; source length does not determine output length.
Do not leave placeholders, “rest unchanged,” promises to append a reference, or process commentary inside the README.

Read the entire result as prose, including the ending and any reference sections you retained.
Notice cadence, awkward compounds, delayed relationships, unsupported rhetorical force, and paragraphs that restart the same point.
Revise the writing that causes that friction; do not defend it merely because its facts are relevant.
A reader's ability to extract the information does not establish that the writing is satisfying to follow.
Check that the opening's account continues through the body rather than disappearing beneath an inventory.

## Review the README first, then its routes

First judge the complete README as prose on its own, including retained reference sections and the ending.
Does its chosen account develop understanding, or does it disappear beneath an inventory?
Do not credit explanations that appear only in unseen linked pages.
For independent source-blind prose review, supply the README without the source or drafting rationale; do not infer what unseen links contain.
An independent agent is optional, not a required step for every README.

Second, when linked pages matter to the selected use or changed documentation, follow those routes and judge each page by its own role.
A configuration reference should support lookup; a migration procedure should make the transition and its hazards clear.
Use `reorganize-docs` to judge navigation or the set of documents, not a giant concatenation treated as one compulsory introduction.
Supporting pages must be edited for their readers, not used as a dumping ground for unedited source prose.
Keep the README prose judgment separate from supporting-page and navigation findings; do not combine them into a score.
If linked material cannot be inspected, report that limit rather than imply that the documentation set was verified.

Keep the source and other repositories unchanged unless the task authorizes those edits.
Report factual uncertainty, incomplete work, and checks not performed outside the README.
Do not claim rendering, link checks, or product verification merely because you reviewed the prose.
