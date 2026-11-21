---
name: ticgit
description: How to use TicGit (`ti`) to track Git-native tickets in a local repository. Use when you need to interface with the tracker and the repository documents TicGit or an active workflow explicitly selects it as the fallback.
---

# TicGit Agent Guide

Use `ti` for planning, progress notes, triage, and resolving work.
Use plain `ti list` for compact tables and `ti show <id> --filter <path>` for selected fields.
Use `--json` for programmatic queries and `--markdown` when the full ticket history is needed.
Use explicit ticket and writeup IDs; do not rely on current-ticket defaults.
Native Markdown can suggest commands unavailable through the proxy; follow the supported workflows below instead.

Select the fields needed for the question before displaying JSON results.
For finding affected tickets, start with IDs, titles, and descriptions; omit comments.

```sh
ti list --search 'renderer' --json |
  jq 'map({id, title, description})'
```

This filters the displayed output; `--json` still retrieves complete records.

## Inspect a ticket

Start with the ticket's current description, not its full comment history.
Use the compact listing to locate tickets and check their current state:

```sh
ti list
ti show <id> --filter .description
```

Inspect `.spec` or relevant comments when requirements, authority or acceptance depend on them.
Read the governing requirements and relevant acceptance record before drawing conclusions about completion.
Tracker state alone does not prove that the required outcome is accepted.

Use the full view when investigating history, recovering a decision or checking whether later evidence supersedes the description:

```sh
ti show <id> --markdown
```

This view includes all comments; do not make it the default for a current-state check.
Stop after the requested inspection or summary when no tracker change is authorized.

## Select further operations

- When authorized to choose work, when inspecting graph dependencies or state, or when deciding whether an outcome is accepted, read [selection and graph inspection](references/selection-and-graphs.md).
- When ticket creation, editing, claiming, comments, state, planning fields, or dependency changes are authorized, read [ticket changes](references/ticket-changes.md) before mutation.
- When inspecting or changing a versioned draft, linking it, or promoting it into a ticket, read [writeups](references/writeups.md).
  Writeups and ticket specs are optional homes for requested work, not prerequisites for every ticket.

## Identity and authority

The proxy uses its accepted workspace authorship identity, not a separate identity for each agent or subagent.
Use explicit ticket/writeup IDs or unique prefixes on every operation, including delegated work.
Assignment and explicit IDs do not reserve work for an agent or authorize starting it.
Filter assignments explicitly with `ti list --assigned <email>`.
Inspection does not authorize tracker mutation; follow the task's permitted effects.

## Boundaries And Failures

Leave store initialization, sync/import, user-map administration, and tool/schema upgrades to coordinated host administration.
Do not use `checkout`, `users`, `mine`, interactive UI/editor, or self-update commands.
Saved views and reviews are deferred; do not use their command families through the proxy.
`ti list <view-name>` reaches native lookup but finds no saved views in request-private state.

A failed or disconnected mutation may already have changed metadata.
Inspect the affected ticket or writeup before deciding whether to retry; never retry automatically or bypass a failed proxy.

