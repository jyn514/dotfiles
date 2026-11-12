---
name: goal-to-issue-graph
description: Turn a brief or broad goal into an actionable issue graph with observable root acceptance, bounded tickets, justified dependencies, and integration checks. Use when asked to break a goal into issues, create a dependency graph, or repair a graph whose tasks do not establish the promised outcome. Also use during authorized work when the agent feels overwhelmed by multiple unfinished outcomes, loses track of remaining work or dependencies, or repeatedly switches tasks without a clear completion condition; an explicit planning request is not required. Recover the governing goal and organize remaining work in the repository's default issue tracker, or TicGit if none is specified. Not for working out one ticket's implementation path, choosing an architecture, ordinary execution of an already coherent ticket, a single difficult debugging problem, slow commands alone, or tracker operations alone.
---

# Goal to issue graph

The purpose of an issue graph is to enable sustained, substantive work without repeated human feedback.
Ask consequential questions requiring human judgment up front; investigate discoverable facts instead of asking the human to supply them.
For material uncertainty that execution must resolve, specify bounded investigations, how their results change the next action, and when to reconsider or stop the affected approach.
Identify unavoidable later human-feedback points without making independent work wait for them.
This purpose does not authorize execution.

Work backward from the promised result, not forward from the current implementation's limitations.
A graph is useful only if completing its tasks establishes the user's goal without redefining success.

The numbered stages make different promises; preserve those distinctions while allowing approach comparison and decomposition to inform each other.
First recover the goal and inspect the actual problem (§§1–2); then fix the root's success conditions while translating current knowledge into bounded tickets (§§3–4).
Those tickets may change as discovery resolves uncertainty, but their closure must continue to serve the stable root contract.
Next connect their outputs with justified dependencies and add applicable integration, quality, and maintenance work (§§5–6); review whether the whole graph can establish the root outcome (§7); create or update it in the selected tracker (§8); then hand it off.
A ready graph is a plan for product work, not evidence that the product already succeeds.

This skill owns decomposition, graph review, and direct creation or revision of issues in the selected tracker for the authorized project work, not implementation.
Use the repository's default issue tracker, or TicGit if none is specified.
Follow the repository's tracker guidance; for TicGit, use [ticgit](../ticgit/SKILL.md).
Inspect the existing graph and reuse matching issues.
Do not require separate approval to materialize the graph within that work; an explicit read-only or proposal-only request still forbids tracker mutation.
Use `implementation-plan` when explicitly asked to work out or review one ticket's implementation plan.
An already-actionable ticket needs no separate plan; keep any needed implementation detail in its existing record rather than a parallel artifact.
Represent an unsettled architecture as a decision task; use [independent design deliberation](../architecture-design/references/deliberation.md) when design selection is also authorized.
For a staged new-tool project, follow `new-tool-development` rather than inventing a parallel approval process.

## 1. Recover the governing goal

Read the request, relevant decisions and authoritative project guidance before interpreting a short prompt through recent work.
Distinguish the whole objective from a current milestone, paused goal or worker assignment.
For a continuation, inspect the supporting records before treating a summary's constraints as user decisions.

Define a compact root contract for the root issue:

- Required observable outcomes, including distinct correctness, coverage, usability and maintenance requirements actually supported by the request.
- The complete target population and authoritative inputs, revisions or environments.
- Allowed ways to satisfy each outcome, explicit exclusions and material unresolved decisions.
- The governing deadline and resource constraints, or an explicit answer that there is no fixed deadline.

Recover the deadline from the request and existing decisions before asking again.
If no deadline is established, ask the user what deadline the graph must meet; do not assume an open-ended schedule.
For a relative duration, establish its start and resulting deadline; replanning does not restart the clock.
Record an explicit "no fixed deadline" answer rather than inventing a limit.

Cite the source of consequential constraints, especially compatibility, preservation and required human approval.
Do not promote an implementation guard, provisional policy or conservative assumption into a user requirement.
Ask focused questions when missing context changes the objective or permitted behavior.
Use `human-review-packets` for consequential approvals or questions that require substantial context; ask simple preferences or missing facts directly.
Continue independent investigation.
Investigate discoverable facts during authorized planning rather than asking the user or assigning discovery by default.
If a genuine dependency prevents resolving them now, apply §4's justified-deferral rule and give the bounded discovery work a concrete output and consuming task.
Do not require a full specification before a graph can describe discovery work.

## 2. Inspect the actual problem

Read the relevant producers, inputs, consumers, tests, operational guidance and existing work.
Use repository evidence to distinguish completed capability, missing implementation, missing input facts, unverified behavior and genuinely unresolved requirements.
Do not turn a determined specification rule into a human decision because its implementation is missing.
Reuse existing facilities and valid completed evidence instead of planning them again.

For goals using “all” or “every,” inspect the original population, not only the subset the current pipeline accepts.
Look for boundary cases excluded by current parsers, filters, manifests or sampling.
A reconciled exclusion report does not prove successful coverage of those items.
Record evidence paths and what each receipt actually establishes; representative successes cannot establish whole-population completion.

### Sketch routes before committing to a breakdown

When the overall approach is unsettled, partially decompose credible candidates enough to explain how each produces the requested result.
Identify the input-to-consumer path, existing capabilities, new mechanisms, hardest work, required facts and consequential unknowns.
Use these sketches to compare approaches and remaining cost, not to commit to the current mechanism before alternatives are understood.
Do not require a full implementation graph for every candidate or choose an approach without explaining how it could work.
Within authorized design work, use `architecture-design` to settle architectural choices; preserve the authority boundaries above.
Refine sketches when decomposition reveals a difficulty that changes the comparison, then turn the selected route into executable issues.

Distinguish evidence sufficient to choose an approach from evidence that its finished implementation meets acceptance.
Current code, established patterns and a traced or worked representative case can justify a choice without demonstrating finished coverage.
Do not require an alternative to produce delivered gains before considering it while favoring already-implemented fragments of the current route.
Use a probe when its result changes the choice, not merely to find a larger collection of locally successful repairs.
If repeated probes yield only local repairs without a credible route to the whole outcome, reopen the approach comparison using `work-selection`.
Do not merely enlarge the repair bundle or treat planning as a requirement to prove the finished product in advance.

## 3. Make root closure explicit

Separate outcomes that can succeed independently.
For example, implementing every resolved rule does not prove every required item has a usable route, and covering items through exceptions does not prove the general rules are implemented.
Require both when the user requires both.

Define what successful completion means for each required item or workflow through the real consumer.
Keep allowed evidence modes distinct: a permitted manual exception need not meet an automated derivation's proof obligations, but it must still produce the promised result.
Do not invent fallback permission or require one mechanism universally when the goal permits alternatives.
A held, skipped, missing-input or unverified state may complete diagnosis; it cannot count as a successful item unless diagnosis is itself the requested outcome.

The root contract answers what must ultimately be true; intermediate tickets describe the current route toward it.
Keep the governing root contract stable as discovery changes that route.
Preserve governing requirements, not every acceptance condition introduced by an earlier plan.
When an approach changes, remove or supersede obsolete intermediate milestones and dependencies while retaining required semantic acceptance.
Check that the replacement can achieve the root outcome without first completing the abandoned approach.
Record cancelled, duplicate, superseded and administrative closes as non-completion, with a reason and successor where applicable.
Update consuming dependencies; a closed-but-unmet prerequisite cannot count as successful completion.
Finishing the initial task list is not permission to shrink the population or weaken required acceptance.
Separate completion of the planning request from completion of the planned product.

## 4. Draft bounded outcome tickets

Choose the smallest useful deliverables with observable acceptance, not one ticket per file, implementation layer or failure message.
Group failures under a shared invariant when one general correction addresses them.
Leave low-risk mechanics to implementation; do not manufacture interfaces or exact file edits for unsettled designs.
For implementation goals, define bounded cross-component outcomes that establish and extend a working end-to-end path.
Do not merely reorder whole-subsystem tickets that still defer integration until every component is complete.

Require every executable task to have a specific deliverable, explicit scope and an observable stopping condition.
A title and acceptance criteria do not bound a task if completing it still requires deciding which substantial work to include or what counts as enough.
Recursively split unbounded tasks into smaller outcome tasks, checking each child by the same rule until every executable leaf is bounded.
Preserve the parent's required outcome across the children, including integration; narrowing each child must not silently discard required work.
Stop splitting when the leaf can be completed and checked without another substantial scope or decomposition decision.
Do not substitute arbitrary time limits, one-file tasks or isolated implementation phases for useful bounded outcomes.

Tracking parents may aggregate broad outcomes, but are not executable assignments.
Resolve substantial scope and approach choices that available evidence and authorized planning can settle.
Investigate discoverable facts during planning rather than leaving implementation workers to select substantial scope later.
For each substantial choice left open, explain why planning cannot resolve it.
Identify the required user judgment, genuinely unavailable external evidence, or bounded implementation experiment needed to decide it.
If a governing scope or stage boundary prevents deciding here, cite it rather than expanding planning authority.
Naming an owner, filing a discovery ticket or marking the choice pending does not supply that justification.
When such a dependency prevents a sound split, define bounded work through the next consequential decision and its result-dependent next actions.
Keep the remaining parent explicitly pending that decomposition; calling it provisional does not make it bounded or ready.
Already-authorized bounded tasks need not wait for decomposition of independent branches.
Do not invent speculative implementation children merely to make the graph look complete.

For example, “improve import support” is not a bounded assignment.
“Support the documented CSV dialect through the import consumer, including its malformed-row cases” can be one bounded child.
If the parent requires other formats too, retain those obligations and continue decomposing them; completing CSV support does not complete the parent.

When an early decision can materially change decomposition, distinguish ready assignments from provisional downstream work.
Fully specify the decision and architecture-independent outcomes first; revise affected downstream tickets after the choice.
A complete requirements inventory does not make the implementation breakdown execution-ready.
Require only the audit outputs needed by the bounded decision, not an exhaustive current-implementation audit by default.
Tracking parents and unresolved decision or decomposition work are not ready implementation assignments.
Name the first concrete action before marking a ticket ready.
If measurement or reproduction is needed for a decision, make that evidence gathering an actionable child rather than marking the decision parent ready.
After splitting, check each child's claims, prerequisites and first action against current code and inputs; a new child can inherit stale parent assumptions.

For every implementation ticket marked ready, state the chosen approach and its basis in current code, an established pattern or applicable experimental evidence.
Name the mechanism and the existing path it extends or replaces, where applicable; an outcome such as “support CSV import” does not settle how to implement it.
Check that the cited basis supports the step this ticket must add, not merely a nearby helper or a manually supplied intermediate result.
Record material implementation uncertainty and what finding would require reconsidering the approach.
Treat an approach as settled when it is chosen and grounded, not proven successful in advance.
If an unresolved choice could materially change scope, dependencies or maintenance costs, the ticket is not ready for implementation.
Resolve the choice during authorized planning where possible; defer it to bounded discovery or decision work only with the justification above.
Routine implementation choices and debugging remain part of implementation.
Do not require a complete implementation plan, a prototype for every change or a new approval step to establish readiness.

Each ticket needs enough detail for another agent to act without reconstructing hidden decisions:

- A concrete title and useful result tied to the root contract; use the tracker ID once the issue is created.
- Bounded work, owning subsystem or principal files, and relevant authority/current evidence.
- Acceptance cases and the actual consumer or check that will establish success, including necessary negatives.
- Required facts, fixtures or component outputs, their producer/owner and completion dependencies.
- Material exclusions and uncertainty that affect the work.

### Check practical feasibility before readiness

Settled scope and a grounded approach do not establish that work is practical.
Before marking implementation ready, establish a credible basis for completing it within governing time and resource constraints.
Where no explicit budget exists, assess whether the cost is proportionate to the required result without inventing an arbitrary limit.
Use existing code, comparable completed work and applicable measurements.
Account for the hardest step, target scale, input preparation, integration and required human or external waits.
Record material cost assumptions and their evidentiary basis in the existing ticket.
Check the combined route too: splitting expensive work into small tickets does not reduce its total cost.
Compare the selected full-goal route with the strongest credible available alternative using [work-selection](../work-selection/SKILL.md).
Justify any additional cost by required quality, maintenance, useful outcomes or consequential learning; do not manufacture alternatives or assume the fastest route wins.
For a fixed deadline, establish a credible elapsed-time forecast for delivering the original goal within the time remaining.
Use [work-estimation](../work-estimation/SKILL.md) for that assessment.
Include genuine overlap, required verification and likely repair, and unavoidable waits.
Include decision experiments and their consequential follow-up work; timing only the next increment does not establish deadline fit.

If known costs are unreasonable, revise the approach or surface the conflict with the governing constraints without weakening the goal.
Where feasibility uncertainty could invalidate completion, resolve it with the cheapest credible representative check before committing the bulk of the effort.
Use inspection and existing evidence during planning where sufficient.
If implementation is needed, specify the bounded learning task below and keep the affected implementation commitment pending its result.
Exercise the actual bottleneck and consequential scale; success with prepared inputs or an easy subcase may not support the cost claim.
A promise to reconsider after expensive failure is not evidence of feasibility.

Match checks to the actual risk; do not require exact estimates, a prototype, a separate de-risking ticket or a new approval for every task.
Routine work with applicable evidence needs no additional experiment.

### Bound implementation needed to choose a direction

Implementation needed to choose a direction is itself a bounded learning task, not permission to defer planning into execution.
State in its existing ticket:

- The consequential choice between approaches.
- The missing evidence and why implementation is the cheapest credible way to obtain it.
- Plausible results that would lead to different choices, and the next action for each.
- The minimum implementation and observation needed for credible evidence before committing further.

If the task cannot specify these, continue resolving its decision framing and decomposition during planning.
Keep the affected implementation pending while doing so; do not hand the unresolved planning to an implementation worker.
Check that the proposed results can support the consequential choice, not merely establish that a local feature works.
For example, a prototype may be needed to choose between streaming and indexed import when references could require retaining the whole input.
Its fixtures must exercise those references; successfully importing a flat CSV file cannot settle that choice.
If existing inspection or evidence settles the decision more cheaply, use it instead of inventing an implementation experiment.

Plan through the next consequential decision without assuming subsequent small successes will add up to the root outcome.
Do not require every future implementation ticket in advance.
If an experiment reveals further uncertainty, revise the affected plan explicitly.
Selecting another small task does not resolve the remaining strategy.

### Acceptance and completion evidence

Ticket acceptance turns bounded work into a checkable promise, and closeout must show that the promise was met on the revision being closed.
Follow each criterion from its current wording, through the result that tests it, to the revision that result supports, and finally to the closeout owner's acceptance decision.
Use the existing ticket fields and applicable evidence to make that chain inspectable; do not create parallel records just to restate it.

For example, a CLI ticket might say criterion `[A1]`: “with the quiet option enabled, the command prints no progress messages.”
Its existing evidence field can point to a CLI test receipt that records the command, option, observed output, and tested revision.
If the ticket is later closed against a newer integrated revision, the closeout owner checks whether that receipt still applies to the closing revision; if a relevant change makes that uncertain, record the reconciliation or obtain applicable evidence before accepting `[A1]`.
A populated evidence field and a passing result at an earlier revision do not by themselves prove that the current criterion is met on the revision being closed.

#### Identify and map each criterion

Give acceptance criteria stable identifiers such as `[A1]` and `[A2]`.
Keep an identifier when its meaning stays the same; assign a new one for a material change and never reuse retired identifiers.
Map each criterion to its proving boundary and evidence class, such as a CLI fixture, property test, benchmark, API result or artifact inspection.
State applicable contexts when different input origins or execution paths could change the result.

Require an acceptance-evidence mapping for every current criterion, using the existing ticket's acceptance/evidence fields when they can express it clearly.
For each criterion, identify its current text or source reference, status and concrete supporting evidence.
In the example, `[A1]` remains the identifier while its meaning is unchanged, and its mapping points to the CLI receipt and states what output in that receipt establishes the criterion.
A shared result may support several criteria when the mapping identifies what proves each one.
Keep this mapping in one canonical record; link from handoffs and recovery state rather than maintaining parallel copies.
Use a separate completion matrix only when the existing record cannot make criterion coverage clear or an applicable governing workflow requires one.
Treat agent-authored workflow formats as revisable mechanisms, not user requirements; do not introduce stricter shared packaging merely to standardize closeout.

#### Tie evidence to the revision being closed

Identify the issue and exact integrated revision being closed, and preserve references to the criteria whose acceptance was checked.
Create additional snapshots only when existing versioned records cannot establish those identities.
Retain the revision actually tested and establish applicability to the closing revision; never present reused evidence as newly executed.
For `[A1]`, if the closing revision changes the command's output path, the earlier receipt cannot be treated as proof without resolving that mismatch; if the relevant behavior is unchanged and applicability is established, reuse it without claiming a new test run.
For permitted no-code-change outcomes, identify the applicable versioned inputs, products or receipts instead of inventing a fixing commit.

#### Decide and record closure

The issue's actual closeout owner—not merely a contributing worker—must check that every current criterion is met by applicable evidence before claiming successful completion.
Downstream closeout records the acceptance decision and any new reconciliation, linking to existing evidence rather than reproducing its narrative.
Missing criteria, partial results, stale criterion text, unsupported worker claims and unreconciled revision mismatches block successful closure.
An investigation may complete with no change only when its acceptance permits that outcome; cancellation or supersession is not evidence that acceptance was met.

#### Validate without overstating the result

Use existing tracker validation where it checks this mapping; otherwise inspect it directly without creating another validation artifact by default.
Do not claim tool-enforced completion for checks performed only by inspection.
Do not build a new tracker or validation framework merely to write the plan.
Structural validation prevents omissions and stale-evidence mismatches; the closeout owner must still check that the evidence actually proves each criterion.
Planning defines this contract, not completed evidence or permission to execute the checks.

#### Work through consequential failure

Acceptance contracts and evidence records explain what closure means; they do not replace decisions about whether the route remains viable.
For a risk that can invalidate the route or prevent completion, name its observable trigger, affected outcome and decision owner.
Work through a plausible adverse result: what can that owner actually assign next, from which usable inputs or working code, with what time remaining?
Resolve choices available planning can settle; “stop and reconsider” does not resolve a known alternative's scope or dependencies.
Do not require a separate risk register or branches for ordinary tickets.

For example, an eight-day import delivery chooses a parser rewrite; extending the existing parser is a credible smaller alternative.
**Insufficient:** “Check correctness and scale early; if the rewrite fails, the owner stops and reconsiders. A smaller route exists.”
**Worked through:** Assume the first integrated check rules out the rewrite after two days.
The format-support ticket still depends on that rewrite, so naming the alternative leaves no executable next assignment.
Ground the smaller route in the existing parser, replace the rewrite-only dependency with its actual prerequisites, and specify the first ready action.
Switch to that route if the integrated check shows the rewrite cannot meet required correctness and scale within the deadline.
Check that switching, remaining implementation, integration and verification fit the six days left and still satisfy the original import requirements.
Do not plan the fallback against the original eight-day budget or require it to finish the abandoned rewrite first.

**No valid fallback:** If the existing parser cannot preserve required cross-record references, format extensions alone cannot satisfy the same goal.
Do not label them a fallback by dropping that requirement.
Revise the approach or surface the constraint conflict; a known alternative is useful only if it remains a credible route to the governing outcome.

Use one canonical home for shared policy and cross-ticket acceptance contracts.
Link directly from each affected ticket and retain short local guards only where they prevent a concrete mistake.
Keep distinct case expectations beside their owner rather than repeating the common workflow in every body.
Do not invent effort ranges for every ticket.
Use grounded elapsed-time estimates where needed to assess deadline fit; otherwise give effort ranges only when requested and supported.
Distinguish component work, shared integration waits, uncertainty and elapsed time.
Do not sum concurrent allowances into an unsupported completion forecast.

## 5. Derive completion dependencies

Tickets define deliverables; dependencies explain which deliverable must exist before another can be closed.
Keep that distinction explicit: dependency edges encode closure prerequisites, while priority and safe concurrent ownership remain separate concerns.

State the edge direction: `A → B` means A supplies something needed to close B.
Explain that output or semantic prerequisite for every edge.
Priority, shared files, a common author and convenient sequencing are not dependencies.
Among ready implementation tasks, prioritize establishing or extending a consumer-visible result within governing milestone order.
Record scheduling priority separately; do not invent dependency edges to express this preference.
An unblocked ticket is not necessarily unowned or safe to edit concurrently; organizers use delegation's [executive procedure](../delegation/references/executive.md) for actual assignments.

Assign each ticket bounded acceptance evidence; identify fixtures where needed and reuse suitable shared fixtures.
Do not assume the existence of a field proves the real-world fact it represents.
If a particular fixture needs external evidence, name the missing output and producer, and add that completion dependency before closure.
Do not make every component wait for an unrelated population-wide acquisition task.
Conditional or synthetic fixtures may test predicates but cannot replace required grounded real-case evidence.

Allow independent preparation where possible.
When a required dependency becomes concrete during discovery, update the graph rather than concealing it in prose or pretending the original graph was exhaustive.
When expansion materially changes the route, including through cumulative small additions, reconsider selecting that work and recheck whole-goal sufficiency, feasibility, remaining deadline and scheduling using §§4 and 7.
Record revised assumptions and forecasts in the existing canonical graph records.
Ordinary decomposition that preserves the agreed scope and cost needs no full route review or added approval.

## 6. Include integration, quality and maintenance where required

Assign these checks to graph work; do not execute implementation or product acceptance without authorization.
Reuse existing inspection and measurement evidence where valid.

### Plan an early end-to-end path

Dependencies should expose the earliest point at which the graph can demonstrate a real result, not arrange components into a long queue that postpones integration.
For implementation goals, plan the smallest supported end-to-end result as early as its genuine prerequisites allow, even with only basic features.
Use the actual producer, intervening boundaries and final consumer; do not substitute hand-written intermediate outputs or bypass the boundary under test.
Extend the working path through repeated integration as capability and scale increase, rather than postponing consumer checks until final convergence.
If a working baseline already exists, exercise the changed path or next failing boundary instead of rebuilding a demonstration of unchanged behavior.
An early limited delivery establishes a working path, not full goal acceptance; retain all required features, population and quality conditions.

### Check interactions and scale

When independent components share semantics or materially increase resource use, place a useful combined checkpoint before final convergence.
Specify an actual interacting path and its negative cases; test consequential scale and interactions early enough to change the approach.
Require a measured larger delivery when small-fixture success cannot establish viability.
Do not impose a full-profile run per ticket or invent universal resource limits.
Assign later interacting changes their affected cross-component regressions.

Make end-to-end acceptance use the actual supported producer, serialized or deployed representation, and final consumer where those boundaries matter.
Expected outputs are test assertions, not substitutes for generation or evidence of input validity.
Account for changed, lost and wrong results, not only gains.

### Set usability acceptance

For usability requirements, choose cases and expected behavior independently of whichever outputs later pass.
Explain how they support the quality claim and exercise known failure modes.
Keep whole-population coverage separate from sample-based quality claims.
Distinguish diagnostic metrics from acceptance criteria: a measurement can inform a quality claim without defining success.
For each required quality claim, state which results prevent completion or require correcting or reconsidering the approach, and who owns the next action.
When the acceptable standard or a necessary user judgment is unresolved, keep that decision explicit; do not invent a cutoff or count reporting the result as satisfying the claim.

### Demonstrate maintainability

For maintainability requirements, choose demonstrations against the expected ongoing workflow and known maintenance risks, not merely an easy operation with prepared inputs.
For routine data updates, use the supported workflow, not case-specific code patches.
Include input preparation and recurring manual work when they are material sources of upkeep.
State what the chosen operation proves; add another only if a material part of the maintenance claim remains untested.
For example, adding a regular item may not exercise the required evidence-correction or input-refresh path.
Replaying one frozen snapshot proves reproducibility, not that updates are maintainable.

## 7. Review the graph in both directions

The preceding stages build a route from root outcomes through ticket deliverables to evidence.
Review that route from both ends: every root criterion must reach proving work, and every required ticket must contribute to a root criterion.
Ask whether an authorized agent can continue substantive work without the user present, including what consequential success or failure findings change its next action.
Resolve missing human choices or result-dependent next actions rather than leaving the user to notice when the work needs redirection.

Trace every root criterion backward to tickets and consumer-visible evidence.
Trace every required ticket forward to a root criterion; remove unrelated work or mark it outside the required graph.
Check dependency existence, direction, reasons and cycles, and ensure every required node reaches the root.
Check every executable leaf for a specific deliverable, explicit scope and an observable stopping condition; recursively split any that still fail this check.
For every implementation ticket marked ready, check its approach, grounding, practical feasibility and material uncertainty against §4.
Bounded acceptance cases alone do not establish readiness.
Check whether the combined route meets the remaining deadline and resource constraints, not just whether each ticket looks manageable.
Review its selection against the strongest credible available alternative and the basis for any additional cost as in §4.
When approach choice is open, check that candidates were not all confined to an agent-selected mechanism.
Check that alternatives were not required to demonstrate finished delivery before consideration; apply the planning-evidence distinction in §2.
For each substantial unresolved choice, check the §4 justification for why planning cannot settle it and the work through the next decision.
Check that each justified deferral has owned bounded discovery or decision work and leaves dependent implementation pending.
For implementation needed to choose a direction, check the decision-changing evidence and result-dependent next actions required in §4.
Do not call the whole graph execution-ready while it still contains such unresolved decomposition.
Structural validity does not prove scope completeness, feasibility or implementation correctness.

Challenge closure with a previously excluded item, a missing fixture, an allowed alternative route, an interaction failure and a routine update where applicable.
Could every listed ticket close while the promised outcome still fails?
If yes, repair the acceptance or missing work rather than adding vague “review everything” tickets.

Also ask which tickets or groups of tickets could be omitted while still credibly achieving the governing outcome.
Relevance alone does not establish necessity: state what part of the governing outcome or its required evidence would remain unmet without the work.
Distinguish required outcomes, prerequisites of the chosen approach and useful extras.
For approach-specific prerequisites, check whether a cheaper credible route avoids the whole group; a valid dependency does not make its parent mechanism necessary.
For example, a representation rewrite may require migration, adapters, cache changes and tests.
Each child can contribute through the rewrite without establishing that the rewrite is needed to achieve the goal.
Remove unnecessary work from the required graph or make it explicitly optional, updating affected dependencies without discarding governing requirements.
Retain additional work when its expected benefit justifies its cost against the remaining deadline, using §4's route comparison.
Do not demand a mathematically minimal graph or treat required quality, verification and maintenance as optional merely because they do not add features.

Use independent review when consequential scope or dependency judgment remains uncertain, not as a mandatory ceremony for a small obvious graph.
Check that the planned closeout rejects an omitted criterion, stale issue body, mismatched revision and a closed-but-unmet prerequisite.
Review reporting obligations in shared contracts as well as individual tickets.
Require a concrete consumer or evidence need for each mandated format; reuse existing versioned records when they establish the same criterion coverage and result identities.
Remove unnecessary matrices, copied bodies, hashes and validation reports without weakening the acceptance checks they were meant to support.

State how changed authority, inputs, interfaces or integration products invalidate affected evidence.
Final acceptance must concern the same current inputs and product; reuse unaffected evidence instead of rerunning everything by habit.

## 8. Create or update the issue graph directly

Create or reuse the root and bounded outcome issues directly in the selected tracker, unless the request is explicitly read-only or proposal-only.
Keep the graph, dependencies, and acceptance records in those issues; link existing authoritative specifications and evidence rather than copying them.
Do not require an intermediate Markdown plan, writeup, or separate materialization approval.
Files needed as CLI input are transport, not a second maintained plan.
Add an index, diagram, or other representation only for a concrete consumer, and derive it from the tracker rather than maintaining competing graphs.

Use actual issue IDs for dependencies and handoffs; translate temporary planning keys if used.
Read back the actual bodies, links, and dependency edges before claiming creation or revision succeeded.
Record shared contracts once in the root issue or link their existing authoritative owner from affected children.
Issue creation does not authorize implementation beyond the existing task, tracker initialization, or tracker administration.
If tracker access is unavailable, report the blocked tracker step without claiming it happened or silently substituting a Markdown plan.

## Cross-domain check

For “index every document in the old archive and keep updates routine,” inventory the archive itself, not just formats today's extractor accepts.
Separate successful ingestion from actual searchability.
Plan format/input discovery and required support around an initial supported archive document passing through actual ingestion and search.
Expand that working path through mixed-format consumer checks, whole-archive verification and a supported new-document update.
An unsupported PDF recorded as skipped is not a searchable document.
An explicitly permitted alternative representation can satisfy coverage only when it works through the search consumer; it does not excuse missing required extractor behavior.

## Handoff

For graph creation or revision, claim planning complete only when substantial choices resolvable during planning are settled.
Remaining deferrals must meet §4.
A settled task list is not a completed plan without a credible feasibility basis for its required work and combined route.
When there is a fixed deadline, the route must plausibly deliver the original goal by that deadline, not merely finish an initial increment.
An unknown deadline must be resolved with the user before claiming planning complete.
A graph that merely labels unfinished planning is not a completed plan.
If a genuine dependency prevents completion, report the affected planning as incomplete, name that dependency and distinguish independently ready work.
Do not substitute a status report for completing planning that remains possible within the request.

Provide the root contract, bounded tickets, explained edges, identified acceptance criteria with verification mappings and material unresolved decisions.
Name the execution/closeout owner and canonical acceptance-evidence record; leave unexecuted evidence explicitly pending.
State inspected and unexamined scope, whether the graph can expand through discovery, what validation actually ran, and whether tracker IDs exist.
Do not report planned checks as executed or the product as complete because its graph is ready.
