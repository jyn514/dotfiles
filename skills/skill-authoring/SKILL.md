---
name: skill-authoring
description: Create or structurally revise portable agent skills with precise triggers, progressive disclosure, executable procedures, and validation. Use when adding a SKILL.md or changing a skill’s scope, routing, workflow, package structure, scripts, or references. For review-only work use spec-review; for prose-only tightening use tighten-docs.
---

# Skill authoring

Create skills that change action reliably without burdening every prompt.

## 1. Justify the skill

Before writing, identify:

- the target agent harnesses and their skill specifications, discovery rules, and supported tools;
- the recurring task or hard constraint the skill owns;
- the concrete trigger phrases and contexts that should load it;
- nearby skills, repository instructions, or canonical docs that may already own the behavior;
- the decisions or failure modes that generic agent behavior handles poorly.

Require a concrete repeated use, second consumer, or hard constraint. Do not create a skill for one isolated task, generic advice, or rules that must apply to every task; put always-applicable routing and constraints in the relevant `AGENTS.md` instead.

Use the smallest workflow justified by uncertainty and risk. Give every costly stage an entry condition and stop when simpler evidence settles the task.

## 2. Declare scope and authority

State what the skill does, when it applies, and adjacent work it does not own. Define how to derive a deterministic working scope when the request omits one; stop for clarification when no safe default exists. For multi-phase work, say which phase the skill owns and forbid contaminating adjacent phases, such as selecting during critique or mutating during review. Route to another skill when a specialized workflow already exists rather than copying it.

Keep one authoritative owner for each procedure. Briefly repeat a safety constraint at the point of action only when removing it would make that step unsafe in isolation. For effectful workflows, state what grants mutation authority; inspection, suggestion, or review must not imply permission to write.

## 3. Design progressive disclosure

Create `<skill-name>/SKILL.md`, with the directory name matching the frontmatter `name` for cross-harness compatibility. Add other files only when they earn their loading cost:

- `references/` for detailed material needed only in some cases;
- `scripts/` for deterministic operations that prose should not reimplement;
- `assets/` for templates or static inputs.

Keep the main skill sufficient to choose and begin the workflow. Link directly to optional material and say when to read or run it. Resolve every relative path from the skill directory.

## 4. Write the frontmatter

Use:

```yaml
---
name: lowercase-hyphenated-name
description: What the skill does. Use when concrete trigger contexts occur.
---
```

The name must match the parent directory, use lowercase letters, digits, and single hyphens, have no leading or trailing hyphen, and stay within 64 characters. Keep the description within 1024 characters. Treat it as routing logic: include the task, trigger contexts, and important exclusions that must be known before loading the body.

Add optional frontmatter only when it has operational meaning and every target harness supports it. Do not rely on one harness ignoring unknown fields. A missing description prevents discovery in common harnesses.

## 5. Write an executable procedure

Use imperative steps in execution order. Every skill should define:

- initial observations and prerequisites;
- scope, ownership, authoritative inputs, and phase boundaries;
- stop conditions and the cheapest decision-changing escalation;
- valid outcomes and an evidence-based completion condition;
- outputs, evidence provenance, and what validation can and cannot prove.

Separate observed facts, assumptions, decisions, and unresolved questions when confusing them could change the action. Distinguish discovery signals from proof: inspect the owning artifact before turning search matches, metrics, or worker reports into findings.

Add hazard-specific rules only when the workflow needs them:

- **Mutable state:** define freshness, authorization, bypass paths, idempotency, interruption, partial effects, unknown outcomes, cleanup, recovery, and independent verification.
- **Bounded audits:** account for inspected, excluded, skipped, and unexamined scope so silence cannot imply completeness.
- **Delegation:** use self-contained, non-overlapping packets and assign one owner for shared effects, deduplication, and synthesis.
- **Resumability:** persist only state expensive to reconstruct—completed evidence, unresolved work, governing decisions, and invalidation conditions.
- **Generated or transformed output:** validate the final consumer-visible representation, not only source syntax or an intermediate artifact.

Separate requirements from examples. Preserve reasons for non-obvious constraints and rejected tempting alternatives. Avoid motivational prose, broad expertise summaries, duplicated repository documentation, and exhaustive catalogs the agent can discover when needed.

Do not prescribe tools unavailable in any target harness unless the skill includes a clearly routed alternative. If helper code is needed, keep each language in its own file, use the owning package manager, and follow dependency-review before adding a dependency.

## 6. Review the skill as routing and procedure

Check both layers independently:

- **Before loading:** does the description trigger on every intended request without claiming adjacent work?
- **After loading:** can the agent identify the first action, boundaries, failure behavior, evidence, and completion condition?

Challenge the draft with at least two concrete tasks: one that must trigger it and one nearby task that must not. For each consequential requirement, identify supporting evidence and the cheapest check that could disprove it; do not claim completion while a requirement lacks evidence. Remove rules that merely restate normal competence. Split bulky conditional detail into a referenced file only when the main procedure remains usable without it.

## 7. Validate and tighten

- Confirm every linked path exists and every command matches the repository and installed CLI.
- Run repository checks for bundled scripts or code.
- Load the skill through every target harness and inspect discovery or validation warnings.
- For Pi, first confirm the installed CLI options, then use `pi --offline --no-extensions --no-tools --no-session --skill <path> --list-models` as the non-mutating load check.
- Confirm no name collision or precedence rule causes another skill to win discovery in any target harness.
- Invoke `tighten-docs` after creating or substantially rewriting the skill. Reject cuts that remove triggers, boundaries, failure modes, rationale, or examples that change decisions.

Report the created files, validation performed, and any environment-specific limitation. Do not claim the skill loaded successfully from syntax inspection alone.
