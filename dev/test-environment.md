# Test environment wrapper

Use `dev/test-environment COMMAND [ARGS...]` for focused tests and probes.
It requires Python 3 and creates a private HOME plus Pi and XDG state directories.
It removes those directories after normal exit, nonzero exit, or a forwarded signal, while preserving stdin, stdout, stderr, and exit status.
This is environment isolation, not a filesystem sandbox.

For Python tests, use `dev/pytest [ARGS...]`; it applies this isolation and selects
a working pytest with the repository's required plugins, using pinned `uvx`
dependencies when necessary.

For performance benchmarks of the user's installed setup, run the intended entrypoint outside this wrapper.
Preserve the actual HOME, XDG directories, PATH, configuration, session data, and daemon state for both baseline and candidate measurements.
An isolated copy of session files does not reproduce configuration loading, command resolution, or an existing daemon.
Label isolated measurements as such; do not use them to claim the user's startup latency.
Record first-run and warm timings separately, and include process startup, repair work, and cleanup in end-to-end measurements.
Keep correctness tests and disposable mutation probes isolated even when the performance benchmark needs real configuration.
The [configured sandbox startup benchmark](../tools/codex-sandbox/development.md#measure-interactive-startup) is one such real-configuration benchmark.

For wrapper or launcher probes, pass the intended entrypoint by path rather than a bare command name.
Isolation can substitute native tools for bare names; for example, `bb` may select native Babashka rather than this repository's dispatcher.

```sh
dev/test-environment libexec/agent-wrappers/bb agent-split --help
```

On Linux, the wrapper also adopts orphaned descendants and reaps them while the command runs.
After the command exits, the wrapper sends SIGTERM to its adopted children and allows one second for cleanup.
It then kills and reaps remaining descendants before removing HOME.
The command's exit status is preserved; processes outside this invocation's subtree are not signaled.
This cleanup cannot run if the wrapper itself receives SIGKILL.

OpenJDK's `user.home` property also points at the private HOME, overriding inherited home properties through `_JAVA_OPTIONS` while preserving other options.
Native Babashka ignores JVM option variables, so [its preload](test-environment.clj) sets `user.home` before inherited `BABASHKA_PRELOADS` and test code run.
These settings reach absolute executable paths and script shebangs as well as commands found on PATH.
Nested wrapper calls use the inner private HOME.

The wrapper clears inherited `JJ_CONFIG` so Jujutsu reads user configuration from the private HOME and XDG directories.
It also removes inherited sandbox credentials, JJ workspace routing and authority projections, Pi session selection, and personal configuration paths before starting the child.

### Persistent test caches

The wrapper sets `CARGO_HOME` to the stable test-only directory `target/test-environment/cargo` in this checkout.
This reuses downloads and keeps unchanged compiled dependencies fresh across runs.
The wrapper does not import the inherited Cargo home's configuration or credentials.
Anything a test writes there, including Cargo configuration or credentials, persists until that directory is removed.
Set `DOTFILES_TEST_CARGO_HOME` to another owned disposable directory when testing Cargo configuration or when a fresh cache is required.
Nested wrapper calls retain that path.
An unusable cache directory fails before the child starts; the wrapper does not fall back to the user's Cargo home.
Cargo's build-output location is unchanged.

The wrapper also sets `UV_CACHE_DIR` to the stable test-only directory
`target/test-environment/uv` in this checkout.
This lets `uvx` reuse pinned tool environments and package downloads while the
private HOME and other XDG state remain disposable.
The wrapper does not reuse the user's uv cache.
Anything a test writes to this cache persists until that directory is removed.
Set `DOTFILES_TEST_UV_CACHE_DIR` to another owned disposable directory when a
fresh cache is required; nested wrapper calls retain that path.
An unusable cache directory fails before the child starts.

### Command selection

For `bb`, `java`, `jj`, and `rg`, the wrapper preserves explicit real-tool overrides or resolves mise shims before changing HOME.
`DOTFILES_TEST_<TOOL>_REAL` takes precedence over `<TOOL>_REAL`.
The selected paths supply both the exported test overrides and temporary command symlinks under the private HOME.
Only those command names change; sibling executables in their installation directories do not enter PATH.
Children inherit the selections, can prepend their own fakes, and lose the temporary symlinks when HOME is cleaned up.
Failed mise resolution stops the run before a child starts.
Repository-local exclusions keep dependencies, notes, test caches, and editor sessions untracked even when private HOME hides global ignore rules.
The wrapper sets `FISH_UNIT_TESTS_RUNNING=1` so interactive Fish skips detached man-page completion generation.
Fish still loads its normal startup configuration.
This prevents its startup completion jobs from racing private-HOME cleanup.

Unselected commands such as Docker retain their incoming PATH selection.
Inside an agent sandbox, this keeps the Docker wrapper that configures the gateway's SSH identity and pinned host key:

```sh
dev/test-environment docker info
```

### Installed SDKs and test fixtures

An explicit `PI_PACKAGE_DIR` takes precedence.
Otherwise, the wrapper discovers the installed Pi SDK under the original HOME before replacing HOME.
Tests can read the SDK without loading personal settings or caches.
The wrapper resolves SDK directory symlinks before isolation, including explicit overrides.
This lets Node discover dependencies beside the source checkout.
For `dev/test --containers`, the runner also captures the validated host Pi installation revision before replacing HOME.
The runtime-image probe builds and checks that commit.
Missing or invalid revision metadata stops the runner before any tests;
repair the installation with `mise run pi-install`.

For Neovim config tests, the wrapper discovers installed plugins at `${XDG_DATA_HOME:-$HOME/.local/share}/nvim/lazy` before isolation.
It passes `DOTFILES_TEST_NVIM_PLUGINS`.
An explicit nonempty value takes precedence and survives nested wrappers.
The fixture copies plugins into temporary storage; Neovim never writes to the installed plugin tree.
For prerequisites and the test command, see the [Neovim config test guide](../tests/nvim/README.md).

The profile suite loads complete shell configurations and reads bindings from a private tmux server.
Its Glide cases import the complete TypeScript configuration with Node's native type stripping and replace browser APIs with fixtures.

See [testing and probes](README.md#testing-and-probes) for common prerequisites, socket permissions, and real-state exceptions.
For installed-Pi-specific test recipes, see the [Pi configuration guide](../config/pi-agent/README.md#testing).
