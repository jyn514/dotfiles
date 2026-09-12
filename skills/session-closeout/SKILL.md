---
name: session-closeout
description: Finish a work session by auditing the whole session, resolving or recording loose ends, reviewing docs/skills/tooling lessons, committing the session's owned changes, and setting an accurate title when the harness supports it. Use when asked to wrap up or end the session. Use for forgotten-work or docs/skills/tooling reviews only when they are explicitly framed as ending the session. Do not use for an ordinary commit request, audit, or mid-session process review.
---

# Session closeout

Close the session from the complete record, not merely the latest turn.

## 1. Establish authority and scope

Read the original request, major course corrections, decisions, completed work, validation, and unresolved findings. Inspect current repository state and separate owned changes from pre-existing or unrelated work.

An explicit request to wrap up or end the session authorizes and requires committing all changes owned by the session, organized into coherent commits. When the harness supports current-session titles, it also authorizes changing the title. It does not authorize optional repairs, issue filing, external publication, or inclusion of unrelated work. Obtain separate authority before those actions.

A request such as “anything we forgot?” or “do you suggest changes to docs/skills/tooling?” initiates closeout only when it is explicitly framed as ending the session. Otherwise treat it as a non-mutating review and do not load this skill. Use `commit-quality`, not this skill, for an ordinary “commit your changes” request.

## 2. Audit the whole session

Use the `double-check` skill for completed implementation or refactoring. Build a compact ledger covering:

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

## 4. Review docs, skills, and tooling lessons

Review whether process improvements are warranted.
Use evidence from the session: observed friction, repeated manual work, hidden failure causes, misleading diagnostics, duplicated policy, missing ownership, or validation gaps in this session.

For each suggestion, name the affected owner and the failure it would prevent. Prefer a canonical documentation owner, a reusable skill only for recurring workflows or hard constraints, and tooling when mechanical enforcement or diagnostics are possible. Route implementation to `technical-docs`, `skill-authoring`, `cleanup-triage`, or another owning skill rather than duplicating its procedure here.

Do not make up an improvement simply to satisfy this skill; "things are in good shape" is an acceptable answer.

## 5. Commit the session's changes

Before committing, use `commit-quality`. Inspect the complete owned diff and repository status. Commit all session-owned changes using explicit paths and coherent atomic boundaries, including tests and documentation inseparable from each behavior; preserve unrelated working-copy changes.

After each commit, verify the resulting commit identity and message, then inspect repository status again. Do not complete closeout while an owned change remains uncommitted unless committing is blocked; name the exact blocker and leave the closeout incomplete. A successful commit does not replace the whole-session audit.

## 6. Title the session

When the harness supports current-session titles, leave the session with a concise title reflecting its durable purpose or result, including substantial secondary work when one title can do so cleanly. Prefer the final outcome over the opening wording or an abandoned approach; distinguish investigation, design, repair, and implementation accurately.

Use only the harness's supported current-session title mechanism. If none is exposed or it cannot operate on an active session, skip title mutation without blocking closeout; do not edit session storage directly. Verify the applied title when the harness exposes an independent read path.

## 7. Report and stop

Report only:

- completion or blockers;
- verification evidence and its limits;
- commits created or owned changes left uncommitted;
- required or recommended follow-ups;
- the applied session title, when supported.

Completion requires every explicit requirement to be implemented or clearly recorded as blocked/deferred, every owned session change to be committed and verified, and unrelated work to remain protected. When title tooling is supported, the title must also be applied. A commit blocker leaves closeout incomplete.
