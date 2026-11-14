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

## Maintain the current record

Before a maintenance write, ask what changes for someone reading the ticket now:

- **Update the description and applicable native fields** when current scope, disposition, remaining work, or the permitted next action changes.
  Replace superseded operative instructions rather than prepending another full snapshot.
  The description alone should make the current disposition and remaining action intelligible, with direct links to evidence and its owner where needed.
- **Comment** when new evidence or rationale explains a transition or a meaningful step without changing those operative facts.
  If it changes those operative facts, update the description and applicable native fields too.
- **Link** to the canonical owner for child-owned acceptance, evidence, or shared accounting instead of copying its narrative into parents and children.
  Keep the parent’s own outcome and remaining action intelligible locally.
- **Make no additional record** when existing records already convey the relevant facts and no useful new evidence or transition needs recording.
  Routine progress or test receipts do not require a substantial description rewrite.

When replacing an instruction, preserve consequential rationale and provenance in existing history or a suitable record if they would otherwise be lost.
Do not create an archive snapshot for every edit.
An investigation can finish while the product work it informs remains unresolved; record each disposition at its own owner.
A tracker state records work's status, not permission to execute it.
Follow the existing acceptance and evidence requirements before claiming completion; neither an investigation result nor a state change automatically closes product work.

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

Use supported fields and tags when they help select work, identify responsibility or explain a waiting condition.
Ordinary executive coordination is a valid reason to maintain them within existing mutation authority; jyn need not request each update.
Follow project conventions and do not populate unrelated fields merely because they exist.
Priority, tags, estimates and milestones are independent operations, not required setup steps:

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
Resolve tickets only when their acceptance and evidence requirements are met, including implementation and verification where applicable.
