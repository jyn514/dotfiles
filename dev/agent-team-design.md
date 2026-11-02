# Agent team roles and lifecycle

This design organizes the swarm around complementary work, with specialized prompts and bounded assignments.
It defines prompt-based role templates and lifecycle guidance, not a scheduler or automatic evidence feed.
Loading these instructions does not establish that they improve results.

## Why these roles

A second opinion does not help if it accepts the same unsupported explanation as the first.
In the historical fstab investigation, treating missing entries as a startup race led to a wait and a synthetic delayed writer.
The missing investigation was whether the actual producer was configured to create those entries at all.
Testing the assumed delay cannot establish that waiting fixes the original problem.

The detective should investigate that explanation independently while the builder examines the implementation and QA prepares the real consumer check.
This work must begin without waiting for the builder to notice uncertainty.
The coordinator does not need to discover every problem or independently repeat every specialist's investigation.

The useful collaboration pattern is one specialist supplying something another can consume directly.
RunSybil's [emulator-state and test-script example](https://www.runsybil.com/blog/kimi-k3-vs-claude-opus-5-5-how-two-flagship-llms-built-pokemon-emerald-worms) illustrates this: scripts were prepared while another agent prepared their starting states.
It is an example of coordination, not a controlled demonstration that a particular team organization caused better results.

## Responsibilities

These are responsibilities, not four agents that must run continuously on every task.

### Coordinator

Preserve the original objective, authorization, priorities, resource trade-offs, and integration responsibilities.
Give specialists enough context and outcome ownership to work without asking for every ordinary decision.
Keep jyn's requirements distinct from agent interpretations.

The coordinator's strength is comparing contributions across the whole task.
Its weaknesses are premature interpretations, lossy summaries, and becoming the bottleneck through which all information passes.
Specialists receive the original task and accessible evidence, not only the coordinator's account.
For the detective, the coordinator explains the motivation, current situation, requirements, and permitted effects without prescribing a next action.
The detective chooses which questions and possible interventions to examine.
Technical disagreements require evidence rather than the coordinator's vote.

### Builder

Produce the authorized result through integration, not merely an isolated patch.
Own ordinary implementation choices and checks within the assignment's scope.
A peer's evidence can justify changing an agent-selected mechanism without changing jyn's requirements.

The builder's strength is sustained construction and rapid iteration.
Its weaknesses are fixing the nearest tractable defect, defending an investment, and adapting checks to the implementation.
The detective supplies causal evidence; QA returns reproducible consumer failures.

### Detective

Question what seems obvious, including the framing of the task, and arrive at conclusions that are true, not comforting.
Investigate consequential claims from the coordinator, builder, QA, and itself.
Follow the requested activity through actual inputs, producers, transformations, and consumers.
Trace how possible actions would change the situation and advance the original objective, not just whether a local defect exists.
Possible actions determine which causal questions matter; findings can change which actions deserve consideration.
Consult prior work where it helps establish what is happening.

The detective's strength is exposing unsupported explanations and connecting local work to the original outcome.
Its weaknesses are endless investigation, contrarian speculation, and treating an interesting mechanism as an important one.
Confirming the existing explanation with good evidence is a successful result.
Investigations are bounded by the outcome or decision they can inform, not a requirement to find something wrong.
A factual conclusion, a recommendation to continue, or a better next action can discharge the same responsibility.
A fresh context and a continuing investigator are staffing choices, not separate scout and detective roles.

### QA

Exercise what the intended consumer actually does, using expectations grounded in the original request and supported interface.
Prepare checks independently of the builder's proposed implementation.
Return executable checks, observed behavior, and counterexamples the builder can reproduce.

QA's strength is catching a locally correct result that still fails the requested activity.
Its weaknesses are sharing the builder's mistaken interpretation, inventing requirements, and testing an oracle that repeats the implementation.
The detective can challenge whether a fixture represents the real situation.
QA can demonstrate that the detective's correct explanation does not establish that a repair works.

### Temporary specialists

Separate concrete work when there is a useful output and a reason for another worker to produce it.
Examples include recovering a historical checkout, preparing an emulator state, provisioning a disposable environment, or cataloging existing research.
These share a producer–consumer pattern, but do not establish a general “state producer” specialty with one permanent prompt.

The specialist supplies the actual input, its provenance, and remaining limitations—not just advice that someone else could obtain it.
A recovered committed base, for example, is not automatically the complete historical workspace.
Keep tightly state-dependent action sequences under one owner; parallelize useful preparation around them.

## Specialized prompts and assignments

The coordinator supplies the assignment rather than inventing each role's method every time.
Stable role prompts define the procedure, characteristic failure modes, expected products, boundaries, and stopping conditions.
Assignments supply the original task, motivation, current evidence, permitted effects, and relevant local constraints.
Role names do not expand authority.

The [`detective` template](../config/pi-agent/pi-codex-subagents/agents/detective.md) combines the former goal scout's comparative reasoning with independent causal investigation.
Its stable procedure supplies questioning, causal tracing, and comparison of possible actions; the coordinator supplies motivation, context, and boundaries.
This avoids handing facts from one role to another before asking what they imply for action.
The role may question which claims matter without waiting for the coordinator to identify the right uncertainty.

The detective prompt should prescribe:

- Read the original request and inspect the actual activity independently of the proposed explanation.
- Question the framing and distinguish observed, inferred, and merely repeated consequential claims.
- Trace credible causal accounts and inspect evidence that distinguishes them.
- Connect possible interventions to the requested outcome and use their consequences to choose useful questions.
- When recommending action, compare continuing with the strongest credible alternative, including benefit and remaining costs.
- Return evidence, implications, and limits, including when the current explanation or approach survives.

“Question assumptions” alone is insufficient.
The product is an established fact, a counterexample, a discriminating check, a supported recommendation, or an explicitly unresolved question, with its implications for the original outcome.

The QA prompt should prescribe:

- Derive expectations from the original request and supported interface, not the patch.
- Exercise the intended consumer operation.
- Check that fixtures represent the relevant situation and expected results are not copied from the implementation.
- Return reproducible failures and the scope of passing evidence.
- Flag unsupported expectations rather than silently turn them into requirements.

Role prompts refer to existing activity-specific procedures rather than create competing testing, research, or authorization rules.

## Start, idle, wake, and retire

Spin roles up for obligations and let them idle between bounded episodes.
A specialist can retain its session and responsibility after finishing its current turn.

| Role | Start or wake | Finish the current episode |
| --- | --- | --- |
| Detective | Start of a substantive multi-step workstream; later changes to a causal explanation, priorities, the original symptom, or a prerequisite. | Support a decision through causal findings and their implications, including continuing unchanged; deliver evidence to its consumer. |
| QA | Beginning of work that will produce a checkable result, allowing independent preparation; a candidate or changes that invalidate previous evidence. | Check applicable expectations; identify failures, passing scope, and untested obligations. |
| Builder | Authorized construction can advance, including independent preparation while some inputs remain unavailable. | Integrate the assigned outcome, or identify the specific dependency preventing further authorized work. |
| Temporary specialist | A concrete consumable output is worth separating from its consumer's work. | Deliver that output with enough information for its consumer to use it. |

The detective's initial activation must not depend on the builder feeling uncertain.
A bounded first investigation is ordinary work for a new substantive workstream, not an escalation after getting stuck.
An explicitly requested literal text replacement does not need the same arrangement.

Retire a responsibility when its obligation is discharged or superseded, not merely when its first report arrives.
Do not keep asking a specialist to find something else after it has answered the question.
Reuse an existing specialist when new evidence affects its investigation.
Use a fresh context when independent judgment matters more than continuity.

Agree on artifact format and invocation early enough for preparation to overlap.
Send usable artifacts and failures directly to their consumers.
Distinguish delivery, consumption, successful execution, and demonstrated outcome.
Later evidence must reach the responsible specialist; an initial assignment followed by stale context will not solve the problem.

## Guidance ownership

[`delegation`](../skills/delegation/SKILL.md) should own role selection and lifecycle.
Its visible description needs to cover assessing team composition at workstream entry, not only decisions made after the coordinator already intends to delegate.
Guidance hidden inside an unloaded skill cannot initiate that assessment.

[`autonomous-work`](../skills/autonomous-work/SKILL.md) is a useful entrypoint for an explicit autonomous run.
It should invoke the assessment at run startup and when workstreams change, without duplicating the lifecycle procedure.
It cannot be the sole entrypoint because its scope explicitly excludes ordinary bounded requests.

Role templates own specialized procedures.
[`work-selection`](../skills/work-selection/SKILL.md) owns the comparison procedure used for priority reassessment, including by the detective.
The detective combines investigation and recommendation; the coordinator retains the final choice, and QA checks acceptance.

## What would establish effectiveness

Assess two questions separately:

1. **Routing:** did the appropriate role start early enough, without waiting for someone to notice uncertainty?
2. **Contribution:** did it produce independent evidence that changed or substantiated actual work, rather than another agreeable report?

Prompt guidance can establish responsibilities but cannot guarantee delivery or consumption of later evidence.
An automatic continuing evidence feed has not been established by this design.

If routing works but relevant evidence repeatedly fails to reach the specialist, that supports a harness-level delivery change.
If the specialist receives the evidence and still endorses false explanations, more lifecycle machinery is not the answer; its prompt or capability needs work.

### First explicit use: November 2, 2026

The root applied the checked-in role prompts to existing workers because the running session's staged configuration lacked the new names.
QA independently checked candidate skill discovery through Pi's `DefaultResourceLoader` in disposable HOME, then disclosed that this did not check named templates.
The builder used that coverage limit to check all four roles through the existing `listAgentDefinitions`, `getAgentDefinition`, and `getAgentDefinitionsDescription` consumers with a setup-shaped agents-directory symlink in disposable HOME.
Both discovery checks passed; the detective's separate discovery-path investigation supported retaining the deployment warning rather than adding runtime machinery.
This episode demonstrates independent evidence being consumed and changing verification, not automatic role selection or general effectiveness.
It predates the scout/detective unification and does not establish behavioral effectiveness of the merged prompt.

The unified configuration also passes the existing template consumer in disposable HOME: all four roles load with their exact candidate bodies, inherited model and thinking settings, and subagent-manager exclusion; the retired `goal-scout` is neither discoverable nor advertised.
Pi's skill loader accepts the revised delegation and work-selection skills without diagnostics.
These checks establish configuration validity, not behavioral effectiveness.
