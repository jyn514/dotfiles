# pi-codex-subagents

Codex-shaped, session-scoped subagents for [Pi](https://github.com/earendil-works/pi). Spawn isolated child Pi processes, receive their final responses automatically, steer active work, and inspect sessions in a live overlay.

Ordinary subagent tools require Pi 0.80.4 or newer and Node.js 22.19 or newer.
[Durable pause](#durable-pause) additionally requires Pi's native handoff and fresh-input admission APIs in both parent and children.

## Install

```bash
pi install npm:@ogulcancelik/pi-codex-subagents
```

For local development:

```bash
pi install /absolute/path/to/pi-extensions/packages/pi-codex-subagents
```

## Tools

| Tool | Purpose |
|---|---|
| `spawn_agent` | Spawn a fresh-context child Pi process |
| `wait_agent` | Block for one completion and return its final text |
| `wait_all_agents` | Block until every selected agent finishes |
| `list_agents` | List current-session agents, or explicitly include historical sessions |
| `read_agent_response` | Read an agent's latest final raw text response |
| `send_message` | Steer a running agent or start another turn when settled |
| `interrupt_agent` | Abort the current turn while preserving its session for later messages |

Agent names are unique within their parent session. The same task name can exist safely in different Pi sessions. Read and control tools are always scoped to the current parent session; only `list_agents(include_all: true)` crosses session boundaries, and that view is read-only.

`spawn_agent.skills` adds model-invocable skills currently loaded in the parent by
name. The tool lists permitted names without repeating descriptions from Pi's
parent skill catalog. Disabled or unloaded skills are refused; refreshing the
parent's skill list updates the permitted names.

## Agent templates

Templates are user-defined Markdown files in:

```text
~/.pi/agent/pi-codex-subagents/agents/*.md
```

No templates are installed automatically. Example:

```md
---
name: reviewer
description: Focused read-only code review agent
provider: openai-codex
model: gpt-5.6-sol
thinking: high
tools: read,bash,grep,find,ls
skills: web-investigate
extensions: @scope/pi-extra-tools, ~/.pi/agent/extensions/local-helper.ts
disabledExtensions: pi-codex-subagents
hint: Give this reviewer exact file paths and a narrow scope.
---
You are a focused review subagent. Return concise findings with file paths.
```

`provider` and `model` are an optional pair.
When both are present, Pi launches that exact provider/model combination.
If either is absent, the child inherits the parent agent's provider and model.
`thinking` is also optional and otherwise inherits the parent.
Template `tools` select an explicit task-tool allowlist; omitting them uses Pi's normal activation, not the parent's active tool names.

`skills` may contain skill names or paths.
`extensions` may contain local files/directories or npm package names already installed by Pi.
These explicit package additions are resolved from project-local packages first and then Pi's global npm directory.
Pi's normal discovery handles packages configured in its own settings.

Children discover configured and local extensions, skills, and prompt templates through Pi's native resource discovery.
They run in the parent's `ctx.cwd` and retain its resolved project-trust decision for that directory, including after recreation.
Declining project trust prevents protected project resources from loading; user resources remain available.
If an older parent or saved worker supplies no trust decision, the child does not grant project trust.
Discovered extension tools are available even when they were not active in the parent.

`disabledExtensions` belongs only to agent-template frontmatter, not `config.json`, its `defaults`, or Pi's `settings.json`.
It accepts comma-separated canonical entrypoint file paths, package names (including an unscoped basename), or `builtin:name` selectors.
For example, `pi-codex-subagents` excludes this package's manager entrypoint without excluding sibling extensions in a monorepo.
Use it on templates that should not expose subagent management tools.
Exclusions apply to both discovered extensions and explicit `extensions` additions, before modules, factories, or hooks execute.
Package-name exclusions match the package's declared entrypoints, not every file in its directory.
The packaged child helper always loads independently, preserving pause support and `link_reply` even with an empty task-tool allowlist.
Exclusions persist with each worker; older worker records without exclusions have none.

The manager uses Pi's public package resolver to select enabled entrypoints before starting the child.
It transports those paths through `--no-extensions` plus explicit `--extension` arguments so unfiltered extension rediscovery cannot bypass exclusions.
Skills and prompt templates still use normal native discovery.
Pi's built-in extensions also load by default, subject to native settings and template exclusions such as `builtin:mcp`.
The manager keeps their names in one package-owned list; maintain that list when supported Pi CLI versions add or rename built-ins.
Older Pi versions without built-in extension resources keep their existing package discovery.

Context-file discovery remains disabled: children do not load `AGENTS.md` or `CLAUDE.md` files.
Each child replaces Pi's coding prompt with `~/.pi/agent/pi-codex-subagents/SYSTEM.md` and supplies an empty append prompt.
Pi's discovered `SYSTEM.md` and `APPEND_SYSTEM.md` files do not replace or append to it.
The extension creates the dedicated file with a minimal subagent prompt when first loaded; edit it directly to change child instructions.
An extension-registered provider must be discoverable or added through template `extensions`, and must not be excluded, for the child to resolve its model.

## Configuration

Optional configuration lives at:

```text
~/.pi/agent/pi-codex-subagents/config.json
```

```json
{
  "storageDir": "~/.local/state/pi-codex-subagents/runs",
  "retentionDays": 7,
  "modelResponseTimeoutMs": 600000,
  "models": ["openai-codex/gpt-5.6-sol", "anthropic/claude-opus-4-6"],
  "modelsFromEnabledModels": true,
  "directSkillRoutes": {
    "tighten-docs": { "agentType": "luna-direct" },
    "session-title-curation": {
      "agentType": "luna-title-direct",
      "proposalOnly": true
    }
  },
  "defaults": {
    "skills": ["web-investigate"],
    "extensions": ["@scope/pi-extra-tools"]
  }
}
```

`storageDir` accepts an absolute path, `~/...`, or a path relative to the package configuration directory. By default runs are stored in `~/.pi/agent/pi-codex-subagents/runs`. `retentionDays` defaults to `7`; expired runs and oversized tool outputs are removed when the extension loads. Set it to `0` to disable automatic cleanup. Runtime sockets remain in the operating system temporary directory and are removed when agents stop.

`modelResponseTimeoutMs` limits one model response, from assistant message start to completion, and defaults to 10 minutes. It does not limit tool execution or the agent's total runtime. A response that keeps streaming forever is failed and its child process is terminated so waiters cannot block indefinitely. Set it to `0` to disable this guard.

`shortcut` optionally binds a key to the subagent browser, for example `"shortcut": "ctrl+shift+a"`. No shortcut is assigned by default; omit it or set it to `""` to leave it unbound. Run `/reload` after changing it.

Configuration is read when agents spawn, while cleanup runs when the extension loads. Restart Pi after changing `storageDir` or `retentionDays` so storage lookup and cleanup use the same configuration throughout the process.

Template skills and extensions override configured defaults; these are additions to native discovery, not its replacement.
Skills explicitly requested by the parent are added to configured template/default skills.
Tool selection belongs to the template or uses normal Pi activation when omitted.
A `model` and `thinking` level requested by the parent override the template and the inherited values, so one task can run on another model without a template.

## Direct skill routing

`directSkillRoutes` delegates exact `/skill:<name>` invocations to an agent template before the parent model runs. Each route requires `agentType`; `proposalOnly: true` adds the existing parent session identity and instructs the child to return proposals without mutation. This is a prompt-level instruction, not a security boundary: use a read-only template when the child must be mechanically unable to apply changes.

Direct routes apply only to idle, text-only interactive or RPC input. Images, extension-authored input, and queued input follow Pi's normal skill handling. The child message keeps `/skill:<name>` first so Pi expands the skill, then appends the agent template prompt. Template frontmatter still configures the child model, thinking, tools, skills, and extensions.

Missing routes use normal parent execution. A missing template, unavailable proposal session, or missing parent identity also falls back before child startup, with a warning. Once child startup is attempted, any failure is reported without rerunning the skill on the parent because the child may already have produced effects. Child completion uses the normal parent-continuation delivery path.

Direct routing requires a Pi version whose extension context provides `resolveSkillCommand()`; older versions continue to support ordinary `spawn_agent` use.

## Model routing

An allowlist in `config.json` decides whether a parent may request a `model` and a `thinking` level per spawn, and which models it may pick. Both arguments appear together or not at all: an installation that configures nothing keeps routing in templates and inheritance. Two sources may be combined:

- `models` lists exact `provider/model-id` pairs approved for this extension alone, independent of any Pi setting.
- `modelsFromEnabledModels: true` adds the models Pi already scoped for the session, resolved from the `enabledModels` setting and `--models`. Models approved for the installation need no second approval here, and Pi has already expanded globs, preferred aliases over dated versions, and dropped unavailable entries. When Pi has no model scoping configured, this source adds nothing.

The arguments are offered only when at least one allowed model is available, and `model` enumerates exactly those pairs:

| Configuration | Allowed and available | `model` and `thinking` on the tool |
|---|---|---|
| neither key set | — | absent, routing belongs to templates |
| `"modelsFromEnabledModels": true`, Pi scoping unset | — | absent |
| `"modelsFromEnabledModels": true`, Pi scoping set | 2 models | present, `model` lists those 2 pairs |
| `"models": ["typo/xyz"]` | nothing available | absent, entry reported as a notification |
| both keys set | the union, deduplicated | present, `model` lists the union |

The list is resolved when a session starts: `models` entries are filtered to what is currently available, unavailable entries are reported as a warning notification, and the scoped models are merged in. Editing the configuration or the Pi setting takes effect when the next session starts, matching the `storageDir` and `retentionDays` behavior above. If a provider drops out mid-session, `spawn_agent` refuses that model at spawn time instead of serving a stale route.

An allowed model may belong to an extension-registered provider.
Its provider extension must load through native discovery or the template's explicit additions.

A thinking level written into an `enabledModels` pattern, such as `anthropic/claude-opus-4-6:high`, is ignored here. `thinking` stays a separate argument, and the child clamps it to what its model supports.

## Completion delivery

A child completion or failure is delivered automatically to its parent session after the child reaches final status. If the parent is active, the result joins the current run; if the parent is idle, it starts a continuation turn. Continue independent work instead of waiting. Use `wait_agent` or `wait_all_agents` only when the next action depends on those responses and no useful work remains meanwhile; an active wait receives the result directly without a duplicate automatic message.

## pi-link worker conversations

When the parent also loads a pi-link version with the worker bridge, `link_send` with `to: { broadcast: true }` and `includeSubagents: true` reaches active workers directly through their owning manager.
This includes the sender's workers.
The parent model does not forward those messages.
Completed, interrupted, suspended, and paused workers are not restarted or resumed for delivery.

`link_reply` accepts a full received message ID and reply text.
When pi-link is enabled, it owns that public tool and delegates admitted manager-delivery references to the helper; direct endpoint references stay with pi-link.
When pi-link is disabled, the helper registers the fallback tool at session startup.
The manager preserves reply support even when a template explicitly limits task tools or selects no task tools.
Other link tools follow ordinary extension configuration and the template's explicit tool list, with no worker-role exclusion.
A queued message does not grant reply permission until it enters that child's native transcript.
The manager validates the worker's stable ID and parent session before routing its reply.
A root's answer returns only to that requesting worker, not its siblings or the owner's model context.
Ordinary task completions still go to the parent.
When pi-link is enabled, it loads its ordinary tools and an independent connection in the child.
Use `disabledExtensions` to opt out of that connection; a read-only explicit tool list still restricts the model's tools.

Worker delivery requires Pi's native fresh-input admission and pause APIs in children.
Missing integration reports `unsupported`; stopped or paused destinations report `skipped`.
Routing receipts acknowledge submission, not model read, and unknown outcomes are not retried automatically.
No worker acknowledges a broadcast automatically, and several workers may independently ask the same question.
See the installed pi-link skill for communication conventions.

## Commands and TUI

On Pi versions with historical message renderer support, collapsed completion headings show the colored status and agent name without reading the response body.
Opening the entry shows the full delivered completion message.
Older Pi versions keep the normal completion renderer.

While agents are starting or running, a compact one-line indicator appears above the editor. It shows the task name for one active agent or a count for multiple agents and points to `/subagents`. The indicator disappears when no agents are active.

`/subagents` opens the agent browser for the current session. Each row shows the task name, status, elapsed time, model, and thinking level, with the task preview underneath. Long names are shortened to fit the terminal. Press Tab to switch to the read-only all-sessions view, then Enter to open an agent.

The overlay uses the child working directory for tool rendering and synchronizes in-progress output when opened midway through a run. Use Left/Right to switch between agents in the current browser scope.

Child RPC processes are terminated after completion, failure, or interruption so settled agents do not keep consuming memory. `send_message` starts a fresh child process with the persisted session and continues from there. On startup, the extension also reconciles and terminates validated owned children left behind by an earlier extension process.

### Working-copy commit-boundary protection

The independently deployed dotfiles boundary integration can warn before a structured write makes the latest finished editing response's diff no longer separately selectable by `agent-split`.
Its ignored `target/jj-split/commit-boundary.json` record belongs to the working copy, so protection follows writes across parent sessions, fresh workers and resumed workers, including after child-process exit.
A warning blocks that write once and retires the protected selection; an intentional retry can proceed.
Read-only turns do not replace the record.

The boundary harness owns capture, checking and record retirement; this package's manager and child helper neither retain nor transport boundary state.
There is no checkpoint restore command or extension-event protocol.
This package has no special boundary-controller discovery; a controller can load through Pi's normal extension setup.
Normal sandbox launchers already inject guest tools; native tools need the boundary extension loaded through their existing extension setup.
For source-backed native and guest regression commands, see [changed-core tests](test/SOURCE-CORE.md).

## Durable pause

Use `/pause --exit` to save the parent and its children, then exit only after saving succeeds.
Reopen the **same parent session file**, which starts paused, and run `/unpause`.
`/resume` remains Pi's session picker.
In RPC mode, `/pause --exit` may need a subsequent command or stdin EOF before the process exits; see [source-test limits](test/SOURCE-CORE.md#coverage-and-limits).

| Command | Action |
|---|---|
| `/pause` | Stop at complete provider/tool boundaries, persist pending inputs, and close captured children |
| `/pause --exit` | Save, then request shutdown; failure leaves the parent open |
| `/pause --status` | Show the phase, pending count, and current pause operation, including the child being captured or closed |
| `/unpause` | Prepare saved children idle, then start fresh continuation runs |
| `/pause --discard` | Explicitly revoke saved pending inputs; already-admitted new runs remain owned by Pi |

This requires command-context `handoff()` and `submitInput()`, pause APIs, and opted-in paused command dispatch.
An older Pi can still run ordinary subagent tools but cannot save this workflow.
The packaged child helper loads before template extensions and checks these capabilities before restoration.
Templates that start independent provider work outside Pi's normal admission are unsupported.

Pause requests reach existing children without waiting for the parent's current provider response or tool batch to finish.
Saving rechecks for children started by already-admitted parent tools.
A running tool must finish before saving succeeds.
While saving, `/pause --status` distinguishes parent submission drain, parent response/tool completion, child capture, and child closure.
For example, `Suspension: preparing; pending 0; capturing child /reviewer.` identifies the child currently being captured.
Operation details describe live work only; they are not restored when reopening the session.
A tool or handler that never returns prevents graceful save; terminating it is not successful suspension.
Wait tools return a nonterminal paused result while the parent batch drains.
Child completions remain buffered until parent delivery is acknowledged.

Continuation reads the latest valid transcript and visibly identifies itself as harness input, not a new human request.
Completed tool effects are not mechanically repeated, although the model can choose to call a tool again.
Pending text, images, and distinct equal-content occurrences survive; replay can change roles, timestamps, and cross-lane order.
Fresh runs use current settings and a fresh retry budget, not saved callback or scheduler state.
An idle parent with only child work receives no unnecessary continuation prompt.

A partial failure reports **incomplete**, not saved.
Keep that parent open and retry `/pause`, or `/unpause` to continue captured work without restarting unaffected children.
If one continuation starts and another fails, retry does not start the accepted continuation again.
Handled/rejected continuation markers leave the original task unresolved.
Unknown admission or process death after admission requires inspection, not speculative replay.
Inspect transcripts, child status, and the group record before explicitly discarding work you no longer need.
Ordinary quit, abort, or forced termination does not implicitly save pending inputs.

Records live under the configured runs directory, in the parent's scope directory: `group.json`, child `*.info.json`, and session transcripts.
Saved work is exempt from retention cleanup until resumed or discarded.
Restart authority requires the original parent ID, canonical file path, and an ancestor transcript anchor.
Copies, forks, imports, and navigation behind/off that anchor cannot replay the saved generation.
Consumption and discard remain revoked across transcript navigation.

An exclusive `.group.claim` prevents concurrent restoration.
Normal shutdown releases it.
After a crash, remove a stale claim only after verifying that no parent or restore process still owns it; a PID alone is insufficient proof.
Keep the group record and transcripts for recovery.

## Output limits

Automatic completions, wait tools, and response tools follow Pi's standard 50 KB / 2,000-line output limit. Oversized output is truncated and the complete text is written beside the runtime data; the returned notice includes a path that can be read with Pi's `read` tool.

## Environment

`PI_SUBAGENT_PI_BIN` overrides the Pi executable used for child processes. Normally children use the same Pi installation as the parent.

## Development tests

From the repository root, run `bun run test:subagents`.
The suite uses changed Pi sources, the real RPC/session runtime, a local faux provider, and disposable state without provider credentials.
Set `PI_TEST_CORE_ROOT` to the companion Pi checkout if it is not `/src/llms/pi`.
See [the source-test instructions](test/SOURCE-CORE.md) for prerequisites, focused runs, and fixture limits.
Installed package artifacts are not sufficient evidence for the pause workflow.

## License

MIT
