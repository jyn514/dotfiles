---
name: skill-authoring
description: Create or evaluate portable agent skills, including existing or proposed discovery triggers, scope, workflows, and supporting package structure. Use for substantive skill changes, skill critique, replacing instructions with a skill route, changing when a caller invokes a skill, or diagnosing ambiguous guidance, bad routing, and missing decision rules. Not for an isolated missed instruction or localized additions, wording edits, paragraph moves, or link fixes that preserve discovery and behavior. Use holistic-writing for whole-artifact editorial review and tighten-prose for bounded local polishing.
---

# Skill authoring

A skill changes which work an agent takes on and how it does that work.
Review what makes the agent load it, what it will do after reading it, and what useful choices it might stop considering.

For review, read the skill and its callers, then use **Review loading and actions** below.
For creation or revision, start with the task the skill should help an agent perform.

## Decide what belongs in the skill

What recurring task needs help, and where does an agent currently go wrong?
Check existing skills and instructions before creating another owner.
A skill needs repeated use, a second consumer, or a hard constraint.
Rules that apply to every task belong in the relevant `AGENTS.md`.

For substantive revisions, recover why the guidance exists.
Use history in the conversation and past sessions, using `jj-workflow` for file history when needed.
Separate what had to be achieved from the failure that prompted the rule and the particular solution chosen.
For example, “leave the live checkout usable” is a requirement; a separate workspace is one way to meet it.

### When correcting a failure

Read the recorded decision, the instructions available then, and the alternatives the agent rejected.
Did it ignore a rule, follow a bad rule, invent a restriction, or lack information needed to choose?
If following the instructions caused the problem, change those instructions rather than adding “use judgment.”

What fact or counterexample should have changed the choice?
Teach the agent how to find that fact and what to do with each possible answer.
Keep a session's particular answer in an example unless evidence supports it as a general rule.
If repeated corrections don't help, consider whether the framing of the question or task is wrong, not just the procedure.

## Put discovery where agents can see it

Put task triggers in the description: the agent reads descriptions to choose which bodies to load.
“Use this skill when…” inside the body is too late.

Read the existing descriptions and caller instructions before adding another route.
Does the agent already receive a trigger that covers this task?
Add a route only when it supplies a different decision or reaches callers that lack the existing trigger.
Plain references need an explicit route from a caller.

Use an always-loaded trigger when it must interrupt a plausible wrong action, protect a constraint outside the skill's scope, or fix an observed loading failure.
Keep rules that apply even without the skill in always-loaded instructions, with a link from the skill to their owner.
For example, ownership checks still apply to routine commits excluded by `jj-workflow`;
test isolation still applies when running tests without a test-design skill.

## Write instructions an agent can follow

Say what request the skill handles, what it leaves to other skills, and what the agent may change.
If a request omits scope, give a usable default or say what the agent must ask.
For a multi-phase task, say where this skill starts and stops.

Link to other procedure owners instead of copying their steps.
Use the [consolidation check](../holistic-writing/references/consolidation.md) when removing duplicated policy.
Keep a warning beside an action when following that action alone would otherwise be unsafe.
For uncertainty about supported cases or who may act, consult the [non-narrowing check](../spec-review/references/non-narrowing.md).

### Package and frontmatter

Create `<skill-name>/SKILL.md` with:

```yaml
---
name: lowercase-hyphenated-name
description: What the skill does. Use when concrete trigger contexts occur.
---
```

Match `name` to the directory: lowercase letters, digits, and single hyphens, with no leading or trailing hyphen; at most 64 characters.
The description must exist, stay within 1024 characters, and expose the task, triggers, and exclusions needed before loading.
Use optional fields only when they have operational meaning and every target harness supports them.

The main file should let the agent choose and begin the work.
Use `references/` for detail needed only in some cases, `scripts/` for deterministic helpers, and `assets/` for templates or static inputs.
Make reference-loading conditions explicit, either in the surrounding step or beside the link.
Delete generated scaffolding; do not add skill READMEs, changelogs, quick references, or process notes.

### Make the next action clear

Write steps in the order the agent will perform them.
What should it inspect first, what should it produce, and how will it know it is done?
For an expensive step, say when to take it and when simpler evidence suffices.

Settle fixed facts while authoring; leave future agents questions whose answers depend on their tasks.
If you don't know how a supported harness handles a frontmatter field, check its loader or documentation now instead of requiring every future agent to verify it.
Which files a particular review needs to inspect, by contrast, depends on the future task.

Watch instructions such as “before creating a design, inspect the implementation.”
They can imply that every task needs a design.
If a design is conditional, say when it is needed before giving its preparation steps.

Choose checks for the failures this task can actually encounter.
An audit needs to distinguish inspected files from skipped files;
a write that can partly succeed needs a way to determine what changed and how to recover.
For generated output, check what its consumer receives rather than only whether an intermediate file parses.

Explain non-obvious constraints and keep examples that help the agent choose.
Cut motivational prose, defensive sentences, exhaustive catalogs, duplicated documentation, and development history that does not change the reader's action.
Prescribe tools available in every target harness or provide an alternative.
Use `dependency-review` before adding dependencies; keep helper languages in separate files and use the owning package manager.

## Review loading and actions

### Will it load for the right requests?

Read the description alongside each caller that routes work to it.
Use a request that should load the skill and a nearby request that should not.
For a general-purpose skill, include a task outside the domain that originally prompted it.

For each request, follow the information the agent would actually see:

- What visible wording would make it select the skill?
- Could it miss the intended task? A description advertising only README writing may miss “review this README without editing it.”
- Could it claim adjacent work? A description mentioning every README may catch a syntax-only correction that needs no writing workflow.
- If a caller now links elsewhere, can the agent still reach the guidance that was removed?

Explain what each missed or unwanted invocation would cause before recommending broader or narrower triggers.

### What will it make the agent do—or stop doing?

Take a representative request and follow the work an agent would infer from the skill.
Look beyond explicit commands to the framing, sequence, examples, and assumed defaults.

What work would it do that the request never called for?
Look for added investigations, documents, workers, approvals, and prerequisites.
For example, importing a tracker guide can turn “this tracker supports specifications” into an expectation to write a specification for every change.
Ask whether each added step earns its cost under the agent's available attention, context, and other responsibilities.

What useful option would it stop considering?
“Preserve every example” can rule out an effective rewrite even when the request only requires preserving the explanation.
A skill can also discourage an option by describing only one route, making alternatives sound exceptional, or treating an example as the normal case.

When a step is conditional, compare an in-scope task that needs it with one that does not.
Does the wording help the agent choose differently?
Before making a required check conditional, establish that the agent can recognize when it is needed.

Read through the task from first action to completion.
Where could the agent get stuck, follow conflicting rules, or call the work finished too early?
If two instructions conflict, state which wins or what the agent should do next.
If a bad choice follows reasonably from the text, fix the instruction that permits it.

For a claim such as “another worker is needed,” what supports it, and what quick check could show otherwise?
When revising collaboration guidance, use the proposed responsibilities where practical and authorized.
Remove rules that merely restate normal competence.

### Behavioral evidence: only on request

When behavioral evidence is requested, read [Behavioral trials](references/behavioral-trials.md) before preparing inputs or contacting agents.
This includes passive observation and paired behavioral or summarization trials.
Report separately what you predict from the text, what you observed agents do, and what supports applying the result to other tasks.

## Validate and finish

Choose checks for what changed:

- **Body or reference:** review the changed instructions and affected links; reuse evidence for unchanged discovery.
- **Caller route:** read caller and description together, follow intended and excluded requests, and check paths.
- **Description meaning:** review which requests it claims and check frontmatter limits; reuse loader evidence when syntax, fields, installation, and configuration are unchanged.
- **New skill:** check frontmatter and links, then load it in the current harness.
- **Harness-specific loading changes:** check the affected harnesses for successful loading, warnings, collisions, and precedence.
  For Pi loading checks, first read [Pi loader checks](references/pi-loader-checks.md).

Use every row that applies.
Check affected commands, run checks for changed bundled code, and review how the changes interact with existing instructions.
Reload an active session before using its behavior as evidence of edited instructions.

After creation or substantial rewriting, use the [shared editorial pass](../holistic-writing/references/editorial-pass.md).
Report findings or changed files, checks performed or reused, and what remains unresolved.
Separate textual review, successful loading, discovery, and observed behavior in the report.
