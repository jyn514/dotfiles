# Durable records

Use the project's issue tracker for unresolved work, maintained documentation for settled guidance, and the project's designated scratch area for temporary work.
Do not use `notes/` as a durable record or handoff.

## Choose what to retain

Record a finding only when it changes a future decision, prevents repeated investigation, or preserves otherwise-lost rationale.
Check existing tickets and maintained documentation before creating another record.
Update the existing owner rather than duplicate it.
Do not retain routine session recaps, completed-work lists, test-count receipts, or speculative improvements without a concrete consumer.

Unresolved work includes bugs, decisions, investigations, validation gaps, and missing documentation.
“This needs to be documented” is a valid ticket; it does not require writing documentation now.
Name the missing reader task or guidance and preserve the facts and rationale its author will need.
Put settled guidance in its maintained documentation when that documentation work is authorized.

## Separate session state from durable evidence

Keep live coordination, temporary command attempts and execution state in the session or scratch area.
Do not copy a session log into a ticket merely to keep it out of documentation.
Retain only the observations, reproduction details and rationale a future decision or investigation needs.
When an authorization trail is necessary, preserve that evidence in the existing issue rather than narrating approval exchanges in a policy page.
Use [documentation placement](documentation-placement.md#keep-session-state-out-of-maintained-documentation) for the boundary between settled guidance and session material.

## Preserve evidence in the ticket

Include the affected owner, decisive observations, known revision or input identity, remaining uncertainty, and enough reproduction detail to investigate again.
Distinguish observations, inference, proposed choices, and decisions actually made.
The ticket must remain useful if temporary logs and artifacts disappear; those artifacts may supplement it, but must not hold its only evidence.
Do not invent precision when the source or version is unknown.

Use the project's tracker procedure for creating, updating, and verifying tickets.
For a project using TicGit, follow the `ticgit` skill.
Filing a ticket records work; it does not authorize implementation, external publication, or changes to another workspace.
If durable recording is blocked, report the exact blocker and the facts still needing a ticket rather than substitute an untracked note or claim a handoff is complete.

## Resolve the record

Record the accepted outcome or rejection in the ticket when the work is resolved.
Keep reusable settled guidance with its maintained documentation, not a parallel notes collection.
Delete a legacy note only after verifying that its useful content is preserved by a ticket or maintained owner, or establishing that it no longer needs retention.
