# Local build and explicit installation recipe

The capability remains default-off. These commands do not launch a provider,
change ordinary host `ti`, or grant guest writable access to installed artifacts.
Linux execution evidence is local/disposable; neither Linux provider composition
nor macOS support is accepted solely by these tests.

## Build and test

The native input is `native-revision`, an exact Git commit, not the checkout's
working tree. `build-local /path/to/ticgit` captures it with `git archive` into a
fresh private build context and passes a mandatory Cargo path override for
`ticgit`. Do not build against crates.io's unmodified package: it lacks the
reviewed parser/native changes. No native source copy or machine path is
committed. Cargo.lock binds registry dependencies; every build/test uses
`--locked` and fails rather than updating it. Dependency changes require explicit
lockfile regeneration/review separate from checking or testing.

Run from the dotfiles root through `dev/test-environment`, selecting an owned
Cargo cache/toolchain where needed. Set `DOTFILES_TEST_CARGO_HOME` and put the
selected toolchain's bin directory on PATH; the wrapper preserves those choices.

```
dev/test-environment tools/tic-proxy/build-local /path/to/ticgit test
dev/test-environment tools/tic-proxy/build-local /path/to/ticgit build --bins
```

The native build has a sibling `<executable>.tic-proxy.json`: strict JSON
`{native_revision, policy_version, sha256}`. Native executable and manifest are
trusted build artifacts, never agent-writable (including mount aliases). The
broker checks this binding and the launch configuration hash before readiness.
It never runs a version command or opens SQLite for readiness. Native fixtures
use `TIC_PROXY_TEST_NATIVE` (set automatically by the helper).

Build output remains in ignored `target/tic-proxy-build/`. The final
`staged bundle:` line identifies a content-addressed bundle with relative paths:

```
manifest.json
native/ti
native/ti.tic-proxy.json
host/tic-broker
guest/ti-proxy
```

`manifest.json` has `version`, `native_revision`, `policy_version`, and
`native`, `broker`, `client` objects. Each artifact object has `path` and `sha256`;
`client` additionally has `platform` (`linux/amd64` or `linux/arm64`). All paths
are fixed relative paths within the bundle. The bundle directory name hashes
the complete manifest, binding all three artifacts. This writable build stage is
**not** an installed trust root and must never be used directly by a launcher.

On Linux, the default client is the host-built binary only when it is a static
64-bit Linux ELF of supported architecture. A dynamically linked host build is
not assumed compatible with the provider image. On Darwin (and when using a
separately built Linux client), supply `--guest-client /path/to/ti-proxy
--guest-platform linux/amd64` before the repository argument. The helper checks
ELF architecture and rejects PT_INTERP, unsupported ABI, and Mach-O. It does not
pretend that a Darwin host executable runs in a Linux guest. Reproduce the same
pinned archive and Cargo.lock when cross-building that client; its reviewed
provenance is still a human installation prerequisite, not established by an ELF
header or caller-supplied hash alone.

Python build/installer tests are discovered by `dev/test`. The full native Cargo
suite is a documented opt-in under that same discovery route: set
`TIC_PROXY_NATIVE_REPOSITORY=/path/to/ticgit` and run `dev/test` or focused
`dev/pytest tools/tic-proxy/tests`. Without the local fork input that test reports
an explicit skip, not a native acceptance pass. Direct focused Cargo testing is
also supported through `build-local ... test`.

## Installation (requires separate review/authorization)

Build and startup never install host artifacts. Finish all intended native,
broker, client, and repository-preflight changes, then rebuild and review the
resulting bundle before considering installation. An earlier staged bundle does
not acquire later fixes merely because it has the same native revision. Building
or passing tests is not authorization to install or enable the capability.

The launcher's fixed installation root is `~/.local/share/tic-proxy`; it reads a
regular `installed.json` there, not a symlink or the writable build-stage
manifest. Before an authorized installation:

- Ensure the root's parent (`~/.local/share`) already exists. It and any existing
  installation root must be owned by the installing user and not group/world
  writable. Use canonical host paths: symlink aliases in the root path are
  rejected. The helper creates an absent root with mode `0700`.
- Review the complete provider mount layout and establish that the installation
  is **outside every guest-writable mount alias**, including separately mounted
  skills or other writable host sources. This acceptance is external to the
  helper; a pathname check cannot discover every alias or provider projection.
- Identify existing writable mount sources to pass as exclusion roots. Each
  `--guest-writable-root` is resolved and rejects overlap in either direction
  with the installation root. These checks catch known conflicts; omitting an
  alias from the arguments does not establish that it is safe.

After that review and separate authorization, run from the dotfiles root,
substituting the freshly reviewed bundle and actual writable mount sources:

```sh
tools/tic-proxy/install-bundle /path/to/reviewed/bundle-MANIFEST_SHA256 \
  --prefix "$HOME/.local/share/tic-proxy" \
  --guest-writable-root /path/to/accepted/workspace \
  --guest-writable-root /path/to/writable/skills
```

Repeat the exclusion option for other known writable sources; do not use the
example paths literally. The helper performs no network access or publication
and does not invoke native TicGit or start a provider.

`--prefix` names the installation **root**, not the artifact directory. A
successful installation has this layout:

```text
~/.local/share/tic-proxy/
  installed.json
  bundle-<manifest-sha256>/
    manifest.json
    native/ti
    native/ti.tic-proxy.json
    host/tic-broker
    guest/ti-proxy
```

The helper verifies the bundle directory name against the SHA-256 of its
manifest bytes, checks the fixed tree and all artifact hashes, validates the
static Linux guest client's platform, and checks the native binding against
`native-revision` and policy version 1. Symlinked artifact directories and files
are rejected. It copies into a private stage, rechecks the artifacts and native
binding, then publishes the content-addressed directory and a complete regular
`installed.json` without replacing an existing installed manifest. Artifact
executables and directories within that bundle are `0555`; manifests are
`0444`. These are read-only installer snapshots, not OS-enforced immutability
against the owning host user.

The adapter-facing `installed.json` contains `version`, `native_revision`,
`policy_version`, `broker_executable`, `broker_sha256`, `native_executable`,
`native_sha256`, `guest_client_executable`, `guest_client_sha256`, and
`guest_client_platform`. Absolute executable paths are derived from the canonical
root and content-addressed directory. The launcher consumes this file, while
the preserved relative `manifest.json` records the reviewed bundle inputs.

Re-running the identical installation verifies the existing record, artifact
bytes, ownership, modes, and link counts without rewriting them. The helper
rejects a different build at the fixed root, altered artifacts or manifests,
unexpected bundle entries, and incomplete destinations. It does not overwrite,
repair, or take ownership of mismatched content. An intentional version change
needs a separately reviewed installation change, not an automatic upgrade.

File modes alone cannot protect an installation reachable through a writable
mount or alias. Installed-source protection and actual provider projection still
require their own acceptance. Installation neither changes ordinary host `ti`
nor enables `capabilities.tic`, and it does not establish Linux provider or macOS
support.

## Dependency scope

Cargo is this subsystem's package manager, as for the existing Rust proxy. The
native parser dependency is the exact archived local fork (no publication).
Serde/JSON provide strict typed envelopes; Clap is the native parser API; anyhow
carries internal failures; tempfile owns request-private state; nix 0.29 supplies
portable Unix descriptor flags/poll/signals; sha2 verifies installed executable
bytes. These versions already occur in the native lock/cache or existing JJ
proxy. Low-level gix-config/discover/pack versions exactly match the native
0.81 dependency family for preflight without repository/configuration opens.
No OS confinement, SQLite broker, external runtime, or generic execution library
is added. The lockfile, full native commit, installed hashes, and behavioral
tests bind this implementation; no claim is made that a cache or version pin
alone proves dependency security or release provenance.
