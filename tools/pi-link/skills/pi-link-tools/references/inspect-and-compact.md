# Inspect or compact a root

Read before listing terminals to identify a target, interpreting status or context usage, or requesting remote compaction.
Apply the [common authority and group rules](../SKILL.md) first.

## Identify the target

`link_list` returns connected terminals in your group, with roles, full Pi session IDs, status, cwd, and available context usage.
`details.sessionIds` maps names to reported IDs; a missing ID is unknown.
Match a known parent session ID, not names or cwd, when identifying a parent terminal.

## Interpret its status

Your own entry is marked `(you)` and cannot be a direct-send or compaction target.
Your status is read at listing time; peer values are their latest snapshots, not reservations.
Missing status is unknown, not idle; `?` context is unknown, including briefly after compaction.
`tool:<name>` identifies one active tool call.
`thinking` includes unsettled retries, automatic compaction, and queued continuations.
`compacting` means manual compaction holds inbox delivery; automatic compaction instead remains `thinking`.
Join/leave UI notices do not enter model context; use `link_list` only when current membership changes a decision.

## Request compaction

`link_compact({ to: "<terminal-name>", instructions?: "..." })` waits up to five minutes for a compaction result.
Only a Pi-idle target with no compaction hold accepts; busy targets decline without interruption or queued work.
Optional instructions guide the summary but do not guarantee what survives.
Compaction can lose unreported detail.
Timeout or caller cancellation stops your wait, not a compaction already dispatched to the target.

