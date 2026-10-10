# Codex sandbox development

Use the [operator guide](README.md) for host setup, session commands, safety, and recovery.
Before running tests or probes, follow the repository
[testing and isolation rules](../../dev/README.md#testing-and-probes).
The startup benchmark below uses the host's real configuration.

## Startup terminal ownership

Redirecting the detached owner's stdio at fork made BuildKit lose its TUI:
Lima's `sandbox_runtime.py` build path needs both stdin and stderr to be TTYs
so SSH requests a guest PTY for automatic progress display. Keeping only stderr
on the terminal is not sufficient.

Preserve these boundaries when changing launcher output or process ownership:

- During interactive provisioning, `host_pi_owner.detached_frontend` keeps the
  invoking terminal's original stdin, stdout, and stderr. Do not force progress
  with `BUILDKIT_PROGRESS` or plain-progress output.
- Before bootstrap completes, `codex-sandbox.run_agent` starts the guest worker
  with explicit `DEVNULL` stdin and `OWNER_LOG_FD` stdout/stderr; inheriting the
  owner's stdio would retain the source pane's terminal.
- `HostPiOwner.mark_bootstrapped()` redirects owner stdin to `DEVNULL` and
  stdout/stderr to the private owner log before starting attachment service or
  delivering the first Pi launch spec. Keep `OWNER_LOG_FD` open until owner exit.
- Non-TTY startup retains the existing file-log relay. Startup failures remain
  visible without duplicate diagnostics; interactive output preserves carriage
  returns rather than passing through the text-file relay.
- Terminal handling must not change `/split` lifetime: either pane may close
  first, and shared resources remain until the final Pi attachment exits.

Run the regressions from the repository root:

```sh
dev/test-environment python3 -m unittest discover -s tools/codex-sandbox/tests -p host_pi_owner_test.py
dev/test-environment python3 -m unittest discover -s tools/codex-sandbox/tests -p codex_sandbox_test.py
dev/test-environment python3 tools/codex-sandbox/tests/restart_hook_test.py
```

`StartupTerminalTest` checks real PTY descriptors during build startup,
post-bootstrap detachment, exact output bytes, startup failure, and non-TTY
relay behavior. The launcher worker-stdio test checks the production handoff
with a native child. Owner tests also cover either pane closing first.
These local tests do not verify actual VM BuildKit rendering; check that on a
host with the supported runtime before claiming VM acceptance.

## Measure interactive startup

From the checkout being measured, run this repository's probe on a Unix host with local container-socket access:

```sh
TMPDIR=/private/tmp python3 tools/codex-sandbox/tests/interactive_startup.py --runs 3
```

The probe uses the normal launcher and configured extensions in a 30×100 pseudo-terminal, with `--no-session` and Pi's `PI_STARTUP_BENCHMARK` mode.
It makes no model request.
Readiness is the arrival of `interactiveMode.init:` in Pi's timing output, emitted after TUI initialization and a deliberate 150ms terminal-drain pause.
Output reports the observed elapsed time, that pause, and an estimate with the pause subtracted;
process shutdown is excluded.

Each invocation prints a new log directory and retains one raw terminal log per run.
A missing readiness marker or unsuccessful exit fails the probe;
`--timeout` defaults to 30 seconds per run, excluding cleanup.
On macOS, `/private/tmp` avoids the launcher's path-alias assertion.

With `CODEX_SANDBOX_RUNTIME=lima-docker`, the probe also records startup boundaries in JSON beside each log, including on timeout.
Container creation follows `workload_argv end`;
`popen end` marks the attach client's spawn, and `container entry` marks execution inside the container.
The probe mounts diagnostic wrappers and supplies a Node preload through `NODE_OPTIONS` for this run only.
Host markers carry their emission time;
guest markers use host receipt time and include transport delay.
Subtract Pi's own total and the 150ms terminal-drain pause from the Node-preload-to-readiness interval to estimate work before Pi's timer, including early imports.

For stalls, add `PI_STARTUP_PROFILE=1` and `--timeout 90`.
Runtime initialization dumps Python stacks every ten seconds while blocked.
The probe prints a `target/startup-profile-*` directory containing a Node CPU profile and Node's own elapsed/CPU times at readiness and exit.
Profiling begins at the Node preload, adds overhead, and writes its files on normal exit;
forced termination can lose the profile.
These diagnostics distinguish active CPU work from waiting, but host swap allocation alone does not establish paging during a stall.

Record whether images and shared required proxies were already warm, plus host/VM load.
Each run creates fresh agent and optional relay containers, but the probe does not reset caches or shared services.
Compare cold and warm samples separately;
image builds may need a longer timeout.
Do not remove unrelated sessions to manufacture a cold run.

## Tests

Run unit tests from the repository root:

```sh
dev/test-environment python3 -m unittest tools/codex-sandbox/tests/codex_sandbox_test.py
dev/test-environment python3 -m unittest tools/codex-sandbox/tests/sandbox_proxies_test.py
```

To check ordinary and linked-worktree mounts on an existing Docker VM, use an
already built sandbox image containing Python and Git. Replace
`codex-sandbox:TAG` with its image reference:

```sh
dev/test-environment env LIMA_HOME="$HOME/.lima" \
  python3 tools/codex-sandbox/tests/repository_mounts_integration.py \
  --state "$HOME/.local/state/codex-sandbox-docker" --image codex-sandbox:TAG
```

This runs the launcher's mount builder with both worktree and shared Git backend
paths. Networkless fixture containers check relative and absolute pointer files,
Git discovery, writable worktree files, and read-only metadata. Fixtures and
containers are removed after each case.

To compare the bundled resolver's ignore filtering with BuildKit, run the
disposable scratch-image probe against an existing Lima-Docker VM:

```sh
dev/test-environment env LIMA_HOME="$HOME/.lima" python3 tools/codex-sandbox/tests/bake_ignore_integration.py --state "$HOME/.local/state/codex-sandbox-docker"
```

The probe checks case sensitivity, wildcard exceptions, ancestor matching, and
Dockerfile-specific ignore precedence through actual Bake builds and container
exports. It removes its containers and tagged images after each case.

Live Caddy checks in `tests/caddy_foundation_test.py` execute the pinned manifest
for the Docker daemon's platform. Unit checks verify identity selection for both
supported platforms. Foreign-architecture execution requires emulation and is
not part of the default suite.

The runtime integration test builds real images and requires a working Docker-compatible daemon and network access:

```sh
python3 tools/codex-sandbox/tests/image_runtime_integration.py --expected-revision <full-pi-commit>
```

Use the full host commit recorded in `~/.local/share/pi/node/.source-revision`.
The test passes that commit as the required `PI_REVISION` build argument and checks
its recorded revision, retaining Alpine Node and Debian Node-20/Bun coverage.
Direct Dockerfile builds must also supply `--build-arg PI_REVISION=<full-pi-commit>`;
there is no independent guest revision default.

Check the image caches against a built final image;
test containers run without network access:

```sh
docker build --build-arg PI_REVISION=<full-pi-commit> --target pi-extension-cache -f tools/codex-sandbox/image/Dockerfile -t pi-cache-test .
python3 tools/codex-sandbox/tests/cache_integration.py --runtime <sandbox-image> --builder pi-cache-test
docker image rm pi-cache-test
```

This checks Alpine bytecode reuse, first-launch extension cache hits, edited source, isolation between containers, and build failure on missing packages or extension errors.
