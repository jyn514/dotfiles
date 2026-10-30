---
name: skill-authoring
description: Create or evaluate portable agent skills, including existing or proposed discovery triggers, scope, workflows, and supporting package structure. Use for substantive skill changes, skill critique, replacing instructions with a skill route, changing when a caller invokes a skill, or diagnosing ambiguous guidance, bad routing, and missing decision rules. Not for an isolated missed instruction or localized additions, wording edits, paragraph moves, or link fixes that preserve discovery and behavior. Use holistic-writing for whole-artifact editorial review and tighten-prose for bounded local polishing.
---

# Skill authoring

Create or evaluate skills that change action reliably without burdening every prompt.

For review, inspect the existing or proposed guidance and its callers, then apply §6's discovery and procedure checks.
Use §1's provenance checks when assessing a proposed correction.
Report supported findings and the smallest useful corrections; a review request does not authorize edits or creation of a replacement skill.
Consult the [non-narrowing check](../spec-review/SKILL.md#non-narrowing-check) when a concrete question concerns supported cases or governing authority, not as another full review.
For creation or substantive changes, follow the workflow below.

## 1. Justify the skill

Before writing, identify:

- the target agent harnesses and their skill specifications, discovery rules, and supported tools;
- the recurring task or hard constraint the skill owns;
- the concrete trigger phrases and contexts that should load it;
- nearby skills, repository instructions, or canonical docs that may already own the behavior;
- the decisions or failure modes that generic agent behavior handles poorly.

### Recover purpose and provenance

For changes within this skill's scope, recover why the affected guidance was introduced or revised before choosing the change.
Mechanical spelling or link corrections that preserve discovery and behavior do not require this history check.

Use relevant history already established in the current conversation rather than searching again.
Otherwise, search retained sessions by skill name, affected guidance or motivating incident, and read the relevant exchanges before choosing the change.
Treat search hits as leads, not complete evidence.

Distinguish the original requirement, the failure the guidance addressed, and the mechanism chosen to address it.
Preserve the requirement when replacing the mechanism.
If no relevant record is found or history is unavailable, state that limit; do not infer that the guidance has no purpose.
Use `jj-workflow` when file history is needed to locate or explain the change.

### Analyze failures and proposed corrections

A missed instruction alone does not establish a guidance problem.
A clear requirement can still benefit from a more explicit execution order or decision check.

Identify what the proposed revision changes at the failed decision point.
Do not assume either that rewording will improve compliance or that existing clarity makes improvement impossible.
Correct an isolated miss without invoking this workflow merely to redesign the instruction.
Use failure analysis here when evidence points to ambiguous or conflicting guidance, bad routing, or a missing decision rule.

For edits prompted by a failed session, inspect the recorded decision and rejected alternatives before drafting.
Do not infer the cause from an outcome summary alone.
Distinguish missing guidance from ignored guidance or restrictions introduced by the chosen approach.

For a correction-driven revision, identify the assumption being challenged, the question or counterexample that challenged it, and why reconsideration was warranted.
Teach what the agent must inspect or construct to answer that question, and how different answers change its next action.
Keep the governing outcome fixed; questioning an implementation obligation does not authorize weakening the requirement.

### Check generalization

Do not overfit a revision to the session that exposed the failure.
Broader vocabulary does not make the corrected answer a reusable decision rule.
Keep task-specific conclusions in examples unless independent evidence or an established constraint supports the broader prescription.
Use §6's scope and interaction checks to challenge the rule's main prescription, not just confirm that its exceptions preserve required behavior.
For judgment guidance, trace how different governing requirements could lead to different choices, including cases where the rejected mechanism is necessary.
Distinguish observed replay success from generalization; matching the originating answer alone establishes neither portability nor reliable improvement.

When distilling research into guidance, identify the tempting inference and its smallest counterexample.
Ask whether an agent without the research history could derive the decision-changing check from the existing guidance.
Add only the missing distinction, reasoning step, or worked example; a research case may justify no edit.

### Require recurring use and place discovery

When reviewing or changing routing, first identify what the target harness exposes at the decision point.
Separate always-loaded instructions and descriptions from on-demand skill bodies and references; verify the actual loading model.
Trace how the agent chooses the next resource using only information already available.
An applicability statement inside an unloaded reference cannot make that reference discoverable.

Reuse an existing visible trigger when it already covers the task instead of adding a parallel caller route or a new skill.
Keep a separate route when it supplies a distinct task-specific decision or serves callers that do not receive the existing trigger.

Require a concrete repeated use, second consumer, or hard constraint.
Do not create a skill for one isolated task, generic advice, or rules that must apply to every task; put always-applicable constraints in the relevant `AGENTS.md` instead.

Put normal task-discovery conditions in the skill description first.
Do not duplicate them in always-loaded instructions merely to make invocation more likely.
Keep an explicit always-loaded trigger only when it must interrupt an otherwise plausible action, protects a constraint outside the skill's discovery scope, or addresses an observed discovery failure.
When extracting instructions, assess whether the existing skill description can own discovery; do not automatically replace every extracted section with a shared trigger.
Plain references are not discoverable skills and still need an explicit route from their callers.

Distinguish discovery triggers from constraints that apply even when the skill is not used.
Keep those constraints in always-loaded instructions and link to their owner from the skill.
For example, ownership checks also apply to routine commits excluded by `jj-workflow`, and test isolation applies when running existing tests without a test-design procedure.

Use the smallest workflow justified by uncertainty and risk.
Give every costly stage an entry condition.
Stop when simpler evidence settles the task.

## 2. Declare scope and authority

State what the skill does, when it applies, and adjacent work it does not own.

Define how to derive a deterministic working scope when the request omits one.
Stop for clarification when no safe default exists.

For multi-phase work, say which phase the skill owns.
Forbid contaminating adjacent phases, such as selecting during critique or mutating during review.

Before adding a procedure, check nearby skills for an owner.
Refer to that owner under §3 rather than copying its workflow.

Keep one authoritative owner for each procedure.
When removing duplicated policy, apply the [consolidation check](../holistic-writing/references/consolidation.md).
Briefly repeat a safety constraint at the point of action only when removing it would make that step unsafe in isolation.
For effectful workflows, state what grants mutation authority; inspection, suggestion, or review must not imply permission to write.

## 3. Design progressive disclosure

Create `<skill-name>/SKILL.md`.
Match the directory name to the frontmatter `name` for cross-harness compatibility.
Add other files only when they earn their loading cost:

- `references/` for detailed material needed only in some cases;
- `scripts/` for deterministic operations that prose should not reimplement;
- `assets/` for templates or static inputs.

Keep the main skill sufficient to choose and begin the workflow.
Refer to owning skills by name rather than copying their procedures; links to specific sections are optional.
Say when to read or run each reference, and distinguish its scope from local work.
Preserve referenced triggers and phase boundaries.
For example, consult [review evidence standards](../references/review-evidence.md) before work without invoking its completion audit.

Keep `SKILL.md` procedural and short.
Move bulky examples or variant detail to directly linked references, read only when needed.
Delete generated template text; do not add a README, changelog, quick reference, or process notes to a skill.

## 4. Write the frontmatter

Use:

```yaml
---
name: lowercase-hyphenated-name
description: What the skill does. Use when concrete trigger contexts occur.
---
```

The name must match the parent directory.
Use lowercase letters, digits, and single hyphens, with no leading or trailing hyphen.
Keep the name within 64 characters and the description within 1024 characters.
Treat the description as routing logic.
Include the task, trigger contexts, and important exclusions that must be known before loading the body.

Add optional frontmatter only when it has operational meaning and every target harness supports it.
Do not rely on one harness ignoring unknown fields.
A missing description prevents discovery in common harnesses.

## 5. Write an executable procedure

State the intended action directly.
Mention an alternative only when choosing or rejecting it is necessary to the task.
Avoid framing an instruction as “before doing X” when X is not otherwise called for; that wording can introduce X as an expected later step.

Use imperative steps in execution order.
Every skill should define:

- initial observations and prerequisites;
- scope, ownership, authoritative inputs, and phase boundaries;
- stop conditions and the cheapest decision-changing escalation;
- valid outcomes and an evidence-based completion condition;
- outputs, evidence provenance, and what validation can and cannot prove.

Separate observed facts, assumptions, decisions, and unresolved questions when confusing them could change the action.
Distinguish discovery signals from proof.
Inspect the owning artifact before turning search matches, metrics, or worker reports into findings.

Add hazard-specific rules only when the workflow needs them:

- **Mutable state:** define freshness, authorization, bypass paths, idempotency, interruption, partial effects, unknown outcomes, cleanup, recovery, and independent verification.
- **Bounded audits:** account for inspected, excluded, skipped, and unexamined scope so silence cannot imply completeness.
- **Delegation:** use self-contained, non-overlapping packets and assign one owner for shared effects, deduplication, and synthesis.
- **Resumability:** persist only state expensive to reconstruct—completed evidence, unresolved work, governing decisions, and invalidation conditions.
- **Generated or transformed output:** validate the final consumer-visible representation, not only source syntax or an intermediate artifact.

Separate requirements from examples.
Preserve reasons for non-obvious constraints and rejected tempting alternatives.
Avoid motivational prose, broad expertise summaries, and duplicated repository documentation.
Avoid exhaustive catalogs the agent can discover when needed.

Do not prescribe tools unavailable in any target harness unless the skill includes a clearly routed alternative.
If helper code is needed, keep each language in its own file.
Use the owning package manager.
Follow dependency-review before adding a dependency.

## 6. Review the skill as routing and procedure

Check both layers independently:

- **Before loading:** does the description trigger on every intended request without claiming adjacent work?
- **After loading:** can the agent identify the first action, boundaries, failure behavior, evidence, and completion condition? Check for rules that conflict, unclear precedence when rules interact, and edge cases where the next action is underspecified. State which rule takes priority or what the agent should do when it cannot resolve the conflict safely.

Treat discovery as classification against the skill's declared scope.
A false positive loads the skill for adjacent work it does not own;
a false negative misses work that needs its procedure.
Identify the concrete consequence of each error and tune triggers and exclusions accordingly;
do not assume the two errors are equally costly or reduce one by making the other unbounded.
Positive and negative task examples test only those cases, not the complete discovery boundary.

Read each changed caller and the target skill’s description together.
Confirm the caller’s intended tasks satisfy the target’s trigger conditions and do not fall under its exclusions.
Trace further delegation when it replaces removed policy.

When loaded guidance leaves the target decision unchanged, check whether the failing choice violates the guidance or remains defensible under it.
If the guidance permits the failure, correct the missing distinction or decision rule rather than adding stronger exhortations.

Review when each recommended operation is warranted, not just whether its syntax is valid.
When importing or adapting a guide, inspect inherited workflow advice rather than accepting it as policy.
Remove or qualify recommendations that lack a task or project-workflow reason; command availability does not make an operation required.
For example, a tracker supporting reviews or specs does not require agents to create them for every change.

Challenge the draft with at least two concrete tasks: one that must trigger it and one nearby task that must not.
For a skill claiming general-purpose use, include a positive task outside its originating domain.

Check that the procedure works without that domain's unstated vocabulary, data model, or workflow.
Explain domain-specific examples rather than treating them as prerequisites.
The existing positive task can meet this check; add another only when needed.

Trace cases where two requirements interact.
Verify that the instructions produce compatible actions or explicitly resolve the conflict.
For each consequential requirement, identify supporting evidence and the cheapest check that could disprove it.
Do not claim completion while a requirement lacks evidence.
Remove rules that merely restate normal competence.

For references, apply §3's entry test: can the agent choose and begin the workflow without reading them?

For example, if a skill supports both writing and review, test “review this README without editing it,” not only “write a README.”
A review procedure in the body does not make the skill discoverable when its description mentions only authoring.

Before arranging behavioral evidence about a prompt or skill change, read [Behavioral trials](references/behavioral-trials.md).
This includes passive observation of ongoing work and paired behavioral or summarization trials; consult it before preparing inputs or contacting an observed agent.
A textual review does not require a trial and does not establish measured compliance.

## 7. Validate and tighten

Apply every relevant category when a change spans several kinds.
Use the applicable type-specific checks below, then apply the universal checks to every change.

### Type-specific checks

- **Body or reference only:** review the changed procedure, constraints, and references.
  Reuse discovery evidence when the name, frontmatter, installed location, and discovery configuration are unchanged.
  A body-only edit does not require loading every harness again.
- **Caller route only:** read the caller and target description together, and trace one task that must route and one nearby task that must not.
  Check linked paths; a changed route alone does not require reloading an unchanged skill.
- **Description meaning only:** review the description's scope and apply §6's routing checks.
  Reuse loader evidence when the name, frontmatter syntax and field set, installed location, and discovery configuration are unchanged.
  Check that the edited description still meets the frontmatter requirements in §4; changed wording alone does not require every harness to reload it.
- **Loader or discovery-configuration change:** for a new skill or changes to name, frontmatter syntax or field set, installed location, or discovery configuration,
  load it through every target harness and inspect discovery or validation warnings.
  Confirm no collision or precedence rule causes another skill to win discovery.
  When Pi is a target, read [Pi loader checks](references/pi-loader-checks.md) before checking it.

### Checks for every change

For every change, confirm affected linked paths exist and affected commands match the repository and installed CLI.
Run repository checks for bundled scripts or code that changed.
Apply §6's positive, negative, and interaction checks to changed behavior and routes.
Reload an active session before using its behavior as evidence for edited instructions.
Use `holistic-writing` for a whole-artifact editorial pass after creating or substantially rewriting the skill, preserving the behavior and discovery decisions established here.
Reject cuts that remove triggers, boundaries, failure modes, rationale, or examples that change decisions.

Report changed files, checks performed, reused evidence, and any environment-specific limitation.
Distinguish textual review, loader validation, discovery, and observed behavior.
Do not claim the skill loaded successfully from syntax inspection alone.
