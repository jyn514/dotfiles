---
description: Convert a plain task into a strict evidence-based pi-codex goal and create it
argument-hint: "<task>"
---

User task:
$@

Turn the user task into exactly one durable pi-codex-goal objective, then call the goal creation tool with that objective.

This prompt invocation is an explicit user request to set a new goal. When the goal creation tool exposes `replace_existing`, pass `replace_existing: true` so an existing active, paused, or budget-limited goal is replaced instead of requiring `/goal clear` first.

Do not set a token budget limit unless the user explicitly provides a budget/limit in the task. If no explicit budget is provided, omit the token budget field entirely. Follow the exposed creation tool's token-budget policy: when supported, explicit budgets must meet its configured minimum (500,000 tokens by default); when the field is absent, explicit budgets are disabled. If the supplied budget violates that policy, ask for a valid budget or no limit instead of raising it or silently dropping it.

The goal must be a completion contract, not a task summary. Preserve the user's full intent, including broad acceptance criteria such as "all", "complete", or "no tech debt" when requested. Do not add requirements or narrow scope without user approval.

Include:

1. Outcome: what must be true when complete, preserving the full requested end state.
2. Verification evidence: the concrete checks or artifacts needed to demonstrate that outcome. Require the repository's existing validation command when relevant.
3. Task-specific constraints: preserve the user's permissions, protected behavior and files, acceptance boundaries, and any explicit stopping or review points. Preserve existing behavior unless the task changes it, and do not discard user changes.
4. Completion condition: every explicit requirement must have concrete verification evidence and no required work may remain.

Keep standing workflow instructions out of the saved objective. For a tracked goal requesting implementation through verified completion, read the `autonomous-implementation` skill file at its advertised path, if available, before starting work. Do not activate that skill for plan-only, review, research, or writing goals. The skill owns work selection, iteration, recovery, and completion-review procedure; the goal tools own status changes.

If missing user input or external work prevents meaningful progress, call `update_goal` with status `blocked` and a dependency reason, then explain what is needed. Do not block while useful work remains. Only explicit `/goal resume` reactivates a blocked goal; ordinary input does not. Never complete a blocked goal.

Use concise imperative language in the goal. If the task is blank or only whitespace, infer the goal based on the conversation context or ask the user to clarify.
