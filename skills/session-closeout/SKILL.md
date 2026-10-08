---
name: session-closeout
description: Close out a session. Use when asked to wrap up or end it; for forgotten-work or docs/skills/tooling reviews only when explicitly framed as ending the session. Not for ordinary commit requests, audits, or mid-session process reviews.
---

# Session closeout

Close the session from the complete record, not merely the latest turn.

## 1. Establish authority and scope

Read the original request, major course corrections, decisions, completed work, validation, and unresolved findings. Inspect current repository state and separate owned changes from pre-existing or unrelated work.

An explicit request to wrap up or end the session authorizes and requires committing all changes owned by the session, organized into coherent commits. When the harness supports current-session titles, it also authorizes changing the title. It does not authorize optional repairs, issue filing, external publication, or inclusion of unrelated work. Obtain separate authority before those actions.

A request such as “anything we forgot?” or “do you suggest changes to docs/skills/tooling?” initiates closeout only when it is explicitly framed as ending the session. Otherwise treat it as a non-mutating review and do not load this skill. Use `commit-quality`, not this skill, for an ordinary “commit your changes” request.

## 2. Audit the whole session

Reuse an existing completion audit when its requirements, implementation, and validation conditions remain unchanged. If corrections followed the audit, check only the affected requirements and checks; do not restart the full audit.

For work not covered by an existing audit, use `double-check` for substantial completed implementation or refactoring across components, a specification, migration, or consequential boundary, or for an explicitly requested completion audit. Otherwise, for routine localized edits or simple configuration changes, inspect the diff and run the appropriate native check without loading it. Build a compact ledger covering:

- each explicit requirement and later correction;
- the final implementation or document state;
- tests, parsers, linters, generated outputs, or other evidence actually run;
- decisions intentionally deferred or rejected;
- temporary files, probes, debug code, stale names, and documentation left behind;
- uncommitted owned work, unrelated dirty work, and commits already created.

Search earlier turns when the current context does not establish the opening request or a decision's outcome. Do not call work complete when a requirement lacks evidence; name the missing check or remaining task.

## 3. Resolve closeout findings

Fix in-scope omissions only when repair is separately authorized, then rerun the cheapest checks that establish the repaired requirement. Leave protected or unrelated work untouched.

For remaining work, distinguish:

- **Required now:** blocks completion or contradicts the request.
- **Recommended follow-up:** worthwhile but outside current authority or scope.
- **Rejected:** considered and deliberately not recommended.

Recommend only concrete work supported by the session. Prioritize defects that can cause wrong behavior, lost work, misleading validation, or repeated operator error over polish. Do not manufacture suggestions to fill a list.

## 4. Review the usefulness of docs, skills, and tooling

Review materials used during the session and concrete missed or mistimed routes,
not the entire documentation tree or skill catalog. Assess:

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

Support conclusions with concrete actions, errors, or corrections from the
session. Loading a skill does not establish that it helped; distinguish observed
benefit or cost from uncertain attribution. Briefly report material benefits and
costs, even when no change is warranted, rather than listing every file read.
Record knowledge that another agent would otherwise have to reconstruct.

For a material finding about a shared component, check known consumers outside
the current repository. Report applicable unresolved follow-ups with the owning
project, evidence reference, and affected version or configuration. Keep the
explanation with its canonical owner; use pointers rather than duplicate accounts.
These follow-ups do not authorize edits elsewhere or block completion of the
original scope.

Use that assessment to decide whether process improvements are warranted.

For each suggestion, name the affected owner and the failure it would prevent. Prefer a canonical documentation owner, a reusable skill only for recurring workflows or hard constraints, and tooling when mechanical enforcement or diagnostics are possible. Route implementation to `technical-docs`, `skill-authoring`, `cleanup-triage`, or another owning skill rather than duplicating its procedure here.

If the session contains concrete friction, report at least one improvement; otherwise state why none was warranted.
Do not make up an improvement simply to satisfy this skill; "things are in good shape" is an acceptable answer.

## 5. Commit the session's changes

Inspect the complete owned diff. Use `commit-quality` for atomic commits, messages, and inseparable tests/docs. Use `jj-workflow` only when preparing the commit requires history, provenance, or ownership judgment; path-limited commits alone do not require it. Commit every session-owned change and leave unrelated work untouched.

Verify each commit's identity and message, then recheck status. Keep closeout incomplete while owned work remains; if committing is blocked, name the exact blocker. A commit does not replace the whole-session audit.

## 6. Title the session

When the harness supports current-session titles, leave the session with a concise title reflecting its durable purpose or result, including substantial secondary work when one title can do so cleanly. Prefer the final outcome over the opening wording or an abandoned approach; distinguish investigation, design, repair, and implementation accurately.

Use the harness's supported current-session title mechanism; do not edit session storage directly. In Codex with `CODEX_THREAD_ID` set, use [codex-rename](../../libexec/agent-wrappers/codex-rename):

```sh
codex-rename 'Fix sandbox skill paths'
```

If the command is not on `PATH`, invoke the linked file from this checkout. It starts a temporary `codex app-server` over stdio, calls `thread/name/set`, verifies the name through `thread/read`, and stops the child process. A successful exit establishes the applied title. It inherits `CODEX_HOME` (default `~/.codex`) and may need sandbox approval to write Codex state. No running daemon is required. If it fails, report whether the rename was sent and whether read-back verified it. If no supported mechanism is available, skip title mutation without blocking closeout. For other mechanisms, verify the applied title when the harness exposes an independent read path.

## 7. Report and stop

Report:

- completion or blockers;
- verification evidence and its limits;
- commits created or owned changes left uncommitted;
- required or recommended follow-ups;
- material benefits and costs of the docs and skills used, with process improvements or the reason none is necessary;
- anything else that would be hard for another agent to recover without reading the session log.

Completion requires every explicit requirement to be implemented or clearly recorded as blocked/deferred, every owned session change to be committed and verified, and unrelated work to remain protected. When title tooling is supported, the title must also be applied. A commit blocker leaves closeout incomplete.
