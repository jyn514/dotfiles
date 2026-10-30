---
name: session-closeout
description: Close out a session. Use when asked to wrap up or end it; for forgotten-work or docs/skills/tooling reviews only when explicitly framed as ending the session. Not for ordinary commit requests, audits, or mid-session process reviews.
---

# Session closeout

Close out the session using its complete record, not just the latest turn.

## 1. Establish authority and scope

Read the original request, major course corrections, decisions, completed work, validation, and unresolved findings. Inspect current repository state and separate owned changes from pre-existing or unrelated work.

An explicit request to wrap up or end the session authorizes—and requires—you to commit all session-owned changes in coherent commits.
If the harness supports current-session titles, the request also authorizes changing the title.
It does not authorize optional repairs, issue filing, external publication, or committing unrelated work; obtain separate authority for those actions.

A request such as “anything we forgot?” or “do you suggest changes to docs/skills/tooling?” initiates closeout only when it is explicitly framed as ending the session. Otherwise treat it as a non-mutating review and do not load this skill. Use `commit-quality`, not this skill, for an ordinary “commit your changes” request.

## 2. Audit the whole session

Reuse an existing completion audit if its requirements, implementation, and validation conditions are unchanged.
If corrections followed the audit, check only the affected requirements and checks; do not restart the full audit.

For work not covered by an existing audit, use [completion review](../review/references/completion.md) for substantial completed implementation or refactoring across components, a specification, migration, or consequential boundary, or for an explicitly requested completion audit. Otherwise, for routine localized edits or simple configuration changes, inspect the diff and run the appropriate native check without loading it. Build a compact ledger covering:

- each explicit requirement and later correction;
- the final implementation or document state;
- tests, parsers, linters, generated outputs, or other evidence actually run;
- decisions intentionally deferred or rejected;
- temporary files, probes, debug code, stale names, and documentation left behind;
- uncommitted owned work, unrelated dirty work, and commits already created.

Search earlier turns when the current context does not establish the opening request or a decision's outcome. Do not call work complete when a requirement lacks evidence; name the missing check or remaining task.
You can identify the current session with `PI_SESSION_ID` (for the Pi harness) or `CODEX_THREAD_ID` (for Codex).

### Use edit-candidate lookup when available

When `read_session` supports `view: "edit_candidates"`, use that view with the session ID or file to find earlier paths for inspection.
Continue with `after: nextCursor` in the same view when more candidates are needed.
If codemode is available, filter or group the candidate objects there rather than parsing transcript prose.
Inspect a relevant candidate by passing its `source` into an ordinary `read_session` call.
Direct calls, persisted nested calls, and checkpoint paths can include failed attempts, copied records, and already-committed work.
Establish ownership and outcomes from source inspection, repository evidence, and existing validation, not the candidate list.
Keep `incomplete` and skipped records explicit; a false flag does not certify an exhaustive inventory.
This lookup supplements the requirements and decisions audit above; it does not replace it.
If the view is unavailable or the source is unsupported, use ordinary session reads and report any remaining evidence gaps.

## 3. Resolve closeout findings

Fix in-scope omissions only when repair is separately authorized, then rerun the cheapest checks that establish the repaired requirement. Leave protected or unrelated work untouched.

For remaining work, distinguish:

- **Required now:** blocks completion or contradicts the request.
- **Recommended follow-up:** worthwhile but outside current authority or scope.
- **Rejected:** considered and deliberately not recommended.

Recommend only concrete work supported by the session.
Prioritize wrong behavior, lost work, misleading validation, repeated operator error, and avoidable process cost over cosmetic polish.
Do not manufacture suggestions to fill a list.

## 4. Review the usefulness of docs, skills, and tooling

Review materials used during the session and concrete missed or mistimed routes,
not the entire documentation tree or skill catalog.
Evaluate the process against the task, not just whether the process was followed.
Assess:

- **Selection:** Did skills trigger when the task warranted them, too early, or
  not at all? Did documentation routes lead to the relevant owner and sections?
- **Effect:** Which advice changed a decision, implementation, or verification?
  Which guidance was redundant or gave no useful direction once loaded?
- **Reading cost:** What extraneous content, duplicated policy, broad triggers,
  or required full-document reads had to be sorted through? Would a narrower
  trigger, focused section, or separate reference preserve the useful advice?
- **Correctness:** Did instructions, examples, and commands work? Identify
  missing ownership, hidden failure causes, misleading diagnostics, drift from
  implementation, validation gaps, repeated manual work, and user corrections.

For material process cost, compare a costly or repeated step with a smaller approach that preserves the user's requirements.
State what useful decision or protection would be lost if the step were omitted, delayed, narrowed, or replaced with existing evidence.
Being required does not establish that a step was worth its cost.
Recommend changes for future work; do not use this assessment to bypass current requirements.
A passing check can still protect against a plausible failure; finding no failure does not make the check useless.

Support conclusions with concrete actions, errors, or corrections from the session.
Loading or following a skill does not establish that it helped; distinguish observed benefit or cost from uncertain attribution.
Briefly report material benefits and costs, even when no change is warranted, rather than listing every file read.
Record knowledge that another agent would otherwise have to reconstruct.
Maintained documents must stand on their own without referring readers to session-local `target/`, `/tmp`, or other disposable artifacts.
Put important findings, rationale, prerequisites, and enough reproduction detail in the owning documentation or specification.
Raw probe evidence need not be retained.

For a material finding about a shared component, check known consumers outside
the current repository. Report applicable unresolved follow-ups with the owning
project, evidence reference, and affected version or configuration. Keep the
explanation with its canonical owner; use pointers rather than duplicate accounts.
These follow-ups do not authorize edits elsewhere or block completion of the
original scope.

Use that assessment to decide whether process improvements are warranted.

For each suggestion, name the affected owner and the failure it would prevent.
Prefer a canonical documentation owner, a reusable skill only for recurring workflows or hard constraints, and tooling when mechanical enforcement or diagnostics are possible.
Route documentation-specific authoring to `technical-docs`, whole-artifact explanation and reader experience to `holistic-writing`, skill behavior to `skill-authoring`, and cleanup to `cleanup-triage` or another owning skill rather than duplicating its procedure here.

If the session contains concrete friction, report at least one improvement; otherwise state why none was warranted.
Do not make up an improvement simply to satisfy this skill; "things are in good shape" is an acceptable answer.

## 5. Commit the session's changes

Inspect the complete owned diff. Use `commit-quality` for atomic commits, messages, and inseparable tests/docs. Use `jj-workflow` only when preparing the commit requires history, provenance, or ownership judgment; path-limited commits alone do not require it. Commit every session-owned change and leave unrelated work untouched.

Verify each commit's identity and message, then recheck status. Keep closeout incomplete while owned work remains; if committing is blocked, name the exact blocker. A commit does not replace the whole-session audit.

## 6. Title the session

When the harness supports current-session titles, leave the session with a concise title reflecting its durable purpose or result, including substantial secondary work when one title can do so cleanly. Prefer the final outcome over the opening wording or an abandoned approach; distinguish investigation, design, repair, and implementation accurately.

Use the harness's supported current-session title mechanism; do not edit session storage directly.

### Codex title changes

In Codex with `CODEX_THREAD_ID` set, use [codex-rename](../../libexec/agent-wrappers/codex-rename):

```sh
codex-rename 'Fix sandbox skill paths'
```

If the command is not on `PATH`, invoke the linked file from this checkout.
It starts a temporary `codex app-server` over stdio, calls `thread/name/set`, verifies the name through `thread/read`, and stops the child process.
A successful exit establishes the persisted title for later reads and resumes.
It does not establish that an already-running standalone TUI refreshed its cached title; report that limitation instead of claiming a visible live update.
It inherits `CODEX_HOME` (default `~/.codex`) and may need sandbox approval to write Codex state.
No running daemon is required.
If it fails, report whether the rename was sent and whether read-back verified it.
If no supported mechanism is available, skip title mutation without blocking closeout.

### Other supported title mechanisms

For other mechanisms, distinguish persisted state from live client refresh and verify only the guarantees that mechanism exposes.

## 7. Report and stop

Report only new information not already apparent from tool output or earlier messages:

- blockers or required work left unfinished;
- required or recommended follow-ups;
- material benefits and costs of the process, including steps to omit, narrow, or replace in future work, or why costly steps were justified;
- anything else that would be hard for another agent to recover without reading the session log.

Do not report commits or successful verification unless the user explicitly asks.
Report failed or unavailable verification only when it leaves unresolved work or
changes what the user can rely on.

Completion requires every explicit requirement to be implemented or clearly recorded as blocked/deferred, every owned session change to be committed and verified, and unrelated work to remain protected.
When title tooling is supported, the title must be persisted and verified; unavailable live-client refresh does not block closeout when it is reported accurately.
A commit blocker leaves closeout incomplete.
