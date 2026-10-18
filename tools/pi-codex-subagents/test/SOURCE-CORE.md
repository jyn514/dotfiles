# Changed-core test command

From the repository root, run:

```sh
bun run test:subagents
```

For a focused suite, pass its path and optional Bun flags to the driver:

```sh
bun packages/pi-codex-subagents/test/run-source-tests.ts packages/pi-codex-subagents/test/parent-child-roundtrip.test.ts --rerun-each=5
```

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

The fixture supports the tested CLI subset: `--session` and ordered `--extension` paths.
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
Completed tool results prevent either batch from being resent on fresh continuation; there are no
production options or fixture-only APIs.

## Coverage and limits

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

`pause-exit-rpc.test.ts` verifies durable save and safe child exit before a subsequent `get_state`
triggers the existing shutdown check and exits zero.
RPC `/pause --exit` may otherwise remain running until a client sends another command or closes
stdin at EOF; core behavior is unchanged.
The interactive `ctx.shutdown()` success path is tested, but the full TUI frontend is not verified.

Bun may print an internal `directory mismatch` diagnostic with `--tsconfig-override`;
tests assert source resolution and complete despite it.
