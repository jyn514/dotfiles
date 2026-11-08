# Versioned writeups

Read when inspecting or changing versioned drafts, linking them, or promoting a draft into a ticket.
Begin with the [common identity, authorization, and proxy rules](../SKILL.md).
For an authorized mutation using file input, also read [file-input mechanics](ticket-changes.md#file-input).

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

