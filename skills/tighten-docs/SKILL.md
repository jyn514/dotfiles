---
name: tighten-docs
description: Make docs, specs, prompts, instructions, and skills clearer and shorter. Use for explicit prose-tightening requests and before completion after creating a substantial document or substantially rewriting documentation, specifications, prompts, instructions, or skills. For short documents or localized edits without an explicit tightening request, review prose directly without loading this skill. Do not apply to code, generated files, or machine-owned data.
---

# Tighten Docs

Make the document satisfying to follow, not merely easy to extract information from.
Sometimes the reader needs a direct distinction; sometimes a thought needs more room.
Judge the experience of reading it, not how many words the revision removes.

## What an improvement looks like

### Reach the distinction without an abstract detour

> SQLite’s in-process architecture, for example, represents a different paradigm from a daemon-based database design.

Compare:

> SQLite runs in-process instead of as a daemon.

The first sentence makes a plain engineering contrast sound grand.
The second names the difference directly.

### Develop the thought when a conclusion is not enough

> Feature flags add complexity.

Compare:

> Each independent on/off flag doubles the possible configurations.
> Keeping a flag means continuing to support both paths and their interactions with other flags.

The longer version earns its length: it explains how complexity grows instead of merely declaring that it does.

### Let a relationship organize the paragraph

> A failed build leaves readers on the current index.
> Refresh builds a new index.
> Readers use the current index during the build.
> The new index replaces the current one only after the build succeeds.

Compare:

> Refresh builds a new index while readers keep using the current one.
> The new index replaces it only after the build succeeds; if the build fails, readers stay on the current index.

The original gives the reader four facts to assemble.
The revision follows the build from start to outcome, explaining what readers use at each stage.

Use these contrasts to guide judgment, not to impose their style on every document.
Formality, fragments, repetition, and a restrained voice can all serve the reader.
Develop what repays attention without inventing facts; development need not include a worked example of every application.

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

1. **Find the reading problem.**
   Read the whole artifact in the form its reader encounters.
   An explanation may need to develop an idea across paragraphs; a reference may need independent lookup paths.
   Notice what makes that reading satisfying and where wording, rhythm, or arrangement makes it difficult.
   Let the difficulty determine the revision, rather than looking for sentences to shorten.
   If no reading problem warrants a change, use the unchanged outcome below.

2. **Choose a revision that addresses it.**
   When facts are clear but their relationship is buried, revise the connected passages together rather than polishing each sentence in isolation.
   Introduce a concrete distinction before an abstraction when that helps, and change headings or section boundaries when the reading requires it.
   Keep needed lookup paths, not necessarily the old arrangement.
   When the surrounding progression already works, revise the awkward passage locally.

   Let paragraphs develop thoughts, bullets distinguish actions or alternatives, and tables support comparisons.
   Preserve effective voice and emphasis; do not normalize deliberate casing, fragments, or idiom just for consistency.
   Keep precise domain terms and explain them when the reader needs help; apply vocabulary bans by meaning rather than word matching.
   Keep required warnings beside the actions they govern, so readers encounter them before acting.

3. **Read the result before defending the edits.**
   Read the complete revision in order, including its dull stretches, then compare its wording, rhythm, selection, and development with the original.
   Ask whether it reads better and whether the original reading problem remains: a revision can improve without fully solving that problem.
   Useful sections and individually defensible edits do not establish that the whole reads well.
   Restore anything that reads better in the original; an unchanged result is preferable to edits made merely to demonstrate effort.

4. **Check what the revision changes.**
   A sentence can keep its wording and still change its meaning.
   Put an unconditional rule under “When tests fail,” and it no longer appears to apply when they pass.
   Keep unconditional instructions outside such headings.
   Preserve governing requirements, including who must do what, who can decide, and which conditions, exceptions, and priorities apply.

   For user-facing instructions, compare the commands, paths, defaults, and validation with the original.
   A smoother explanation must not silently change observable behavior, public API details, or compatibility promises.
   Do not turn example-only behavior into a default or guarantee.

   A cut can leave an action clear while removing the reason to choose it.
   Keep rationale, rejected alternatives, and examples that guide a future choice or prevent a likely mistake.
   An explanation that merely says a rule is good can go, as can code-owned implementation detail that does not affect the reader's action or understanding.

   Moving an explanation only helps if readers can still find and use it.
   Read each revised section on its own and follow changed references: can readers find their first action, applicable constraints, and required validation?
   For skills, discovery begins before the body loads; preserve every trigger in the YAML description and check linked references and examples.

5. **Explain the result.**
   Describe what improved and what remains difficult, using representative quotations and sustained patterns rather than an edit count.
   Explain preservation decisions that affected the revision and any edits you reversed.
   Name uncertainty that limits the judgment and any material you excluded or could not read.
   Before claiming guidance is missing, read the complete relevant section in both versions and follow any replacement route; cite exact locations.
   This review concerns prose, not operational correctness.

## When no revision earns its cost

Leaving the artifact unchanged is a judgment about the revisions you considered, not a claim that no better version exists.
Explain why the original is preferable to your strongest concrete alternative, and identify any reading problems left unresolved.
“Every section has a purpose” is not a judgment about how the whole reads.
If you cannot support the verdict concretely, the parent arranges a bounded independent whole-document reading through [delegation](../delegation/SKILL.md), or reports that independent review is unavailable.
If that reading finds a missed improvement, withdraw the verdict and reconsider the affected scope.

## When consolidating instructions

Compare required behavior and conditions before calling two policies duplicates.
“Prioritize clarity → precision → concision” ranks goals; “Use concise, clear language” directs writing style.
Keep both, though they can appear together.

When policies do duplicate each other, keep one authoritative owner with direct, task-specific references from affected entry points.
Usually keep distinct lookup routes to that owner; test each entry point before removing one.
A link must say why the reader needs it, not merely “See testing.md.”
Preserve useful two-level routing such as task → owner → focused topic; flatten it or add a short local guard if the operative rule takes more than three hops to reach.

Keep a repeated safety constraint at the point of action when its absence permits a concrete misunderstanding or unsafe action.
Otherwise, test deletion or a direct reference rather than preserving text solely because it existed.

## Skill-specific rules

Keep `SKILL.md` procedural and short.
Move bulky examples or variant detail to directly linked references, read only when needed.
Delete generated template text; do not add a README, changelog, quick reference, or process notes to a skill.
