---
name: tighten-prose
description: Polish wording, diction, sentence rhythm, repetition, and local clarity in existing prose. Use for explicit local edits to sentences or short passages within an established explanation, including docs, reports, specifications, prompts, instructions, and skills. Do not use for whole-artifact editorial judgment, restructuring, developing missing explanations, or consolidating policies; use holistic-writing. Do not apply to code, generated files, or machine-owned data.
---

# Tighten prose

Improve the requested passage within its established purpose, meaning, and explanation.
Local scope limits the changes, not the context you may read to make them well.
A polished passage does not establish that the whole artifact works.

## Revise locally

1. Read the requested passage and enough surrounding text to understand its reader, intended voice, and role.
   Do not expand a local request into a document-wide rewrite.
2. Improve the wording and cadence; remove repetition, vague phrasing, and canned rhetoric where they weaken the passage.
   Join, split, or rewrite sentences when they read better, not merely to shorten them.
   Preserve useful emphasis, precise domain terms, deliberate casing, fragments, and idiom.
   Apply vocabulary bans by meaning rather than word matching.
3. Preserve meaning, conditions, authority, warnings, exact tokens, quoted output, commands, paths, and links.
   Do not remove evidence or requirements, invent facts, move sections, or change the explanatory plan.
4. Read the complete revised passage in context and compare it with the original as prose.
   Restore anything that sounded better before; leave the passage unchanged if no edit earns its cost.
   Explain consequential choices and any unresolved issue, not an edit count.

If the problem requires different content, organization, or a developed explanation, flag it for `holistic-writing` rather than trying to solve it through wording alone.
Do not claim the whole artifact has passed editorial review.

## Example: name the distinction directly

> SQLite’s in-process architecture, for example, represents a different paradigm from a daemon-based database design.

Compare:

> SQLite runs in-process instead of as a daemon.

The revision names the same engineering contrast without making it sound grand.
Use the contrast to guide judgment, not to impose this style on every passage.

## Delegate the bounded pass

Prefer a small-model subagent for a useful batch of passages or independent wording judgment; this reduces subscription usage.
Apply an exact replacement or an edit smaller than its handoff directly.
When delegating, use [delegation](../delegation/SKILL.md) for the assignment and integration.
Supply the exact passage, necessary context, and requirements to preserve.
The worker follows the workflow directly without further delegation; the parent reads its revision before its report.
If a useful delegation is unavailable, perform the local pass directly and report that limitation.
