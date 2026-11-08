# Change tickets

Read when ticket creation, editing, claiming, comments, state, planning fields, or dependency changes are authorized.
Begin with the [common identity, authorization, and proxy rules](../SKILL.md).
Assignment is not mutation authority.

## Claim only when assignment is intended

Claim a ticket only when assigning it to the configured author and setting its status to open and state to assigned are both intended.
Claiming can reopen a closed ticket or replace an in-progress or blocked state; do not use it merely to announce that work starts.

```sh
ti claim -t <id>
```

The proxy uses its accepted workspace authorship identity, not a separate identity for each agent or subagent.
Assignment and explicit ticket IDs do not reserve work for an agent.
Filter assignments explicitly with `ti list --assigned <email>`.

## File input

For proxy calls, the guest client reads input files relative to its own cwd and sends their UTF-8 contents to the host as stdin.
Guest-only temporary files are supported; the host does not open the supplied guest pathname.
An input-loading failure does not fall back to a host-file read.
Supply files or explicit text instead of requesting an interactive editor.
`-F -` reads caller stdin; use `-F ./-` to name a literal file called `-`.

## Create And Edit Tickets

For new or substantially rewritten ticket titles and descriptions, use [holistic-writing](../../holistic-writing/SKILL.md) before submitting them.
Tracker mechanics do not replace editorial review.
State changes, tags, and routine progress comments do not require that pass.

Create a ticket from a UTF-8 file whose first line is the title and remaining lines are the description:

```sh
ti new -F ticket.md --tags bug,parser --markdown
```

Edit the title and description with the same file format:

```sh
ti edit <id> -F ticket.md
```

## Progress Notes

Add comments with an explicit target and body:

```sh
ti comment -t <id> -- "found the failing case"
ti comment -t <id> -- "implemented fix; running the tests"
```

## State And Triage

Tickets have a broad status and a specific state:

```text
open: new, assigned, in-progress, blocked, review
closed: resolved, wontfix, duplicate, invalid
```

Useful updates:

```sh
ti state blocked -t <id>
ti state review -t <id>
ti close <id>
```

`ti close` resolves the ticket and records the configured author as `closed_by`.

## Planning Fields

Set priority, tags, estimates, or milestones only when the task or project workflow calls for them.
These are independent operations, not required setup steps:

```sh
ti priority -t <id> 2
ti tag -t <id> bug parser
ti points -t <id> 3
ti milestone -t <id> v1.0
```

Read existing requirements before implementing and clarify missing decisions when needed.
Use the ticket's `spec` field when it is the chosen home for those requirements or implementation notes.
Do not create a spec for every change or duplicate a maintained repository specification:

```sh
ti spec -t <id> -F spec.md
ti show <id> --filter .spec
```

## Dependencies

Track ordering constraints explicitly:

```sh
ti dep <blocker-id> -t <id>
ti dep <blocker-id> -t <id> --remove
```

`ti next` skips tickets whose dependencies are not closed; it does not require those dependencies to be closed as resolved.

## Record progress and completion

Comment when you learn something important or finish a meaningful step.
Mark blockers with an explicit state update and dependencies with `ti dep`.
Resolve tickets only after implementation and verification are complete.
