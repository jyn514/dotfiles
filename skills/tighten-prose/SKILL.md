---
name: tighten-prose
description: Polish wording, diction, sentence rhythm, repetition, and local clarity in existing prose. Use for explicit local edits to sentences or short passages within an established explanation, including comments and docstrings, docs, reports, specifications, prompts, instructions, and skills. Also use for bounded, fact-supported corrections to diagnostic or help text. Do not use for whole-artifact editorial judgment, restructuring, developing missing explanations, or consolidating policies. Do not apply to executable code, generated assets, or machine-owned data.
---

# Tighten prose

Improve the requested passage within its established purpose and explanation; preserve its meaning except for an authorized, fact-supported local correction.
Local scope limits the changes, not the context you may read to make them well.
A prose-only edit in a source file does not itself require a coding workflow or authorize changes to behavior or guarantees.
For documenting a helper during implementation or changing a caller contract, use [coding judgement](../coding-judgement/SKILL.md) and its code-structure route.
A polished passage does not establish that the whole artifact works.

When error or diagnostic wording involves explaining a failure or suggesting recovery, consult [diagnostic design](../references/diagnostic-design.md).
When CLI help wording involves invocation or behavior, consult [CLI design](../references/cli-design.md).
A spelling or punctuation correction alone needs neither reference.
For a requested local correction to misleading diagnostic or help content, use established facts to correct the text within that scope.
These checks do not authorize changing command behavior or guarantees.

## Revise locally

1. Read the requested passage and enough surrounding text to understand its reader, intended voice, and role.
   Do not expand a local request into a document-wide rewrite.
2. Improve the wording and cadence; remove repetition, vague phrasing, and canned rhetoric where they weaken the passage.
   For individually clear sentences that form a difficult paragraph, [follow the paragraph's thread](#follow-the-paragraphs-thread).
   For an important word that feels approximate or merely adequate, [explore its meanings](#explore-an-adequate-word).
   For a sentence that sounds like a maxim, insight, or takeaway, use the [paraphrase test](#test-apparent-takeaways).
   Join, split, or rewrite sentences when they read better, not merely to shorten them.
   Prefer familiar words and verbs that name the action.
   Avoid [telegraphic compression](../holistic-writing/references/reading-examples.md#compression-can-hide-the-condition-and-actor) that leaves necessary relationships implicit.
   Preserve useful emphasis, precise domain terms, deliberate casing, fragments, and idiom.
   Apply vocabulary bans by meaning rather than word matching.
   When a sentence hides an action in a noun, try naming who does what.
   Keep the noun form when it provides useful emphasis or names an established concept.
   For example, “The migration took twelve minutes” keeps attention on the migration's duration rather than who performed it.
   Unpack stacked nouns and unfamiliar word combinations when readers must guess how their parts relate.
   Preserve established technical terms; flag missing meaning rather than inventing a relationship.
   Distinguish timing (for example, “while” or “after”) from cause (“because,” “causes,” or “therefore”).
   When evidence establishes causation, name the action and consequence rather than leaving their relationship implicit in temporal wording.
   Do not infer causation from sequence or coincidence alone.
3. Preserve meaning except for an authorized, fact-supported local correction; preserve conditions, authority, warnings, exact tokens, quoted output, commands, paths, and links.
   Do not remove evidence or requirements, invent facts, move sections, or change the explanatory plan.
4. Read the complete revised passage in context and compare it with the original as prose.
   Restore anything that sounded better before; leave the passage unchanged if no edit earns its cost.
   Explain consequential choices and any unresolved issue, not an edit count.

If the problem requires broader content changes, reorganization, or a developed explanation, flag the broader work rather than trying to solve it through wording alone.
Use a dedicated skill when it owns the requested work; otherwise use `holistic-writing`.
Do not claim the whole artifact has passed editorial review.

## Local techniques

### Follow the paragraph's thread

When sentences are individually clear but the paragraph is difficult to follow, underline their openings and inspect the sequence of subjects.
What does each sentence pick up from the preceding one, and what does it introduce?
Try placing the connection near the beginning and the important new information at the sentence's grammatical completion.
Compare the resulting paragraph with the original; do not impose this order where another progression works better.
Choose subject and voice partly by what the reader is already following.
Passive voice can preserve that connection; changing to active voice does not automatically improve the passage.
See the [early-cutoff comparison](../holistic-writing/references/reading-examples.md#follow-the-unchanged-output) for a paragraph that follows the output from one sentence to the next.

### Explore an adequate word

When an important word feels approximate or merely adequate, consult its dictionary definitions rather than just a synonym list.
Use the meanings to explore a better word or phrase, then compare the alternatives in context.
Keep the original when it does more; definitions can inform figurative wording without forbidding it.
See the [dictionary keepers](../holistic-writing/references/reading-examples.md#keep-words-that-earn-their-place) for two lookups that support leaving the wording alone.

### Test apparent takeaways

When a sentence sounds like a maxim, insight, or takeaway, restate it in plain, literal words.
Does it explain something, or merely give the preceding material the sound of a conclusion?
If its contribution disappears in paraphrase, compare the passage without it.
See the [caching-paragraph comparison](../holistic-writing/references/reading-examples.md#paraphrase-the-takeaway) for a fluent sentence whose apparent insight disappears when restated.

## Example: name the distinction directly

> SQLite’s in-process architecture, for example, represents a different paradigm from a daemon-based database design.

Compare:

> SQLite runs in-process instead of as a daemon.

The revision names the same engineering contrast without making it sound grand.
Use the contrast to guide judgment, not to impose this style on every passage.

## Delegate the bounded pass

Prefer a small-model subagent for a useful batch of passages or independent wording judgment; this reduces subscription usage.
Apply an exact replacement or an edit smaller than its handoff directly.
When delegating, use [delegation](../delegation/SKILL.md) for shared responsibility and its [self-contained assignment procedure](../delegation/SKILL.md#give-a-self-contained-assignment) to frame the bounded assignment.
Supply the exact passage, necessary context, and requirements to preserve.
The worker follows the workflow directly without further delegation; the parent reads its revision before its report.
If a useful delegation is unavailable, perform the local pass directly and report that limitation.
