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

To test the shared/root split with the independently deployed dotfiles instruction-includes extension:

```sh
PI_TEST_INSTRUCTION_INCLUDES_SOURCE=/src/dotfiles/config/pi-agent/pi-extensions/pi-instruction-includes.ts bun run test:subagents
```

The path selects the actual extension source, not a copied implementation.
The discovery suite creates disposable global/project instructions, ROOT, a child-role file, and symlinked/nested includes.
Without this variable, the include-specific composition cases report skips; the native no-include cases still run.

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

The fixture supports the tested CLI subset: `--session`, ordered `--extension` and `--skill` paths,
`--tools`, `--no-tools`, `--no-builtin-tools`, `--approve`/`--no-approve`, resource-discovery suppression flags,
`--no-context-files`, `--system-prompt`, and `--append-system-prompt`.
Explicit tool selection goes through the real SDK's registration and activation rules, including plain lists and native modifiers.
Without tool-selection flags, fresh sessions use normal builtin and extension-tool activation; resumed or forked sessions retain native transcript selection among currently registered tools.
Model selection remains faux.
Native settings load from disposable user/project files with the supplied project-trust decision;
only compaction and retry are overridden for deterministic tests.
Paths go through public resource-loader options and Pi's shipped
`DefaultResourceLoader`/jiti loader, including source SDK virtual modules and tsconfig-path handling.
Manager supplies `child-helper.ts` before selected extension entrypoints.

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

`fork.test.ts` creates owned native branched sources with messages, completed tool results, compaction, metadata cuts and labels.
It checks actual provider context and the registered `spawn_agent` schema, including required `message`, exact source/cut failures and fresh omission.
Explicit-tool cases exercise settled continuation, native pause/recreation, retained source-tool effects and retention of both linked native child files.
They remove the source before continuation to detect accidental re-extraction and check that expired child cleanup leaves the source and neighboring tasks intact.
Edited role and shared-context markers verify current instruction loading on fork, settled recreation, and pause/reopen continuation.
A separate selection case records a real source loadout with public `setActiveTools()`, then checks inherited `read`/`grep` selection and native template modifiers.
Current default-active and default-inactive extension tools remain registered without automatically joining that restored selection.
An actual attempted call verifies that an unavailable historical tool is neither registered nor executable; the explicit plain-list case separately checks template override behavior.

`discovery.test.ts` checks native configured-package discovery, user/project skills and prompt templates,
canonical-path and package-basename exclusions, and explicit additions subject to exclusions.
A disposable monorepo contains a denied manager entrypoint and an allowed sibling extension.
Import, factory, and hook markers show that only the trusted project fixture executes;
the denied manager never executes, even when explicitly added.
The discovered tool is called despite being absent from the supplied parent tool names.
Explicit task-tool lists still restrict it, while the helper's `link_reply` remains available.
Fresh worker processes retain trust and exclusions after template edits, expand skills/templates normally,
and compose the dedicated child role with native base/append selection and shared context files.
Composition cases compare root and child provider prompts with default and configured bases, ancestor/cwd overrides,
one shared skill catalog, and role/template/task cardinality.
With the actual include extension selected, they also check optional ROOT refresh and exclusion from children,
symlinked shared rules, nested relative includes, and helper-before-include ordering.
The SDK fixture supplies dummy built-in factories through public `InlineExtension` descriptors, using the manager's authoritative name list.
They record factory/hook execution and register no-I/O tools instead of starting actual CLI services.
Built-in cases cover default discovery, selective `builtin:name` exclusions, native settings exclusions,
trusted/untrusted project overrides, and explicit task-tool restrictions.
A separate exact-name assertion checks the four user-approved current CLI identities; service behavior is not tested here.

`boundary-integration.test.ts` exercises the production boundary controller, actual native/guest writes and real local JJ.
Worker A reorganizes rules, settles and exits; the test requires the harness-owned shared record to exist.
A read-only resumed turn preserves that record, then the manager shuts down.
A new manager and parent session spawn a different worker B to attempt an extraction.
B must receive one warning with the file unchanged and the record retired.
Another read-only turn cannot resurrect it; B's resumed retry runs in a new process and succeeds without changing unrelated edits.
The fixture ignores `/target/jj-split/` before its baseline commit and never seeds or mutates boundary records.
Companion dotfiles tests cover shared-record concurrency, independent SDK sessions and isolation between separate JJ repositories.
They do not exercise an actual manager parent/child hierarchy or linked JJ workspaces.
The removed manager/helper checkpoint handoff is not a supported integration.

`manager-link.test.ts` exercises the real manager, child helper, native transcript, and RPC control path.
It checks worker ownership, selection during startup, delivered-reference replies before and after child recreation, and stable-ID private delivery.
It also checks refusal to wake paused or completed children and reply-tool availability with empty and modifier-based task-tool selections.
`link-integration.test.ts` additionally loads the production subagent extension and pi-link in real RPC sessions connected over WebSocket.
Its helper-only case explicitly excludes pi-link from workers and checks sender-worker inclusion, two remote siblings independently asking the same question, worker author attribution, private replies, and the absence of independent worker connections.
Its configured full-worker case checks independent worker endpoints and replies through both direct endpoint delivery and manager delivery.
It also checks ordinary link-tool availability, explicit selected-tool lists, and a read-only scout list that retains only helper reply support alongside its task tools.
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
