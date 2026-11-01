<skill>
<name>orchestrator-worker</name>
<path>/workspace/flower/.agents/skills/orchestrator-worker/SKILL.md</path>
---
name: orchestrator-worker
description: Implement a Flower orchestrator worker task from an orchestrator packet. Use when Codex is given a Flower Orchestrator Worker Packet, task-local workspace, allowed ownership paths, covered git-bug issue ids, final report handling instructions, or is asked to run outside the orchestrator while following the same worker contract.
---

# Orchestrator Worker

Implement exactly the task described by the worker packet.

## Work Boundaries

- Treat the packet as the authority for task id, covered issue ids, allowed ownership paths, protected paths, and final report handling.
- Edit only files covered by the allowed ownership paths. If required work needs another path, stop and report `needs-scope`.
- Do not edit protected paths. Protected paths usually include `.git`, `.jj`, `.agent-git-bug`, and `target/flower-worker`.
- Do not write git-bug state.
- Do not rebase other work.
- Do not merge.
- Commit only to the task-local history when a commit is required.
- Do not revert unrelated changes. If existing changes affect the task, work with them or report the conflict.

## Procedure

1. Read the packet completely.
2. Inspect the named issues, allowed files, and adjacent tests before editing.
3. Make the smallest coherent implementation that satisfies the acceptance criteria.
4. Run focused tests when relevant.
5. Run `bb lint --changed` when practical before reporting completion.
6. Leave enough evidence in the report for the orchestrator to review the attempt without reading the whole workspace.

## Report

Return the final JSON report as your last message. In orchestrated runs, the orchestrator saves that final message to its report file.

Use `resources/flower/orchestrator/worker-report.schema.edn` as the report contract. Read it when the exact field set, allowed status values, or nullability matters.

</skill>