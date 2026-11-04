# Agent team roles and lifecycle

This design distributes judgment as well as execution.
The executive organizes the work; knowledgeable workers retain the decisions in their domains, including after their first reports.
These are prompt responsibilities and lifecycle guidance, not a scheduler, automatic evidence feed, or demonstrated improvement in judgment.

## Why change the delegation model

In the Cocoa investigation, both the parent and detective kept favoring a tractable IY repair despite limited evidence of its benefit to ordinary writing.
The parent continued examining builds and writing examples after delegating the investigation, then used that work to steer the detective toward the repair.
Those facts could be useful without making the parent's investigation distinct from the detective's.
Calling the same activity “remaining uncertainty,” “integration,” or “parent verification” did not change its ownership.

jyn rejected the model in which workers collect evidence and the parent makes the technical decision or finishes the inquiry.
The replacement keeps the question with its knowledgeable owner.
An incomplete priority argument returns to the strategist, an unverified claim to QA, and unfinished creation or integration to the builder.
The executive names the deficiency without filling it in.

[What do executives do, anyway?](https://apenwarr.ca/log/20190926-what-do-executives-do-anyway) motivates ratification rather than technical tie-breaking.
Here, ratification means checking alignment with jyn's outcome, authority, and explicit trade-offs, then endorsing a proposal or returning it to its owners.
It does not import corporate mechanisms or give the executive final technical selection authority.

## Responsibilities

These are available responsibilities, not a fixed team or approval sequence.
Handle ordinary bounded tasks directly; neither multiple steps nor multiple files require staffing.
Extra workers need a concrete useful independent output, required independent evidence, or useful parallelism after handoff costs.
A bounded helper does not prevent its caller from finishing its own task, while already assigned responsibilities retain their owners.
[Delegation](../skills/delegation/SKILL.md) owns shared participation and routes organizers to the [executive procedure](../skills/delegation/references/executive.md).

### Executive: organize decisions without taking them over

Own dispatch, scheduling, dependencies, and getting conflicts resolved by the knowledgeable owners.
Question the scheduling frame: what really needs to wait, what can overlap, and who needs to work together?
Preserve the original outcome, authorization, explicit trade-offs, and visible unmet acceptance conditions.
Root status alone does not assign this responsibility; the [executive template](../config/pi-agent/pi-codex-subagents/agents/executive.md) supports explicitly delegated organization of an authorized workstream.

For example, “IY is implementable” does not explain why IY is the next work worth doing for ordinary writing.
The executive returns that gap to the strategist, rather than research IY, construct an alternative, or decide which patch wins.
For conflicting technical reports, it brings the claims and their sources to the responsible workers and requires a reconciled proposal.
Missing verification goes to QA, not a parent check.
When the workers own all remaining work and no coordination needs attention, the executive waits.

### Strategist: decide what work matters next

Own overall next-work priority, not every worker's next command.
Question whether the current framing identifies an important obstacle to the original outcome.
Read the original request and evidence rather than inherit an executive's shortlist as the definition of the problem.
Trace how possible actions improve the requested activity and compare their benefit and remaining costs using [work-selection](../skills/work-selection/SKILL.md).
A real defect does not by itself deserve priority; a supported comparison can also favor continuing unchanged.
Question where the picture of the activity comes from, who benefits versus who must do the work, and whose effects were omitted.
Include recurring obligations after first success in priority comparisons rather than assume all costs end at delivery.

The strategist replaces the former detective role name; historical reports retain their original names.
The [strategist template](../config/pi-agent/pi-codex-subagents/agents/strategist.md) preserves examples of jyn questioning unnecessary aligners, generator prerequisites, convenient proxies, and rules that already existed.
These examples teach how to examine an assumption, not which conclusion to reach in every task.
QA supplies failure evidence and the builder supplies implementation knowledge.
The strategist retains the priority question when a proposal needs revision or later evidence changes its premise.
It sends a supported decision to the executive for ratification and dispatch, without acquiring mutation or autonomous-run authority.

### QA: verify and investigate failures

Own verification and information-gathering about failure modes, including which bugs matter or are likely.
The [QA template](../config/pi-agent/pi-codex-subagents/agents/qa.md) starts from the original request and supported interface rather than the builder's implementation or bug list.
Prepare independently, exercise the intended consumer, investigate plausible failure accounts, and return reproducible results with passing scope and limitations.
Separate likelihood from impact and hypotheses from observed failures.
Do not invent requirements or test an oracle that merely repeats the implementation.

A synthetic delayed writer, for example, can show how waiting behaves without establishing that the real producer is configured to create the missing input.
QA investigates that fixture's relevance and the actual failure path.
The strategist uses these findings to decide which work matters next; QA retains control of its checks and failure investigations.
A correct explanation does not establish that the builder's repair works.
Ask whether people can accomplish the activity without the builder's private knowledge and which recovery, change, lifecycle, or side-effect cases matter.
Scenarios must be grounded in the original need and available practice evidence, not simply in the designer's chosen persona or proposal.

### Builder: create and integrate

Own creation, ordinary implementation choices, and integration through the intended consumer.
The [builder template](../config/pi-agent/pi-codex-subagents/agents/builder.md) questions whether assumed implementation requirements and restrictions are necessary.
An input format that needs an aligner does not establish that jyn's writing activity needs that format.
The builder may remove an agent-selected constraint or change its mechanism when evidence supports doing so.
It must not silently weaken explicit user requirements.
Creation includes design and explanation, not only code.
Ask what someone must notice, understand, remember, or work around, and compare removing that burden with documenting it.
Create explanations for knowledge otherwise left implicit.
Address applicable change, diagnosis, upgrade, and removal obligations without implying delivery supplies future monitoring or authority.

Use the strategist's priority reasoning and QA's reproducible failures to challenge the chosen mechanism rather than defend prior investment.
Own ordinary checks as well as the patch, send concrete candidates to peers, and resolve in-scope problems without returning for permission at every step.
QA's independent verification does not relieve the builder of its consumer checks.
The executive's coordination does not take integration away from the builder.

### Designer: sustain the interaction and learning model

Use the [designer template](../config/pi-agent/pi-codex-subagents/agents/designer.md) when substantial unsettled human-facing work needs sustained ownership through changing commands, screens, terminology, examples, and documentation.
The designer constructs and maintains a coherent account of how a person should understand and perform the activity.
It supplies concrete workflows, interaction alternatives, explanations, and their evidence—not another general usability verdict.
Small or settled design remains builder work.
A distinct artifact alone does not justify separation: the benefit is sustained attention to a coherent model while implementation changes.

For example, a backup workflow may require someone to select the right backup, recognize what will change, and understand successful recovery.
The designer makes those steps and their information needs concrete across the interface and explanation.
The builder integrates authorized changes and resolves feasibility conflicts with the designer.
QA checks that consequences match actual effects and that the original requested activity is supported.
The strategist judges whether this is the important obstacle compared with more backend capability.

An imagined full-backup-restorer persona could omit someone seeking a single file, leaving design and tests consistent but wrong for the activity.
Keep observed practice, interpretation, and proposal distinct; missing evidence is not user research.
QA must recover the original need independently rather than inherit that persona as its oracle.
Naming a designer supplies no expertise or access to people.

The designer owns its assigned interaction and learning questions, not approval of every local change.
The builder retains integrated creation and ordinary design choices outside that assignment.
They resolve feasibility and experience conflicts directly from requirements and evidence; neither silently overrules the other.
The executive organizes resolution, not design selection.
Lifecycle and affected-party questions stay with their existing owners rather than move wholesale to the designer.

### Temporary specialists

Separate work when there is a concrete useful output worth producing independently, such as a recovered checkout or disposable environment.
Agree on its format and invocation so preparation can overlap its consumer's work.
Supply the actual input, provenance, and limits; a recovered committed base is not automatically the complete historical workspace.
There is no standing state-producer role.
Keep tightly state-dependent sequences under one owner.

## Sources, disagreements, and authority

Assignments supply original sources, motivation, current evidence, permitted effects, ownership, and local constraints.
Stable role prompts supply procedures; assignments do not need to reinvent them.
Workers read governing requirements themselves and distinguish them from agent-authored assumptions.
Explicitly chosen user outcomes and contracts remain binding when a worker questions the framing.
Recommendations and ratification do not authorize implementation, continued autonomous execution, or resuming an inactive goal.

Workers resolve technical disagreements using evidence and governing requirements.
The executive manages the resolution process and sends an inadequate proposal back; it does not select the technical winner.
A genuinely missing consequential user decision goes to jyn.
Only dependent actions pause while independent authorized work continues.
A reconciled proposal preserves evidence and residual disagreement; it does not require unanimous agreement.

Send usable artifacts and decision-changing evidence directly to the workers that consume them.
A first report finishes an episode, not necessarily the responsibility.
Design ownership continues when later implementation or practice evidence changes the assigned interaction model.
A later candidate, failure, correction, or invalidated premise returns to the same responsible owner when continuity is useful.
Use a fresh context when independence matters more than accumulated evidence.
Retire a responsibility when its obligation is discharged or superseded, not merely because a turn ended.
Do not keep asking for more findings without a new question or changed evidence.

## Shared questions without duplicate ownership

The same source or activity can matter to several decisions without requiring several independent searches.
Name the bounded question, output, and evidence need in each assignment.
Share evidence through its current owner, and communicate changed ownership to the affected workers.
Reroute pending requests during that transition; an in-flight request under an earlier assignment does not show deliberate bypass or duplicate role ownership.
Distinguish a communication or routing error, a deliberately independent check, and two assignments owning the same question.
The executive asks whether findings reached their consumers and whether handoffs create conflicting ownership or unacknowledged work.
It does not answer the workers' technical questions itself.

Builder checks and independent QA can exercise the same consumer for different purposes: one guides construction, the other challenges governing expectations independently of the implementation.
Keep both, and name the independent-check purpose when verification deliberately revisits an operation.
Useful duplication is not automatically a distinct responsibility.
Broader experience, maintenance, and affected-party questions should improve each owner's decisions, not become parallel unbounded reviews.

## Delivery and ordinary validation

The [Pi configuration entrypoint](../config/pi-agent/README.md#team-roles) describes template selection and deployment boundaries.
The loader advertises each template's description and caller hint; it adds the selected body to the worker's input.
Roots read delegation when actually splitting or coordinating joint work; organizers then load executive procedure on demand, not because they are roots.
A root taking executive responsibility also follows delegation's installed executive-role-body route; a direct caller using a bounded helper does not adopt that role.
Every subagent has a shared-coordination read route through global Pi `AGENTS.md`, including generic, omitted-role, parent, and Luna consumers; the common skill body is not unconditionally included.
[Autonomous-work](../skills/autonomous-work/SKILL.md) and work-selection preserve direct ownership when no independent responsibility is assigned, and return delegated questions to their owners rather than retain parent verification or final priority selection.
Generic parent and Luna templates do not impose a competing role model.
Goal continuations require scope, persistence, and completion evidence and route through autonomous-work; they do not assign technical verification to the parent.

Native template checks establish discovery, instructions delivered to a child, inherited model/thinking, and specialist delegation exclusions.
Skill-loader checks establish catalog eligibility and description delivery.
Neither proves improved judgment, useful collaboration, or resolution of the Cocoa writing problem.
The earlier one-prompt Cocoa run still recommended IY; parsing or delivery checks do not change that evidence.
This rewrite does not require an efficacy study or new trial infrastructure.

The [template test guide](../config/pi-agent/README.md#subagent-templates) owns the ordinary configuration checks.
Shared skills and staged sandbox templates can come from different source trees; no installed-configuration switch is part of this proposal.
Use the documented reload or fresh-sandbox boundary before claiming an active session uses the changed instructions.
