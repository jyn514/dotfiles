---
name: ticgit
description: How to use TicGit (`ti`) to track Git-native tickets in a local repository. Use when you need to interface with the tracker and the repository documents TicGit or an active workflow explicitly selects it as the fallback.
---

# TicGit Agent Guide

Use `ti` for planning, progress notes, triage, and resolving work.
Prefer `--markdown` when the command supports it.
Use explicit ticket IDs and branch/review references; do not rely on current-ticket or current-branch defaults.
Native Markdown can suggest commands unavailable through the proxy; follow the supported workflows below instead.

## Basic Workflow

Find and inspect work:

```sh
ti list --markdown
ti next --markdown
ti show <id> --markdown
```

Treat `next` as a recommendation, not a persistent selection.
Pass the ticket ID on every later operation, including work delegated to subagents.

Claim a ticket only when it should be assigned to the configured author:

```sh
ti claim -t <id>
```

The proxy uses one authorship identity for the store, not a separate identity for each agent or subagent.
Assignment identifies a person or stable role; an explicit ticket ID identifies a subagent's task.
Filter assignments explicitly with `ti list --assigned <email>`.

## Create And Edit Tickets

Create a ticket from a UTF-8 file whose first line is the title and remaining lines are the description:

```sh
ti new -F /tmp/ticket.md --tags bug,parser --markdown
```

Edit the title and description with the same file format:

```sh
ti edit <id> -F /tmp/ticket.md
```

Supply files or explicit text instead of requesting an interactive editor.
Through the proxy, `-F -` transports bounded standard input; native TicGit does not itself implement file-stdin input.

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

Use priority, tags, estimates, and milestones to keep work easy to sort:

```sh
ti priority -t <id> 2
ti tag -t <id> bug parser
ti points -t <id> 3
ti milestone -t <id> v1.0
```

Use `spec` for implementation notes before coding:

```sh
ti spec -t <id> -F /tmp/spec.md
ti show <id> --filter .spec
```

## Dependencies

Track ordering constraints explicitly:

```sh
ti dep <blocker-id> -t <id>
ti dep <blocker-id> -t <id> --remove
```

`ti next` skips tickets with unresolved dependencies.

## Saved Views

Use this proxy-only syntax only when `ti views save --help` advertises explicit list arguments:

```sh
ti views save bugs --tag bug
ti list bugs --markdown
```

The proxy runs listing and saving as one serial request using only the supplied filters.
With no filters, it saves the default list filters, not an earlier request's filters.
Plain native TicGit does not accept the extended arguments; do not substitute a list-then-save workflow when agents share state.

## Writeups

Capture rough notes before promoting them into tickets:

```sh
ti writeup new --title "Parser cleanup" -F /tmp/writeup-body.md
ti writeup list
ti writeup show <writeup-id>
ti writeup edit <writeup-id> --body "Another observation"
ti writeup link <writeup-id> <ticket-id>
ti tag --writeup <writeup-id> cleanup
ti writeup promote <writeup-id>
```

For `writeup new`, the file contains only the body; supply the title separately.
For `writeup edit -F`, the first line is the updated title and remaining lines form a new body version.
Promotion creates a ticket and closes the writeup; use the returned ticket ID for later work.

## Code Reviews

Create and inspect review metadata using explicit branch and base refs:

```sh
ti review new --branch <branch-name> --base <base-ref> --ticket <id>
ti review show <branch-name> --markdown
```

Refresh the review after adding commits:

```sh
ti review update <branch-name>
```

The proxy sees the common-directory Git HEAD, not the caller's worktree branch.
The pinned native `review new` can fail on a detached common-directory HEAD even with `--branch`; report that failure rather than changing HEAD.
Review integration commands record metadata; they do not merge code.

## Boundaries And Failures

Leave store initialization, sync/import, user-map administration, and tool/schema upgrades to coordinated host administration.
Do not use `checkout`, `users`, `mine`, interactive UI/editor, or self-update commands.
Only the explicit view-save form is admitted from the views command family.

A failed or disconnected mutation may already have changed metadata.
Inspect the affected ticket, writeup, or review before deciding whether to retry; never retry automatically or bypass a failed proxy.

## Agent Practices

- Use ticket IDs or unique prefixes and explicit branch/review references.
- Check for a spec before implementing; add one if the path is unclear.
- Comment when you learn something important or finish a meaningful step.
- Open or update reviews when branch commits change.
- Mark blockers with an explicit state update and dependencies with `ti dep`.
- Resolve tickets only after implementation and verification are complete.
