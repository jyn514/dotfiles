# Changed-core test command

From the repository root, run:

```sh
bun run test:subagents
```

For a focused suite, pass its path and optional Bun flags to the driver:

```sh
bun packages/pi-codex-subagents/test/run-source-tests.ts packages/pi-codex-subagents/test/parent-child-roundtrip.test.ts --rerun-each=5
```

To include the independently deployed pi-link source in the cross-package native test:

```sh
PI_TEST_LINK_SOURCE=/src/dotfiles/tools/pi-link/index.ts bun run test:subagents
```

To exercise the independently deployed commit-boundary controller and actual native/guest tools with local JJ:

```sh
PI_TEST_COMMIT_BOUNDARY_SOURCE=/path/to/dotfiles /path/to/dotfiles/dev/test-environment bun run test:subagents
```

`PI_TEST_COMMIT_BOUNDARY_SOURCE` is the absolute dotfiles checkout root, not an extension file.
Its `dev/test-environment` supplies native JJ/Babashka with disposable configuration, without sandbox proxy authority.
The phase loads the real `commit-boundary.ts` and, in guest mode, `guest-tools.ts` through template extensions.
The guest tool worker uses the selected Pi source public entry and the driver's source aliases, not installed SDK artifacts.
Only owned disposable repositories and Unix sockets are created.
For a focused run, pass `packages/pi-codex-subagents/test/boundary-integration.test.ts` to the driver.

Without the corresponding `PI_TEST_LINK_SOURCE` or `PI_TEST_COMMIT_BOUNDARY_SOURCE`, those integration cases report skips.
The manager/helper suites still run.
The supplied pi-link directory must have its installed `ws` dependency.
The fixture copies its TypeScript files into disposable storage, verifies the copies, and substitutes only the loopback port.
It never changes the pi-link checkout or binds its usual port.

`PI_TEST_CORE_ROOT` selects the core checkout (default `/src/llms/pi`).
The driver reads its authoritative tsconfig aliases, rebases them to absolute source paths, and supplies an ephemeral config via Bun's `--tsconfig-override` to tests and child processes.
Transitive workspace imports use source; no build or dependency changes are needed.
`--no-install` disables Bun auto-installation.

## Isolation and ownership

The driver runs each suite in a separate Bun process, keeping `core.test.ts`'s SDK `mock.module` replacement isolated.
Each interpreter gets disposable HOME/XDG state, TMPDIR (including loader caches), and `PI_TEST_OWNED_ROOT`, without inherited provider credentials and with `PI_OFFLINE=1`.
`--no-orphans` bounds descendant cleanup.
The driver reports each phase and removes its owned storage after exit.

Native suites are skipped by ordinary unconfigured `bun test`; use this source-backed driver for changed-core coverage.
Installed SDK execution is not a substitute.

The legacy core fixture uses `PI_TEST_OWNED_ROOT/a` (or a unique temporary fallback) and removes it in `afterAll`.
Tests do not rewrite copies or preload SDK mocks.

## Native fixture

`source-rpc-child.sh` is the executable `PI_SUBAGENT_PI_BIN` and propagates the source aliases.
Its TypeScript entrypoint uses public `ModelRuntime`, `createAgentSessionServices`,
`createAgentSessionFromServices`, `createAgentSessionRuntime`, and shipped `runRpcMode`.
Only model I/O is faux; session execution, RPC framing, pause/handoff, extension contexts,
Manager, production `index.ts`, and coordinator behavior are real.
Tests need no private production or core-test imports.

The fixture supports the tested CLI subset: `--session`, ordered `--extension` paths, `--tools`, `--no-tools`, and `--no-builtin-tools`.
Explicit tool selection goes through the real SDK's registration and activation rules, including plain lists and native modifiers.
Without tool-selection flags, the fixture intentionally disables builtins.
Model selection is faux; builtins and automatic resource discovery are disabled.
Paths go through public `resourceLoaderOptions.additionalExtensionPaths` and Pi's shipped
`DefaultResourceLoader`/jiti loader, including source SDK virtual modules and tsconfig-path handling.
Manager supplies `child-helper.ts` before explicit template extensions.

`held-tool-extension.ts` registers `faux_hold` with `Type.Object({ path: Type.String() })`.
A `hold-tool:<owned-path>` input makes the provider call it.
The tool writes `.started`, observes native pause state in `.pause-requested`, waits for `.release`,
appends one effect to `.effects.jsonl`, and writes `.ended` before returning.
A later provider request produces normal text, not another tool.
Provider-call and template-start journals derive from the existing session path.

The fixed `parent-held-task:<owned-path>` input scripts real parent tools: `spawn_agent` with the
owned `source-parent-roundtrip` template, then one assistant batch containing `[wait_agent, send_message]`.
Pause releases the wait, while the later admitted call must still steer the child before capture.
`parent-nested-held-task:<owned-path>` uses a packaged test tool to call production `send_message`
through public `ctx.executeTool`, covering its independently assigned nested drain token.
Native nested-call events and persisted `nestedCalls` verify this path.
`parent-blocked-held-task:<owned-path>` holds another parent tool between the wait and send.
The child must observe its pause and finish its held tool without another provider request while that parent tool remains blocked.
Live `/pause --status` notifications identify parent response/tool completion versus capture of the named child, then drop the activity after saving.
Completed tool results prevent either batch from being resent on fresh continuation; there are no
production options or fixture-only APIs.

## Coverage and limits

`manager-checkpoint.test.ts` exercises the volatile handoff with a narrow native checkpoint peer.
It checks real settled child exits and new-PID restoration before the next tool, stable worker/session identity, no-write preservation,
replacement, explicit retirement, missing/malformed exports, startup failure, failed restoration, crashes, interruption,
missing/malformed restore results and helper errors with successful RPC command completion,
late closing-process notifications/settled frames, worker/parent isolation, manager recreation and absence of payloads in production files.
A production-index pause case starts with a live restored checkpoint and verifies the actual saved group record and both transcripts exclude it.
The narrow `checkpoint-rpc-filter.ts` fixture drops or corrupts only helper-result frames from a real native child to test missing receipts.
It does not replace session execution, helper code or provider behavior.
`boundary-integration.test.ts` additionally exercises the production boundary controller, actual native/guest writes and real local JJ.
It writes and hibernates, preserves the checkpoint through a no-write turn, restarts and blocks the separating edit once,
then hibernates and restarts again with the checkpoint retired so retry succeeds.
The peer fixture establishes transport/lifetime behavior; it is not a substitute for that actual boundary-policy regression.

`manager-link.test.ts` exercises the real manager, child helper, native transcript, and RPC control path.
It checks worker ownership, selection during startup, delivered-reference replies before and after child recreation, and stable-ID private delivery.
It also checks refusal to wake paused or completed children and reply-tool availability with empty and modifier-based task-tool selections.
`link-integration.test.ts` additionally loads the production subagent extension and pi-link in two real RPC roots connected over WebSocket.
It checks sender-worker inclusion, two remote siblings independently asking the same question, worker author attribution, private replies, and the absence of worker root connections.
Only provider responses are scripted; production routing and lifecycle behavior are unchanged.

The suite covers source resolution (including rejection of stale installed `dist/index.js`),
real RPC prompt/stream/session behavior, held-tool completion, and pause/reopen continuation
without repeating completed effects.
Manager coverage includes parent waits and admitted batches, paused-submission rejection,
child fencing and closure, persisted captures, recreation, same-UUID/session restoration,
resume, and completion delivery.

The production-index/coordinator suite pauses an active parent with a held-tool child, closes RPC,
reopens, and unpauses.
It checks parent and child continuation, tool result/effect, child identity and file,
provider-work fencing, and buffered completion acknowledgment/delivery.
It also checks direct and nested same-batch sends are captured once and delivered in fresh child
history without extra provider requests or repeated effects.
Manager coverage starts another admitted child after the initial pause and verifies that capture also fences that child.

`pause-exit-rpc.test.ts` verifies durable save and safe child exit before a subsequent `get_state`
triggers the existing shutdown check and exits zero.
RPC `/pause --exit` may otherwise remain running until a client sends another command or closes
stdin at EOF; core behavior is unchanged.
The interactive `ctx.shutdown()` success path is tested, but the full TUI frontend is not verified.

Bun may print an internal `directory mismatch` diagnostic with `--tsconfig-override`;
tests assert source resolution and complete despite it.
