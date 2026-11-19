---
name: holistic-writing
description: Write, substantially revise, or editorially review prose as a whole, including documentation and CLI --help text. Covers usability, correctness, explanatory development, reading experience, voice, and factual fidelity. When a dedicated skill owns the requested writing or review, start there and follow its editorial-pass route. Not for merely running --help to inspect a command, contract, conformance, or completion audits alone, documentation placement or tree restructuring, design selection, human-owned product briefs, or bounded local polishing (use tighten-prose).
---

# Holistic writing

Write for someone who was not in the conversation, investigation, or design session.

## Establish the task

What should this reader understand, feel, or do after reading?
Establish the artifact, reader, purpose, factual inputs, and permission to write or review.
For new writing, inspect the material it must explain and the intended destination.
Ask about missing context when it could materially change the result.
Reuse context and decisions already supplied by another procedure.

A review request authorizes findings, not edits.
Leave specialized decisions with their owners; prose work does not authorize selecting a design, changing requirements, or rewriting a human-owned product brief.

## Write and revise

Read and follow the [shared editorial pass](references/editorial-pass.md).
Dedicated skills also call that pass directly; do not restart this entry point when they have established the task.

For user-facing diagnostic writing or review, read [diagnostic design](../references/diagnostic-design.md) for the jobs of messages and labels and the distinction between diagnosis and proposed repair.
For CLI help writing or review, read [CLI design](../references/cli-design.md) for the execution and interface contracts the text must describe.
These routes apply to prose-only work; they do not require a coding workflow or authorize changing command behavior.

For documentation-specific forms, prerequisites, commands, and reader workflows, read the [documentation checks](references/documentation.md).
For placement alone, use [documentation placement](../references/documentation-placement.md).
Use [readme-writing](../readme-writing/SKILL.md) for audience guidance when documentation serves project newcomers, regardless of filename or stage of use.
When a technical skill owns the work, retain its factual and technical checks; combine the guidance with one task setup and one shared editorial pass.
Existing page splits, renames, and navigation belong to `reorganize-docs`.
