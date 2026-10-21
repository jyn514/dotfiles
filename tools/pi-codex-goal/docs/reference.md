# Goal reference

[Back to the README](../README.md)

## Installation options

Requires Pi 1.0.0 or later (official releases and the [fitchmultz Pi fork](https://github.com/fitchmultz/pi)) and Node.js 24 or later.

```sh
# Latest npm release
pi install npm:pi-codex-goal

# Current GitHub default branch
pi install https://github.com/fitchmultz/pi-codex-goal
```

The GitHub default branch can include unreleased changes even when `package.json` still identifies the latest published version.

npm, Git, and local directory installs all load the TypeScript source (`extensions/index.ts` and `src/`) through Pi's extension loader. There is no build step or production TypeScript dependency. See [development setup](development.md#local-setup) for local checkouts and duplicate-install precautions.

## User commands

The [README command table](../README.md#goal-controls) covers the usual controls.

`/create-goal <task>` expands the task into an objective with an outcome, verification evidence, task-specific constraints, and a completion condition.
Drafting must not add requirements or narrow the requested scope.
Standing workflow instructions stay out of the saved objective.
It asks the model to call `create_goal` with explicit replacement enabled, so you do not need to run `/goal clear` before setting a new goal.

The template follows the goal-writing practices in OpenAI's [Codex follow-goals guide](https://developers.openai.com/codex/use-cases/follow-goals) and [Using goals in Codex cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex).

`/goal` with no arguments reports the current objective, status, token budget, token usage, and elapsed active time. A plain `/goal <objective>` starts a new unlimited goal or replaces the current one after confirmation. `/goal copy` copies the objective for active, paused, blocked, budget-limited, and completed goals.

`/goal edit` opens a multiline editor prefilled with the current objective in interactive and supported RPC clients.
Saving changes only the objective and its update timestamp; it preserves the goal ID, usage, budget, status, and any blocked or paused reason.
The revised objective reaches subsequent model turns without interrupting a running turn or starting or resuming work.
Completed goals remain completed.
Canceling or saving unchanged text leaves the goal untouched; saving after the goal was cleared or replaced discards the edit.
To start different work rather than refine the existing objective, use `/goal <objective>`.

Objectives are limited to 8000 Unicode characters. Token budgets are set through the model tool; `/goal --tokens` is not a budget option.

## Model tools

### `create_goal`

Starts a goal with an `objective` and an optional `token_budget`. It fails if a non-complete goal already exists unless `replace_existing: true` is provided. After a goal is complete, `create_goal` replaces it with a new active goal.

Omit `token_budget` for an unlimited goal. By default, new explicit budgets must be safe integers of at least 500,000 tokens, including replacements. Smaller budgets are rejected rather than raised automatically. Existing saved goals retain their original budgets and usage.

Set `PI_CODEX_GOAL_TOKEN_BUDGET_POLICY` before starting Pi to choose a different minimum or reject all explicit budgets:

```sh
PI_CODEX_GOAL_TOKEN_BUDGET_POLICY=100000000 pi
PI_CODEX_GOAL_TOKEN_BUDGET_POLICY=disabled pi
```

A positive safe integer sets the minimum, including values below the default. `disabled` permits only omitted budgets. The exposed tool schema and execution boundary enforce the same policy, including replacement calls. Invalid or empty settings fail extension loading. The setting is read at extension load; restart Pi or `/reload` after changing its environment. This policy does not change saved goals, and `/goal <objective>` still creates unlimited goals.

### `get_goal`

Returns the current goal state and usage.

### `update_goal`

Accepts `status: "complete"` after verified completion.
Use `status: "blocked"` with a non-empty `reason` only when missing input or external work prevents progress across the remaining goal.
The agent must not block while independent authorized work toward the objective remains.
Narrowing an investigation does not narrow the saved goal or its acceptance conditions.
The reason should explain what the dependency prevents and why no independent authorized work remains.
These are model instructions, not a mechanical proof that the goal is blocked; the tool still enforces only the existing status and non-empty-reason rules.

Blocking preserves the unfinished objective, reason, and usage through reload, fork, and compaction. It cancels automatic continuations and provider auto-resume, and does not interrupt an already-running tool. Use `/goal` to inspect the dependency and explicit `/goal resume` to reactivate the goal. Ordinary input or reopening the session cannot resume it, and completion is rejected while blocked. Reaching the token budget still stops the goal rather than allowing blocking to bypass the limit.

Use `status: "paused"` with a non-empty `reason` only to annotate an already-paused goal.
This does not pause an active goal or resume work; it preserves saved usage, and repeating the same trimmed reason adds no entry.
`/goal` and tool output show the reason; objective edits and reload preserve it, while resume and completion clear it.
An agent cannot change a paused goal to blocked.

Calling `update_goal` on an already-complete goal is idempotent and does not append duplicate session entries. The extension accounts the assistant response calling either status change before persisting it; completion reports final token and elapsed-time usage.

Completed goals are terminal for automatic transitions: pause, resume, and hidden continuations do not reopen them. To recover from premature completion, use `/goal <objective>` to replace the goal, call `create_goal` with `replace_existing: true`, or `/goal clear` before starting again.

### MCP tool names

In bridged MCP environments, Pi may expose these tools under namespaced names such as `pi__get_goal`, `pi__create_goal`, and `pi__update_goal`.
Prompt guidance explains naming once per prompt: call the exposed tool name, not display or transcript labels.
Standing instructions, full continuation prompts, and automatic continuations share the evidence-backed completion and whole-goal blocking guidance.
Every new continuation includes the full current objective as untrusted task data, including compact continuations after resume or compaction.
Edits update objective blocks in extension-owned pending continuations at the provider boundary.
The rewrite preserves recorded usage and user-authored messages.
Legacy continuations without objective blocks remain readable; saved session entries are not migrated or rewritten.

## Behavior

While a goal is active, the extension:

- Tracks elapsed active time between turns and tool completions.
- Adds completed assistant turn input plus output token usage when the active model reports it.
- Coalesces runtime goal custom-entry writes so unchanged status and usage are not appended on every tool completion. Live footer usage stays current, and meaningful usage is flushed at turn boundaries, shutdown, compaction, budget crossings, and bounded intervals during long tool-heavy runs.
- Leaves threshold and overflow compaction decisions to Pi. The user's effective compaction settings remain authoritative while goal accounting and continuation follow host compaction events.
- Pauses when an active assistant turn is aborted, such as when you press Esc.
- Recovers from provider assistant errors without immediate hidden continuation loops. Context-window overflow triggers automatic compaction and then resumes the active goal; transient errors use bounded backoff retries; recognized provider usage-limit pauses schedule a conservative auto-resume retry. Use `/goal resume cancel` to stop the scheduled retry.
- Prompts on session resume before reactivating a paused goal when a UI is available, and supports explicit `/goal resume`.
- Pauses a hidden continuation that only inspects goal status with `get_goal` without doing actionable work.
- Rejects `/goal pause` unless the goal is active and rejects `/goal resume` unless the goal is paused or blocked.
  After host overflow recovery, an active goal can receive another continuation without changing status.
- Sends all goal start and continuation prompts as hidden custom messages, including manual, session, and provider-limit resumes.
  These do not reset Pi's exhausted overflow recovery allowance.
  If `/goal resume` encounters another overflow after a failed compact-and-retry attempt, send a normal user message to reset that allowance, reduce context, or switch to a larger-context model.
- Treats completed goals as terminal for automatic transitions while allowing `/goal <objective>` and explicit `create_goal` replacement to replace goals.
- Marks the goal `budgetLimited` when a positive token budget is reached.
- Sends hidden steering messages when budget is reached or when the agent is idle but the goal is still active.
- Routes every active goal to the optional `autonomous-work` skill at start or resume and back to its recovery guidance when stuck.
  This covers implementation, research, writing, planning, and review; standing tool guidance covers model-created goals too.
  The separately installed skill owns work selection, prerequisite recovery, scouting, iteration, and activity-specific verification.
  The extension retains objective, completion-evidence, blocking, resume, and budget contracts independently of the skill.
  Autonomy does not expand the task's authorized activity or effects.
  Research and review do not authorize fixes, plans do not authorize execution, and drafts do not authorize publication.
  The extension uses the advertised skill path, does not bundle the skill, and does not treat its absence as a blocker.
  These are model instructions, not a guarantee of compliance or better prioritization.
- Compacts repeated hidden goal continuations before provider context so only the latest active continuation stays runnable. Older ones become short bookkeeping markers, and auto-queued continuations use a compact prompt after `/goal` start or resume.
- Shows Codex-style status labels with compact token or elapsed-time usage in the Pi footer when a UI is available.

Token counts use commas and compact abbreviations, for example `123M (123,456,789) tokens`. Goal totals count only completed assistant-turn `input` plus `output` while the goal is active. Cache read/write channels are excluded because they are provider cache accounting fields rather than extra sent and received text tokens. Pi 0.81+ also folds tool, compaction, and branch-summary usage into host session totals/footer stats. Those host maintenance and nested-tool costs stay out of goal budgets, so goal tokens measure assistant turn work toward the objective rather than whole-session spend.

## Durable recovery and accounting

Native custom entries remain the source of truth across resume, tree/fork, reload, and compaction. Existing goal formats and historical saved budgets are retained without migration or journal rewriting. Paused headless goals require explicit `/goal resume`; blocked goals remain blocked until explicitly resumed. Shutdown persists pending recovery before disposal. Neither supported 1.0 target provides the old fork checkpoint/accounting APIs; legacy session goal entries still recover normally.

Turn accounting consumes the current native response once, including a status-changing tool's calling response. Native `ctx.executeTool()` child calls are correlated to their calling response, and repeated tool-call IDs are correlated to the latest response rather than older entries. Multiple children do not charge that response again; the completion receipt is not goal work. Accounting uses persisted `turn_end` messages rather than reading the not-yet-appended `message_end`, and does not assume boundary drafts are committed inside handlers.

## Compatibility contract

The extension uses the shared public Pi 1.0 extension API. Pi-bundled runtime packages remain optional wildcard peers supplied by the host. Locked development dependencies are reproducible snapshots rather than validation targets. Qualification selects the latest stable official Pi cohort and the latest maintained fork's actual graph, including host-supplied TypeBox; a development update does not change the host's bundled dependencies.

Per-loop `agent_end` drives guarded goal continuation; it is not final completion. Native `waitForIdle`/`agent_settled` includes queued goal work, tool receipts, and host compaction/retry. No checkpoint, `recordUsage`, metadata/revision, or extra fork RPC/TUI API is required. Each run qualifies the maintained fork's exact current revision; historical coverage does not certify a new host.
