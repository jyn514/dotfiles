---
name: design-deliberation
description: Orchestrate the smallest useful workflow for uncertain software-design decisions using independent alternatives, repository evidence, critique, optional fusion, and fixed-set review. Use for genuine design forks, legacy architectural pain, or implementation tasks requiring explicit design selection.
---

# design-deliberation

## Purpose

Coordinate the Pi design skills for uncertain software-design decisions. Choose the smallest useful workflow, preserve independent alternatives long enough to compare them, prefer repository evidence over model taste, and stop before implementation unless the user explicitly asks to proceed.

This is an orchestration skill. It should delegate substantive work to the narrower skills rather than reimplementing their logic.

## Inputs

- the user's design question or implementation task
- explicit constraints and non-goals
- repository context and history when available
- any existing candidate designs or prior analysis

## Core rule

Use the minimum machinery justified by the uncertainty.

Do not run the full deliberation chain merely because the skills exist. The point is better decisions per unit of time and tokens, not maximal ceremony.

## Workflow selection

First classify the task.

### Broad project-improvement goal

For goals such as “make this project better”, “find the highest-leverage improvement”, or “what should I work on next?”, start with `opportunity-scan`. Do not begin from recent commits, the current diff, or whatever subsystem dominates the parent conversation. Recent activity is evidence of attention, not evidence of importance.

Use:

1. `opportunity-scan` to map the project and shortlist important opportunities across distinct subsystems;
2. `pain-axis` only after an opportunity area has been selected, when repository history can test whether the pain is recurring;
3. `design-space-scout` only if the selected opportunity contains a genuine design fork;
4. continue with `independent-plan` → `cross-critic` → optional `fusion-candidate` → `council-review` when multiple serious designs remain.

Do not ask `pain-axis` to decide which project area matters most. Its job is to investigate an area, not choose the area.

### Small or mostly-local change

Use:

1. `boundary-declaration`
2. `second-user` when a new abstraction/generalization is proposed
3. `ratchet` when a concrete invariant or historical failure can be checked mechanically

Do not generate three plans unless there is a real design fork.

### Genuine architecture/design decision

Use:

1. `pain-axis` when repository history is likely to contain useful evidence
2. `design-space-scout`
3. `independent-plan` once per viable brief, in isolated contexts when possible
4. `cross-critic`
5. `fusion-candidate` only when the critic identifies cleanly composable parts
6. `council-review`

Then, if a candidate is selected and implementation is requested:

7. `boundary-declaration`
8. `second-user`
9. `ratchet`

### Legacy or failure-prone subsystem

Start with `pain-axis` unless history is unavailable or clearly irrelevant. Feed its factual output into the scout and planners as evidence, not as a design mandate.

### Long autonomous implementation run

After a design has been selected:

1. run `boundary-declaration` before substantial editing;
2. use `second-user` whenever the implementation introduces a new abstraction;
3. use `ratchet` repeatedly as concrete invariants and failure modes become known.

Do not use `council-review` as a substitute for mechanical checks that already exist.

## Full deliberation procedure

### 0. For broad goals, choose the problem before designing the solution

If the user supplied a broad project-improvement goal rather than a concrete design question, invoke `opportunity-scan` first.

The opportunity scan must:

- construct a coarse project map before ranking opportunities;
- sample across subsystems and across time;
- deliberately consider neglected or low-churn areas;
- require independent evidence before treating recent work as high leverage;
- return a small cross-project shortlist before selecting an area.

Only after an opportunity area is selected should `pain-axis` investigate that area in depth. Feed the resulting evidence into later planning as evidence, not as a design mandate.

If the opportunity is already concrete and local, skip the multi-plan workflow unless a genuine design fork remains.

### 1. Gather evidence without choosing a design

For a concrete selected area, invoke `pain-axis` when historical evidence may matter.

Keep its output factual. Do not allow historical coupling or past architecture to silently become the default solution.

### 2. Diversify the design space

Invoke `design-space-scout` with the task, constraints, relevant repository context, and any `pain-axis` evidence.

The scout should return up to three viable, materially distinct briefs. If fewer than three real regions exist, use fewer; never fabricate a weak third option.

The scout's rejected forks are provisional. Preserve them for later review.

### 3. Elaborate candidates independently

Invoke `independent-plan` separately for each scout brief.

Important isolation rule:

- each planner sees the shared task, constraints, factual evidence, and its own brief;
- it must not see sibling plans;
- it may inspect the repository independently;
- it may reject a scout premise when concrete evidence makes it untenable.

Assign stable opaque candidate IDs such as A, B, and C outside the model outputs.

If fewer than two viable plans survive, stop the multi-candidate workflow and report why; a council has no useful diversity to compare.

### 4. Critique without collapsing the candidates

Invoke `cross-critic` on the fixed surviving candidate set.

The critic must first compare the candidates without seeing the scout's rejected forks. After that independent comparison, expose the rejected forks and ask whether any important region was pruned prematurely.

The critic may identify potentially composable components, but must not silently rewrite A/B/C.

### 5. Optionally construct one fusion candidate

Invoke `fusion-candidate` only if the critic identified components that appear cleanly separable and compatible.

`NO_FUSION` is a normal outcome.

If a fusion candidate D is created:

- preserve explicit provenance for every component taken from A/B/C;
- state rejected/superseded components;
- state the composition assumptions and new risks;
- treat D exactly like any other candidate.

Never allow synthesis to inherit authority merely because it contains pieces from several plans.

### 6. Freeze the candidate set and review it

Invoke `council-review` on the fixed candidate set `{A, B, C, D?}` plus the critic report and factual evidence.

Once this stage starts:

- no candidate E may be invented;
- no existing candidate may be rewritten;
- candidate identity/provider information should be hidden when practical;
- candidate ordering should not be treated as meaningful.

Valid outcomes are:

- `SELECT <candidate>`
- `EQUIVALENT <candidate-set>`
- `ABSTAIN`

`SELECT D` is ordinary selection, not a special fusion outcome.

If the council returns `ABSTAIN`, surface the missing evidence and cheapest useful inquiry. Do not manufacture a winner merely to finish the workflow.

## After selection

A selected plan is still a design hypothesis, not verification.

Before implementation, invoke `boundary-declaration` to make ownership, state, lifecycle, and effect boundaries explicit.

During implementation:

- invoke `second-user` when a new reusable abstraction appears;
- invoke `ratchet` when an important invariant can be turned into a mechanical check.

Prefer tests, type checks, static analysis, benchmarks, repository facts, and demonstrated failure cases over additional model votes whenever those are available.

## Existing candidates

If the user already supplied two or more serious candidate designs, skip `design-space-scout` unless an important region appears missing. Treat the supplied designs as the fixed initial candidates and begin with independent elaboration or `cross-critic`, depending on their level of detail.

If the user supplied one design and asks whether it is good, do not automatically manufacture alternatives. First decide whether there is a genuine unresolved design fork. For a local/low-risk decision, `boundary-declaration` or `second-user` may be sufficient.

## Cost control

The default cost-control strategy is structural, not numerical:

- do not deliberate on trivial choices;
- use at most three initial plans;
- run planners in parallel when possible;
- do not add planner revision rounds by default;
- construct at most one fusion candidate;
- do not recursively debate;
- stop on `EQUIVALENT` or `ABSTAIN` instead of spending tokens forcing convergence.

If the environment exposes model cost/usage, report it, but do not require cost accounting for the skill to function.

## Output to the user

Default output should be compact and decision-oriented:

- selected candidate, equivalent set, or abstention;
- 2–5 decisive reasons;
- important uncertainty or missing evidence;
- whether a fusion candidate was considered;
- next useful action.

Do not dump every intermediate transcript unless the user asks.

## Invariants

Preserve these properties even if the exact workflow changes:

0. **Problem selection before solution search.** Broad project goals use `opportunity-scan`; recent activity is never treated as importance by default.
1. **Diversity before elaboration.** Distinct alternatives come from different underlying design decisions, not wording noise.
2. **Isolation during generation.** Initial planners do not see sibling proposals.
3. **Evidence before taste.** Repository facts and mechanical checks outrank model preference.
4. **Candidates stay distinct.** Critique annotates alternatives rather than prematurely merging them.
5. **Fusion is explicit and non-privileged.** A synthesis must name its provenance and compete with its sources.
6. **Selection is a separate operation.** The final reviewer receives a fixed candidate set and cannot invent a new winner.
7. **Abstention is valid.** Missing evidence can be the correct result.
8. **Implementation is separate.** Deliberation does not edit the repository unless the user separately requests implementation.

## Anti-patterns

Do not:

- start a broad project-improvement goal from recent commits or the current working area; run `opportunity-scan` first;
- ask three agents the same prompt and call stochastic variation “design diversity”;
- assign arbitrary personas merely to force disagreement;
- let a critic rewrite all candidates into its preferred vocabulary;
- ask “should we merge B into A?” before independently identifying what is valuable or incompatible about A and B;
- automatically prefer a fusion candidate;
- keep adding review rounds until models agree;
- treat council consensus as proof;
- use historical evidence as an excuse to preserve the status quo;
- introduce abstractions for hypothetical future users;
- weaken a mechanical invariant check merely so implementation can continue.

## Escalation path

Only add heavier machinery after observing a concrete failure of this workflow.

Examples:

- repeated scout framing failures → add an independent design-space challenge;
- council repeatedly abstains on obtainable evidence → add an inquiry/evidence-gathering loop;
- selected designs repeatedly fail only after implementation → consider speculative implementation branches;
- long runs repeatedly regress known invariants → strengthen `ratchet` integration.

Do not build speculative branches, persistent hypothesis ledgers, or delayed-commit infrastructure merely because they are theoretically appealing. Make observed failures earn the complexity.
