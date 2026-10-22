---
name: goal-to-issue-graph
description: Turn a brief or broad goal into an actionable issue graph with observable root acceptance, bounded tickets, justified dependencies, and integration checks. Use when asked to break a goal into issues, create a dependency graph, or repair a graph whose tasks do not establish the promised outcome. Not for a selected change's file/commit plan, choosing an architecture, executing tickets, or tracker operations alone.
---

# Goal to issue graph

Work backward from the promised result, not forward from the current implementation's limitations.
A graph is useful only if completing its tasks establishes the user's goal without redefining success.

This skill owns decomposition and graph review, not implementation or automatic tracker mutation.
Use `implementation-plan` for a selected change's detailed plan.
Represent an unsettled architecture as a decision task; use [independent design deliberation](../architecture-design/references/deliberation.md) when design selection is also authorized.
For a staged new-tool project, follow `new-tool-development` rather than inventing a parallel approval process.

## 1. Recover the governing goal

Read the request, relevant decisions and authoritative project guidance before interpreting a short prompt through recent work.
Distinguish the whole objective from a current milestone, paused goal or worker assignment.
For a continuation, inspect the supporting records before treating a summary's constraints as user decisions.

Write a compact root contract:

- Required observable outcomes, including distinct correctness, coverage, usability and maintenance requirements actually supported by the request.
- The complete target population and authoritative inputs, revisions or environments.
- Allowed ways to satisfy each outcome, explicit exclusions and material unresolved decisions.

Cite the source of consequential constraints, especially compatibility, preservation and required human approval.
Do not promote an implementation guard, provisional policy or conservative assumption into a user requirement.
Ask focused questions when missing context changes the objective or permitted behavior; use `human-review-packets` for judgment calls.
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

When an early decision can materially change decomposition, distinguish ready assignments from provisional downstream work.
Fully specify the decision and architecture-independent outcomes first; revise affected downstream tickets after the choice.
A complete requirements inventory does not make the implementation breakdown execution-ready.
Require only the audit outputs needed by the bounded decision, not an exhaustive current-implementation audit by default.
Tracking parents and unresolved decision or decomposition work are not ready implementation assignments.
Name the first concrete action before marking a ticket ready.
If measurement or reproduction is needed for a decision, make that evidence gathering an actionable child rather than marking the decision parent ready.
After splitting, check each child's claims, prerequisites and first action against current code and inputs; a new child can inherit stale parent assumptions.

Each ticket needs enough detail for another agent to act without reconstructing hidden decisions:

- A stable local key, concrete title and useful result tied to the root contract.
- Bounded work, owning subsystem or principal files, and relevant authority/current evidence.
- Acceptance cases and the actual consumer or check that will establish success, including necessary negatives.
- Required facts, fixtures or component outputs, their producer/owner and completion dependencies.
- Material exclusions and uncertainty that affect the work.

### Acceptance and completion evidence

Give acceptance criteria stable identifiers such as `[A1]` and `[A2]`.
Keep an identifier when its meaning stays the same; assign a new one for a material change and never reuse retired identifiers.
Map each criterion to its proving boundary and evidence class, such as a CLI fixture, property test, benchmark, API result or artifact inspection.
State applicable contexts when different input origins or execution paths could change the result.

Specify a mandatory structured completion matrix derived from the current issue criteria, not an optional narrative summary.
Each criterion needs a row with its identifier, current criterion text or source reference, status and concrete supporting evidence.
Bind the matrix to the current issue-body snapshot and exact integrated revision being closed.
Reuse prior evidence only when the closeout contract permits it; retain the revision actually tested and establish applicability to the closing revision.
Never present prior evidence as having been run on the closing revision.
For permitted no-code-change outcomes, identify the applicable versioned inputs, products or receipts instead of inventing a fixing commit.
The issue's actual closeout owner—not merely a contributing worker—must complete and validate the matrix before claiming successful issue completion.
Require exact current criterion coverage, all criteria met, relevant evidence for each, and consistent issue/revision identities.
A shared passing suite may support several rows only when the evidence identifies what proves each criterion.
Missing criteria, partial results, stale criterion text, worker-only results and unreconciled revision mismatches block successful closure.
An investigation may complete with no change only when its acceptance permits that outcome; cancellation or supersession is not evidence that acceptance was met.

Use the tracker's supported matrix format and closeout validator; EDN is not required.
If tooling cannot enforce the checks, require explicit matrix validation at closeout and report the enforcement gap rather than claiming tool-enforced completion.
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
When independent components share semantics or materially increase resource use, place a useful combined checkpoint before final convergence.
Specify an actual interacting path and its negative cases; require a measured larger delivery when small-fixture success cannot establish viability.
Do not impose a full-profile run per ticket or invent universal resource limits.
Assign later interacting changes their affected cross-component regressions.

Make end-to-end acceptance use the actual supported producer, serialized or deployed representation, and final consumer where those boundaries matter.
Expected outputs are test assertions, not substitutes for generation or evidence of input validity.
Account for changed, lost and wrong results, not only gains.

For usability requirements, choose cases and expected behavior independently of whichever outputs later pass.
Explain how they support the quality claim and exercise known failure modes.
Keep whole-population coverage separate from sample-based quality claims.
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

State how changed authority, inputs, interfaces or integration products invalidate affected evidence.
Final acceptance must concern the same current inputs and product; reuse unaffected evidence instead of rerunning everything by habit.

## 8. Save or materialize only what was requested

Prefer existing project formats and trackers.
A small graph can be a ticket list with explicit edges; add machine-readable output or a renderer only for a concrete consumer.
Choose one authoritative representation and derive any index or diagram rather than maintaining competing graphs.
Validate the final reader-visible bodies and links, not only source syntax.

A local graph does not imply permission to create tracker issues, initialize a store or change implementation.
When tracker mutation is authorized, use the owning tracker procedure, inspect existing issues and reuse matches.
Keep planning keys distinct from actual IDs, record the mapping, translate dependencies and read back actual bodies/edges before claiming creation succeeded.
Shared contracts must survive outside temporary planning files; record them once in a durable owner and update child references.
If access is unavailable, deliver the local handoff and name the blocked tracker step without claiming it happened.

## Cross-domain check

For “index every document in the old archive and keep updates routine,” inventory the archive itself, not just formats today's extractor accepts.
Separate successful ingestion from actual searchability.
Plan format/input discovery, required support, an early mixed-format consumer check, whole-archive verification and a supported new-document update.
An unsupported PDF recorded as skipped is not a searchable document.
An explicitly permitted alternative representation can satisfy coverage only when it works through the search consumer; it does not excuse missing required extractor behavior.

## Handoff

Provide the root contract, bounded tickets, explained edges, identified acceptance criteria with verification mappings and material unresolved decisions.
Name the execution/closeout owner and supported matrix-validation procedure; leave unexecuted evidence explicitly pending.
State inspected and unexamined scope, whether the graph can expand through discovery, what validation actually ran, and whether tracker IDs exist.
Do not report planned checks as executed or the product as complete because its graph is ready.
