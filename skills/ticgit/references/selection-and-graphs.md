# Work selection and issue graph inspection

Read when authorized to choose work or when interpreting dependencies, graph state, or acceptance records.
Begin with the [common inspection and safety rules](../SKILL.md).

## Choose work when authorized

Use `next` only when authorized to choose work, with filters appropriate to that scope.
For example:

```sh
ti next --assigned <email> --tag <tag> --markdown
```

Treat the result as a recommendation, not a persistent selection or reservation.
Inspect its assignment and blockers before starting; `next` can return blocked tickets and excludes child tickets.
It does not supersede an assigned task or coordinate ownership between agents.
Pass the ticket ID on every later operation, including work delegated to subagents.

## Inspect An Issue Graph

Inspect tracker state, dependencies, and acceptance records:

```sh
ti list --state in-progress --subissues
ti list --all --subissues --json
ti show <id> --filter .comments
```

Include `--subissues` when listing the whole graph; the default list omits child tickets.
Use JSON to join tickets with their dependency IDs and identify unfinished prerequisites.
A dependency-clear ticket is not necessarily authorized or ready to start; inspect its required inputs and governing workflow.
`next` can recommend an in-progress ticket, so it is not an unclaimed-work queue.

### Establish whether the outcome is accepted

Keep dependency closure, tracker state, current execution, and accepted outcomes distinct.
An in-progress state does not prove an agent is currently executing the task, and a closed dependency may be resolved, rejected, or a duplicate.
Read the canonical acceptance record before claiming the required outcome is met; `resolved` alone is not acceptance evidence.
For an overview, link to that record in its chosen home, such as ticket comments, a specification, or a linked artifact.

