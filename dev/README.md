# Development and maintenance

Run the commands below from the repository root. See [configuration](../config/README.md)
for installing or adding dotfiles, and the [tools reference](../tools/README.md)
for subsystem-owned commands and tests.

## Repository change guidelines

### Layout and conventions

Small user commands and command links live in `bin/`; independently invoked
subsystems, with their tests and documentation, live in `tools/<name>/`.
Shared internal implementations belong in `libexec/`, maintenance commands in
`dev/`, and cross-cutting tests in `tests/<feature>/`. Configuration belongs in
`config/`, system files in `global/`, sourced support and static assets in `lib/`,
vendored code in `vendor/`, and package manifests in `install/`.
Setup entry points are `setup`, `setup.ps1`, and `track`.

Keep scripts portable unless the existing file targets one platform. Match native
formatting rather than normalizing unrelated code. Declared POSIX `sh` scripts use
tab-indented blocks and explicit `set -e` or `set -u` when failure handling matters.
Python uses four-space indentation, standard-library `unittest`, type-friendly
signatures, and `Path` for filesystem work.

Comment implementation choices that preserve non-obvious historical constraints:
name the constraint and why the choice preserves it. Preserve concurrency when
consolidating independent operations. For batches, use a review surface suited to
many results rather than repeating the single-item interaction.

### Commands and validation

Read the relevant setup function before using `./setup` on a new machine.
`./track <existing file> [name]` moves a user file into `config/` and adds its Dotbot
mapping, or copies a system file into `global/` and records it in `install/global.txt`.

Use [Testing and probes](#testing-and-probes) for dependencies and isolation:

- `dev/test` runs the suite and repository checks.
- `python3 tools/open/tests/test_open.py` tests the editor/open wrapper.
- `python3 tests/wezterm/wezterm_test.py` tests selectors in `config/wezterm.lua`.
- `shellcheck setup track bin/* dev/* libexec/**/*.sh tools/**/*.sh` checks applicable
  shell files; some entries are not shell scripts.

Keep subsystem tests under `tools/<name>/tests/` and cross-cutting tests under
`tests/<feature>/`. Name Python files `*_test.py` or `test_*.py`, and name test
methods after the protected behavior. Prefer temporary directories and mocks to
real home state. Config regex tests need positive and negative examples.

Before using an undocumented mutation API on production, test it end-to-end on an
owned disposable resource, verify the complete result, and restore or delete that
resource. Recovery tests must cover states left by failed recovery attempts, not
only clean startup and normal shutdown.

Validate configuration with its native parser or application where practical,
as well as repository tests. Examples: shell syntax checks, `jq empty
config/agents/claude/claude.json`, headless Neovim startup, Kitty's loader, and
`claude doctor`. Distinguish parser failures from unrelated runtime,
authentication, or environment warnings. Confirm the application loaded changes
before interpreting results, as required by the shared instructions.

### Review and bootstrap

Follow [commit-quality](../skills/commit-quality/SKILL.md) for atomic changes,
imperative subjects, and explanatory bodies. PRs state the user-visible change,
commands run, and platform assumptions; include screenshots only for visual
terminal or desktop behavior.

Follow the early safety constraints in [AGENTS.md](../AGENTS.md) for generated
outputs, VM repairs, credential scopes, privileged system files, and secrets.
When adding dotfiles or packages, review `install.conf.json` or `install/*.txt`
so bootstrap behavior stays predictable.

## Testing and probes

Before running Pi tests or compaction replays, ensure the locked dependencies are
installed. This requires Node/npm; Pi tests and replays also require Bun.
For initial setup or after dependency changes, run this before starting tests,
not alongside them:

```sh
npm ci --ignore-scripts --no-audit --no-fund
```

This makes tests and replays use the locked Pi SDK instead of Bun's
auto-installed or cached version.

Run `dev/test` for the suite, including `tests/pi`, with the prerequisites above.
It checks for Bun on PATH before running any suite and stops with installation
guidance if Bun is missing.
It invokes `dev/test-environment` automatically; a failing Pi test stops the runner.
Python discovery follows `pytest.ini`: `*_test.py` and `test_*.py` under `tests/`
and `tools/`. Other suites need an existing discovery route or explicit dispatch
in `dev/test`, by default or through a documented opt-in mode. Check that the
intended cases execute through that route, not only through a focused command.
For focused tests and ad-hoc Pi probes, including `--help` checks, use
`dev/test-environment COMMAND [ARGS...]`. For example:

```sh
dev/test-environment bun test tests/pi/luna_compaction_test.ts tests/pi/replay_compaction_test.ts
```

The wrapper requires Python 3 and creates a private HOME and Pi/XDG state
directories. It removes them after the child exits normally, nonzero, or by
forwarded signal, preserving stdin, stdout, stderr, and exit status. This is
environment isolation, not a filesystem sandbox: commands can still write
explicit paths outside HOME. Check generated-source freshness with check-only
commands or a disposable checkout, not an updater targeting the working copy.
The wrapper clears inherited `JJ_CONFIG` so Jujutsu loads user configuration from
the private HOME/XDG directories instead.
Cargo is the exception to disposable per-run state: the wrapper sets `CARGO_HOME` to `target/test-environment/cargo` in this checkout.
That stable test-only directory reuses downloads and source paths, allowing unchanged compiled dependencies to stay fresh across runs.
It never imports the inherited Cargo home's configuration or credentials.
Anything a test command writes there, including Cargo configuration or credentials, persists until you remove the directory.
Set `DOTFILES_TEST_CARGO_HOME` to another owned disposable directory when testing Cargo configuration or when a fresh cache is required.
Nested wrapper calls retain that path.
An unusable cache directory fails before the child starts; the wrapper does not fall back to the user's Cargo home.
Cargo's build-output location is unchanged.

The sandbox launcher and proxy tests in `tools/codex-sandbox/tests/` require
permission to create local TCP and Unix sockets. If an execution sandbox denies
socket creation with `PermissionError: [Errno 1] Operation not permitted`, rerun
the affected command outside that sandbox using the harness's approval mechanism.
Keep the `dev/test-environment` wrapper; HOME isolation does not grant socket
permissions.

The wrapper sets `FISH_UNIT_TESTS_RUNNING=1` so interactive Fish skips detached man-page completion generation.
Fish still loads its normal startup configuration.
This prevents its startup completion jobs from racing private-HOME cleanup.

For `bb`, `java`, `jj`, and `rg`, the wrapper preserves explicit real-tool overrides
or resolves mise shims before changing HOME. Failed resolution stops the run before
a child starts. Repository-local exclusions keep dependencies, notes, test caches,
and editor sessions untracked even when private HOME hides global ignore rules.

An explicit `PI_PACKAGE_DIR` takes precedence. Otherwise, the wrapper discovers the
installed Pi SDK under the original HOME before replacing HOME, so tests can
read the installed SDK without loading personal settings or using its caches.
The wrapper resolves SDK directory symlinks before isolation, including explicit
overrides, so Node can discover dependencies beside the source checkout.
For `dev/test --containers`, the runner also captures the validated host Pi
installation revision before replacing HOME. The runtime-image probe builds and
checks that commit. Missing or invalid revision metadata stops the runner before
any tests; repair the installation with `mise run pi-install`.

For Neovim config tests, the wrapper discovers installed plugins at
`${XDG_DATA_HOME:-$HOME/.local/share}/nvim/lazy` before isolation and passes
`DOTFILES_TEST_NVIM_PLUGINS`. An explicit nonempty value takes precedence and
survives nested wrappers. The fixture copies plugins into temporary storage;
Neovim never writes to the installed plugin tree. Run the focused suite with
`dev/test-environment python3 tests/nvim/nvim_test.py`. It requires Neovim and
installed plugins, and reports skipped tests when either is absent.

The native prompt-section regression needs an installed Pi build with
`systemPromptOptions.sections`; the locked test SDK predates that API. Run it
without Bun's module mocks:

```sh
dev/test-environment node --test tests/pi/native_prompt_sections.mjs
```

Do not wrap the [configured startup benchmark](../tools/codex-sandbox/development.md#measure-interactive-startup)
or live `dev/replay-compaction` requests: those intentionally use installed
configuration, caches, or authentication. Isolated runs do not measure that setup.

### Broker-backed live provider probe

Running this probe makes a live model request through the sandbox broker and may incur model cost.
It uses the installed Pi SDK, private HOME, no model-catalog refresh, and no discovered extensions or sessions.
Unlike `dev/replay-compaction`, it does not need personal configuration or stored authentication.
The parent passes broker credentials through stdin because `dev/test-environment` removes the inherited broker variables.
Do not put the key in command arguments, files, or diagnostic output.

Save these two files in a private temporary directory.
Use an available `openai-codex` model ID when running the launcher from the repository root.

`probe.ts`:

```typescript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const packageDir = process.env.PI_PACKAGE_DIR;
assert.ok(packageDir, "Set PI_PACKAGE_DIR to the installed Pi SDK");
const manifest = JSON.parse(readFileSync(resolve(packageDir, "package.json"), "utf8"));
const { ModelRuntime, ModelRegistry } = await import(pathToFileURL(resolve(packageDir, manifest.exports["."].import)).href);
const { default: codexSidecar } = await import(pathToFileURL(resolve("config/pi-agent/pi-extensions/codex-sidecar.ts")).href);
const { baseUrl, apiKey } = await Bun.stdin.json();
assert.ok(baseUrl && apiKey && process.argv[2], "Broker credentials and a model ID are required");
process.env.CODEX_SIDECAR_URL = baseUrl;
process.env.CODEX_SIDECAR_KEY = apiKey;

const runtime = await ModelRuntime.create({ modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
const registry = new ModelRegistry(runtime);
codexSidecar({ registerProvider: registry.registerProvider.bind(registry) });
const catalogModel = registry.find("openai-codex", process.argv[2]);
assert.ok(catalogModel, "Model is missing from the installed catalog");
// Catalog metadata can retain a different endpoint despite provider registration.
const model = { ...catalogModel, baseUrl };
const response = await registry.complete(model, {
  messages: [{ role: "user", content: [{ type: "text", text: "Reply only PROBE_OK." }], timestamp: Date.now() }],
}, {
  maxTokens: 256, reasoningEffort: "low", transport: "sse", signal: AbortSignal.timeout(60000),
  onPayload: (_payload, requestModel) => {
    assert.equal(requestModel.baseUrl, baseUrl, "Refuse to send broker credentials to another endpoint");
  },
});
assert.equal(response.stopReason, "stop", "Probe did not finish normally");
console.log("Broker request completed.");
```

`run.py`:

```python
import json
import os
from pathlib import Path
import subprocess
import sys

broker = {"baseUrl": os.environ["CODEX_SIDECAR_URL"], "apiKey": os.environ["CODEX_SIDECAR_KEY"]}
probe = Path(__file__).resolve().with_name("probe.ts")
result = subprocess.run(
    ["dev/test-environment", "bun", str(probe), sys.argv[1]],
    input=json.dumps(broker), text=True, check=False,
)
sys.exit(result.returncode)
```

Run `python3 /path/to/run.py MODEL_ID` with broker variables available in the parent environment.
Set `PI_PACKAGE_DIR` if the installed SDK is not discoverable under the original HOME.
The endpoint assertion checks the effective request model before the provider sends HTTP headers.
This SSE probe checks broker connectivity, not WebSocket behavior or the web-search extension.
For offline activity persistence and replay coverage, run `dev/test-environment node --test tests/pi/native_web_search.mjs`.

## Bootstrap maintenance

Run `dev/update-bootstrap-lock --dry-run` to preview newer plugin revisions,
release assets, and checksums. Run it without `--dry-run` to update
`install/bootstrap.lock.json` and `install/bundles.json`, then review the diff
and run `dev/test`. The updater uses `GITHUB_TOKEN` when it is already set,
but does not require or export one.

## Replay a compaction

A replay makes a live Luna request and may incur model cost. It uses normal Pi
authentication or the sandbox model broker; do not run it through
`dev/test-environment`. Install the [locked dependencies](#testing-and-probes) first.

To compare [compaction instruction](../config/pi-agent/pi-extensions/compaction.md)
changes against a saved compaction, run:

```sh
dev/replay-compaction SESSION.jsonl [COMPACTION_ID]
```

By default, the command selects the latest compaction on the session's active
branch; an entry ID selects a specific one. It saves `original.md`, `new.md`,
the input and instructions, and token usage in a private temporary directory
for manual comparison. The session file is never modified; failed requests
retain the replay inputs.

Replay uses the recorded cut point and previous checkpoint, not today's retention
settings. It uses current instructions, SDK serialization, and the default model
budget; original custom compaction instructions and generation settings are not
recorded and cannot be reconstructed. Caller-added repository status is excluded
from the comparison and input when saved checkpoint metadata identifies it;
older summaries without that metadata remain intact.

The replay applies the extension's required-header check to generated output;
it does not judge semantic retention. Use the source-backed
[retention cases](../tests/pi/fixtures/compaction-replay/README.md) to compare
persistent corrections, conditional permissions, paused work, investigation-only
authority, repeated compaction, and accepted evidence versus newer experiments.
Their checklists require human comparison against recorded source turns, not a score for prose quality.

The offline [replay tests](../tests/pi/replay_compaction_test.ts) run with the
focused test command above. They verify input reconstruction, not model retention.
See the [extension guide](../config/pi-agent/pi-extensions/README.md#compaction)
for compaction behavior and instruction updates.
