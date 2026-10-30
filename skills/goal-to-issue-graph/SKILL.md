---
name: goal-to-issue-graph
description: Turn a brief or broad goal into an actionable TicGit issue graph with observable root acceptance, bounded tickets, justified dependencies, and integration checks. Use when asked to break a goal into issues, create a dependency graph, or repair a graph whose tasks do not establish the promised outcome. Also use during authorized work when the agent feels overwhelmed by multiple unfinished outcomes, loses track of remaining work or dependencies, or repeatedly switches tasks without a clear completion condition; an explicit planning request is not required. Recover the governing goal and organize remaining work directly in TicGit. Not for a selected change's file/commit plan, choosing an architecture, ordinary execution of an already coherent ticket, a single difficult debugging problem, slow commands alone, or tracker operations alone.
---

# Goal to issue graph

Work backward from the promised result, not forward from the current implementation's limitations.
A graph is useful only if completing its tasks establishes the user's goal without redefining success.

This skill owns decomposition, graph review, and direct creation or revision of TicGit issues for the authorized project work, not implementation.
Use [ticgit](../ticgit/SKILL.md) for tracker operations; inspect the existing graph and reuse matching issues.
Do not require separate approval to materialize the graph within that work; an explicit read-only or proposal-only request still forbids tracker mutation.
Use `implementation-plan` for a selected change's detailed plan.
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

Cite the source of consequential constraints, especially compatibility, preservation and required human approval.
Do not promote an implementation guard, provisional policy or conservative assumption into a user requirement.
Ask focused questions when missing context changes the objective or permitted behavior.
Use `human-review-packets` for consequential approvals or questions that require substantial context; ask simple preferences or missing facts directly.
Continue independent investigation.
If uncertainty concerns discoverable facts rather than a user choice, assign a bounded discovery task with a concrete output and consuming task.
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

## 3. Make root closure explicit

Separate outcomes that can succeed independently.
For example, implementing every resolved rule does not prove every required item has a usable route, and covering items through exceptions does not prove the general rules are implemented.
Require both when the user requires both.

Define what successful completion means for each required item or workflow through the real consumer.
Keep allowed evidence modes distinct: a permitted manual exception need not meet an automated derivation's proof obligations, but it must still produce the promised result.
Do not invent fallback permission or require one mechanism universally when the goal permits alternatives.
A held, skipped, missing-input or unverified state may complete diagnosis; it cannot count as a successful item unless diagnosis is itself the requested outcome.

Keep the governing root contract stable as discovery changes the work.
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

When an early decision can materially change decomposition, distinguish ready assignments from provisional downstream work.
Fully specify the decision and architecture-independent outcomes first; revise affected downstream tickets after the choice.
A complete requirements inventory does not make the implementation breakdown execution-ready.
Require only the audit outputs needed by the bounded decision, not an exhaustive current-implementation audit by default.
Tracking parents and unresolved decision or decomposition work are not ready implementation assignments.
Name the first concrete action before marking a ticket ready.
If measurement or reproduction is needed for a decision, make that evidence gathering an actionable child rather than marking the decision parent ready.
After splitting, check each child's claims, prerequisites and first action against current code and inputs; a new child can inherit stale parent assumptions.

Each ticket needs enough detail for another agent to act without reconstructing hidden decisions:

- A concrete title and useful result tied to the root contract; use the tracker ID once the issue is created.
- Bounded work, owning subsystem or principal files, and relevant authority/current evidence.
- Acceptance cases and the actual consumer or check that will establish success, including necessary negatives.
- Required facts, fixtures or component outputs, their producer/owner and completion dependencies.
- Material exclusions and uncertainty that affect the work.

### Acceptance and completion evidence

Give acceptance criteria stable identifiers such as `[A1]` and `[A2]`.
Keep an identifier when its meaning stays the same; assign a new one for a material change and never reuse retired identifiers.
Map each criterion to its proving boundary and evidence class, such as a CLI fixture, property test, benchmark, API result or artifact inspection.
State applicable contexts when different input origins or execution paths could change the result.

Require an acceptance-evidence mapping for every current criterion, using the existing ticket's acceptance/evidence fields when they can express it clearly.
For each criterion, identify its current text or source reference, status and concrete supporting evidence.
Keep this mapping in one canonical record; link from handoffs and recovery state rather than maintaining parallel copies.
Use a separate completion matrix only when the existing record cannot make criterion coverage clear or an applicable governing workflow requires one.
Treat agent-authored workflow formats as revisable mechanisms, not user requirements; do not introduce stricter shared packaging merely to standardize closeout.
Identify the issue and exact integrated revision being closed, and preserve references to the criteria whose acceptance was checked.
Create additional snapshots only when existing versioned records cannot establish those identities.
Retain the revision actually tested and establish applicability to the closing revision; never present reused evidence as newly executed.
For permitted no-code-change outcomes, identify the applicable versioned inputs, products or receipts instead of inventing a fixing commit.
The issue's actual closeout owner—not merely a contributing worker—must check that every current criterion is met by applicable evidence before claiming successful completion.
A shared result may support several criteria when the mapping identifies what proves each one.
Downstream closeout records the acceptance decision and any new reconciliation, linking to existing evidence rather than reproducing its narrative.
Missing criteria, partial results, stale criterion text, unsupported worker claims and unreconciled revision mismatches block successful closure.
An investigation may complete with no change only when its acceptance permits that outcome; cancellation or supersession is not evidence that acceptance was met.

Use existing tracker validation where it checks this mapping; otherwise inspect it directly without creating another validation artifact by default.
Do not claim tool-enforced completion for checks performed only by inspection.
Do not build a new tracker or validation framework merely to write the plan.
Structural validation prevents omissions and stale-evidence mismatches; the closeout owner must still check that the evidence actually proves each criterion.
Planning defines this contract, not completed evidence or permission to execute the checks.

For risks that can invalidate an approach or prevent completion, name the observable trigger and affected outcome.
Assign an owner for the next decisive check or choice.
State what its plausible results change and when to stop the affected approach, revise the graph or obtain a user decision.
An investigation that rules out the planned route must hand off an owned next action, not leave only a blocked dependent.
Do not require a separate risk register or branches for ordinary tickets.

Use one canonical home for shared policy and cross-ticket acceptance contracts.
Link directly from each affected ticket and retain short local guards only where they prevent a concrete mistake.
Keep distinct case expectations beside their owner rather than repeating the common workflow in every body.
Give effort ranges only when requested and supported; distinguish component work, shared integration waits, uncertainty and elapsed time.
Do not sum concurrent allowances into an unsupported completion forecast.

## 5. Derive completion dependencies

State the edge direction: `A → B` means A supplies something needed to close B.
Explain that output or semantic prerequisite for every edge.
Priority, shared files, a common author and convenient sequencing are not dependencies.
Among ready implementation tasks, prioritize establishing or extending a consumer-visible result within governing milestone order.
Record scheduling priority separately; do not invent dependency edges to express this preference.
An unblocked ticket is not necessarily unowned or safe to edit concurrently; use `delegation` for actual assignments.

Assign each ticket bounded acceptance evidence; identify fixtures where needed and reuse suitable shared fixtures.
Do not assume the existence of a field proves the real-world fact it represents.
If a particular fixture needs external evidence, name the missing output and producer, and add that completion dependency before closure.
Do not make every component wait for an unrelated population-wide acquisition task.
Conditional or synthetic fixtures may test predicates but cannot replace required grounded real-case evidence.

Allow independent preparation where possible.
When a required dependency becomes concrete during discovery, update the graph rather than concealing it in prose or pretending the original graph was exhaustive.

## 6. Include integration, quality and maintenance where required

Assign these checks to graph work; do not execute implementation or product acceptance without authorization.
Reuse existing inspection and measurement evidence where valid.
For implementation goals, plan the smallest supported end-to-end result as early as its genuine prerequisites allow, even with only basic features.
Use the actual producer, intervening boundaries and final consumer; do not substitute hand-written intermediate outputs or bypass the boundary under test.
Extend the working path through repeated integration as capability and scale increase, rather than postponing consumer checks until final convergence.
If a working baseline already exists, exercise the changed path or next failing boundary instead of rebuilding a demonstration of unchanged behavior.
An early limited delivery establishes a working path, not full goal acceptance; retain all required features, population and quality conditions.
When independent components share semantics or materially increase resource use, place a useful combined checkpoint before final convergence.
Specify an actual interacting path and its negative cases; test consequential scale and interactions early enough to change the approach.
Require a measured larger delivery when small-fixture success cannot establish viability.
Do not impose a full-profile run per ticket or invent universal resource limits.
Assign later interacting changes their affected cross-component regressions.

Make end-to-end acceptance use the actual supported producer, serialized or deployed representation, and final consumer where those boundaries matter.
Expected outputs are test assertions, not substitutes for generation or evidence of input validity.
Account for changed, lost and wrong results, not only gains.

For usability requirements, choose cases and expected behavior independently of whichever outputs later pass.
Explain how they support the quality claim and exercise known failure modes.
Keep whole-population coverage separate from sample-based quality claims.
Distinguish diagnostic metrics from acceptance criteria: a measurement can inform a quality claim without defining success.
For each required quality claim, state which results prevent completion or require correcting or reconsidering the approach, and who owns the next action.
When the acceptable standard or a necessary user judgment is unresolved, keep that decision explicit; do not invent a cutoff or count reporting the result as satisfying the claim.
For maintainability requirements, choose demonstrations against the expected ongoing workflow and known maintenance risks, not merely an easy operation with prepared inputs.
For routine data updates, use the supported workflow, not case-specific code patches.
Include input preparation and recurring manual work when they are material sources of upkeep.
State what the chosen operation proves; add another only if a material part of the maintenance claim remains untested.
For example, adding a regular item may not exercise the required evidence-correction or input-refresh path.
Replaying one frozen snapshot proves reproducibility, not that updates are maintainable.

## 7. Review the graph in both directions

Trace every root criterion backward to tickets and consumer-visible evidence.
Trace every required ticket forward to a root criterion; remove unrelated work or mark it outside the required graph.
Check dependency existence, direction, reasons and cycles, and ensure every required node reaches the root.
Structural validity does not prove scope completeness, feasibility or implementation correctness.

Challenge closure with a previously excluded item, a missing fixture, an allowed alternative route, an interaction failure and a routine update where applicable.
Could every listed ticket close while the promised outcome still fails?
If yes, repair the acceptance or missing work rather than adding vague “review everything” tickets.
Use independent review when consequential scope or dependency judgment remains uncertain, not as a mandatory ceremony for a small obvious graph.
Check that the planned closeout rejects an omitted criterion, stale issue body, mismatched revision and a closed-but-unmet prerequisite.
Review reporting obligations in shared contracts as well as individual tickets.
Require a concrete consumer or evidence need for each mandated format; reuse existing versioned records when they establish the same criterion coverage and result identities.
Remove unnecessary matrices, copied bodies, hashes and validation reports without weakening the acceptance checks they were meant to support.

State how changed authority, inputs, interfaces or integration products invalidate affected evidence.
Final acceptance must concern the same current inputs and product; reuse unaffected evidence instead of rerunning everything by habit.

## 8. Create or update the TicGit graph directly

Create or reuse the root and bounded outcome issues directly in TicGit, unless the request is explicitly read-only or proposal-only.
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

Provide the root contract, bounded tickets, explained edges, identified acceptance criteria with verification mappings and material unresolved decisions.
Name the execution/closeout owner and canonical acceptance-evidence record; leave unexecuted evidence explicitly pending.
State inspected and unexamined scope, whether the graph can expand through discovery, what validation actually ran, and whether tracker IDs exist.
Do not report planned checks as executed or the product as complete because its graph is ready.
