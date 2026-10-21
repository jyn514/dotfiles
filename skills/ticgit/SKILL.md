---
name: ticgit
description: How to use TicGit (`ti`) to track Git-native tickets in a local repository. Use when you need to interface with the tracker and the repository documents TicGit or an active workflow explicitly selects it as the fallback.
---

# TicGit Agent Guide

Use `ti` for planning, progress notes, triage, and resolving work.
Prefer `--markdown` when the command supports it.
Use explicit ticket and writeup IDs; do not rely on current-ticket defaults.
Native Markdown can suggest commands unavailable through the proxy; follow the supported workflows below instead.

## Basic Workflow

Inspect the assigned ticket; use listing to locate tickets when needed:

```sh
ti list --markdown
ti show <id> --markdown
```

Use `next` only when authorized to choose work, with filters appropriate to that scope.
For example:

```sh
ti next --assigned <email> --tag <tag> --markdown
```

Treat the result as a recommendation, not a persistent selection or reservation.
Inspect its assignment and blockers before starting; `next` can return blocked tickets and excludes child tickets.
It does not supersede an assigned task or coordinate ownership between agents.
Pass the ticket ID on every later operation, including work delegated to subagents.

Claim a ticket only when assigning it to the configured author and setting its status to open and state to assigned are both intended.
Claiming can reopen a closed ticket or replace an in-progress or blocked state; do not use it merely to announce that work starts.

```sh
ti claim -t <id>
```

The proxy uses its accepted workspace authorship identity, not a separate identity for each agent or subagent.
Assignment and explicit ticket IDs do not reserve work for an agent.
Filter assignments explicitly with `ti list --assigned <email>`.

## Create And Edit Tickets

For proxy calls, save input files inside the shared checkout and use paths relative to the caller's cwd.
Guest-only temporary files are unavailable.
Create a ticket from a UTF-8 file whose first line is the title and remaining lines are the description:

```sh
ti new -F ticket.md --tags bug,parser --markdown
```

Edit the title and description with the same file format:

```sh
ti edit <id> -F ticket.md
```

Supply files or explicit text instead of requesting an interactive editor.
`-F -` names a literal file called `-`; it does not read stdin.

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

## Writeups

Use a writeup when the task calls for a versioned draft, not as a required step before creating tickets.
Create a ticket directly for actionable work; use ticket comments for incremental observations about existing work.

Create and inspect a draft:

```sh
ti writeup new --title "Parser cleanup" -F writeup-body.md
ti writeup list
ti writeup show <writeup-id>
```

For `writeup new`, the file contains only the body; supply the title separately.
To revise the draft:

```sh
ti writeup edit <writeup-id> -F revised-writeup.md
```

For `writeup edit -F`, the first line is the updated title and remaining lines supply a new body version when present.
Alternatively, `--body` supplies a complete new body version without changing the title.
Neither form appends observations to the previous body; default `show` and promotion use the latest version.
Use `ti writeup show <writeup-id> --all` to inspect earlier versions.

Linking to an existing ticket and promotion into a new ticket are different choices, not required sequential steps.
To link a draft to existing work:

```sh
ti writeup link <writeup-id> <ticket-id>
```

To create a new ticket from the draft:

```sh
ti writeup promote <writeup-id>
```

Promotion creates a ticket and closes the writeup; use the returned ticket ID for later work.

## Boundaries And Failures

Leave store initialization, sync/import, user-map administration, and tool/schema upgrades to coordinated host administration.
Do not use `checkout`, `users`, `mine`, interactive UI/editor, or self-update commands.
Saved views and reviews are deferred; do not use their command families through the proxy.
`ti list <view-name>` reaches native lookup but finds no saved views in request-private state.

A failed or disconnected mutation may already have changed metadata.
Inspect the affected ticket or writeup before deciding whether to retry; never retry automatically or bypass a failed proxy.

## Agent Practices

- Use explicit ticket/writeup IDs or unique prefixes.
- Read existing requirements and clarify missing decisions; add a ticket spec only when it is the appropriate owner.
- Comment when you learn something important or finish a meaningful step.
- Mark blockers with an explicit state update and dependencies with `ti dep`.
- Resolve tickets only after implementation and verification are complete.
