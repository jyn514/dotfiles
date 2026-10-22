---
name: tighten-docs
description: Make docs, specs, prompts, instructions, and skills clearer and shorter. Use for explicit prose-tightening requests and before completion after creating a substantial document or substantially rewriting documentation, specifications, prompts, instructions, or skills. For short documents or localized edits without an explicit tightening request, review prose directly without loading this skill. Do not apply to code, generated files, or machine-owned data.
---

# Tighten Docs

Make the document satisfying to follow, not merely easy to extract information from.
Good prose gives readers precise distinctions, developed relationships, well-judged emphasis, and a voice suited to its purpose.
A reference can offer clear alternatives and useful independent sections; an explanation can develop a thought across paragraphs.
Neither earns a good reading experience merely by containing useful material.

## What an improvement looks like

### Reach the distinction without an abstract detour

> SQLite’s in-process architecture, for example, represents a different paradigm from a daemon-based database design.

Compare:

> SQLite runs in-process instead of as a daemon.

The second sentence puts the actual contrast in front of the reader.
The first makes the reader pass through “architecture,” “represents,” and “different paradigm” to reach it, with an inflated manner for engineering readers.
The improvement is that direct relationship, not a rule against long sentences or technical terms.

### Develop the thought when a conclusion is not enough

> Feature flags add complexity.

Compare:

> Each independent on/off flag doubles the possible configurations.
> Keeping a flag means continuing to support both paths and their interactions with other flags.

The longer version gives the reader a mechanism to think with, rather than just a verdict.
Keep development that repays the reader's attention; cut detail that does not.
This does not require a worked example of every application, or authorize inventing facts about the system being documented.

### Let a relationship organize the paragraph

> A failed build leaves readers on the current index.
> Refresh builds a new index.
> Readers use the current index during the build.
> The new index replaces the current one only after the build succeeds.

Compare:

> Refresh builds a new index while readers keep using the current one.
> The new index replaces it only after the build succeeds; if the build fails, readers stay on the current index.

The first paragraph makes the reader assemble four detached facts.
The revision follows the refresh in time, keeping the readers' experience alongside the build and its possible outcomes.
Its improvement comes from relating the facts, not changing their terminology or putting them under another heading.
Apply the reasoning in these examples, not their surface style: formality, fragments, repetition, and a restrained voice can all serve the reader.

## Delegate the prose pass

The main agent delegates this skill to a small-model subagent to reduce subscription usage.
Use [delegation](../delegation/SKILL.md) for the assignment and integration.
Supply the reader's task, the reading problem if known, and the requirements to preserve.
For document-level work, supply the complete artifact.
The subagent runs the workflow directly, without further delegation; the parent reads its complete revision before its edit report.
If small-model delegation is unavailable, the main agent runs the workflow and reports that limitation.
One completed pass meets the post-rewrite requirement for the reviewed files, including this skill.
Check corrections within that pass; they do not require another pass.

## Revise and judge the result

1. **Read the whole artifact and choose the work.**
   Identify the reader's task and where following the prose becomes satisfying, awkward, tedious, or unrewarding.
   If no reading problem warrants a revision, use the unchanged outcome below.
   Choose a structural revision when arrangement causes the problem, or a local revision when the surrounding structure works.
   Preserve needed lookup paths without assuming the current headings or section boundaries are necessary.

2. **Write the revision.**
   Develop connected passages together, introducing concrete distinctions before abstractions when that helps.
   Use paragraphs to develop thoughts, bullets for distinct actions or alternatives, and tables for comparisons.
   Preserve effective voice, emphasis, and precise domain terms; do not normalize deliberate casing, fragments, or idiom just for consistency.
   Explain specialist terms when the reader needs it, and apply vocabulary bans by meaning rather than word matching.
   Keep required warnings beside the actions they govern.

3. **Read the complete result before defending edits.**
   Does it resolve the reading problem through its wording, rhythm, selection, or development?
   Judge the whole, including dull stretches; useful sections and cosmetic changes do not establish improvement.
   Compare with the original as prose and restore anything that reads better there.
   An unchanged result is preferable to edits made merely to demonstrate effort.

4. **Check meaning and use.**
   Preserve governing requirements, priority, authority, observable behavior, public API details, and compatibility promises.
   Account for conditions, exceptions, commands, paths, defaults, validation, and example-only behavior.
   Keep rationale, rejected alternatives, and examples that change a future choice or prevent a likely mistake; cut explanations that merely announce that a rule is good.
   Implementation detail owned by code need not remain in user docs unless it affects a reader's action or understanding.
   Check revised sections independently and follow changed routes and references.
   Readers must still find their first action, applicable constraints, and required validation.
   For skills, preserve every discovery trigger in the YAML description and check linked references and examples.

5. **Report the reading judgment, not an edit tally.**
   Support it with representative passages and sustained patterns, then explain consequential preservation decisions, actual reversions, uncertainty, and any unread or excluded scope.
   Before reporting missing guidance, read the complete relevant section in both versions and follow any replacement route; cite exact locations.
   A prose review does not establish operational correctness.

## When consolidating instructions

Compare required behavior and conditions before calling two policies duplicates.
“Prioritize clarity → precision → concision” ranks goals; “Use concise, clear language” directs writing style.
Neither replaces the other, though they can be presented together.
Likewise, a conditional heading changes the scope of every instruction beneath it: keep unconditional rules outside that condition.

Keep one authoritative owner for duplicate policy, with direct, task-specific references from affected entry points.
Distinct lookup routes to that owner are usually worth keeping; test each entry point before removing one.
A link must say why the reader needs it, not merely “See testing.md.”
Preserve useful two-level routing such as task → owner → focused topic; flatten it or add a short local guard if the operative rule takes more than three hops to reach.
Keep a repeated safety constraint at the point of action when its absence permits a concrete misunderstanding or unsafe action.
Otherwise, test deletion or a direct reference rather than preserving text solely because it existed.

## When no revision earns its cost

Explain why the complete artifact reads well, including the strongest concrete revision considered and why the original works better.
“Every section has a purpose” does not settle that question.
Say “No further eligible cuts identified,” not “already tight enough” or that no improvement is possible.
If the judgment lacks concrete support, the parent arranges a bounded independent whole-document reading through [delegation](../delegation/SKILL.md), or reports that independent review is unavailable.
If that reading finds a missed improvement, withdraw the verdict and reconsider the affected scope.

## Skill-specific rules

Keep `SKILL.md` procedural and short.
Move bulky examples or variant detail to directly linked references, read only when needed.
Delete generated template text; do not add a README, changelog, quick reference, or process notes to a skill.
