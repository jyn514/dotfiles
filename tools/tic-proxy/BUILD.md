# Pinned bundles and launcher cache

TicGit defaults on for new sessions; explicit `capabilities.tic: false` opts out.
Building does not launch a provider, change ordinary host `ti`, or modify project
capability settings. Linux disposable tests do not establish actual provider
composition or macOS support.

## Build and test

The native input is `native-revision`, an exact Git commit, not the checkout's
working tree. `build-local /path/to/native-repository` captures it with
`git archive` into a fresh private build context and passes a mandatory Cargo
path override for `ticgit`. Normal Pi acquires the pinned source from the public
`jyn514/ticgit` fork over HTTPS when needed; direct development builds can still
use a local checkout. Do not substitute crates.io's unmodified package: it lacks
the reviewed parser/native changes. Cargo.lock binds registry dependencies;
builds/tests use `--locked` and fail rather than updating it.

Run from the dotfiles root through `dev/test-environment`, selecting an owned
Cargo cache/toolchain where needed. Set `DOTFILES_TEST_CARGO_HOME` and put the
selected toolchain's bin directory on PATH; the wrapper preserves those choices.

```sh
dev/test-environment tools/tic-proxy/build-local /path/to/native-repository test
dev/test-environment tools/tic-proxy/build-local /path/to/native-repository build --bins
```

The builder produces host-native `ti` and `tic-broker`. Normal builds keep Cargo's
unoptimized dev profile but set `CARGO_PROFILE_DEV_DEBUG=0` for native, broker,
and client builds. Debug information adds substantial bytes to each verified
bundle without helping normal startup; omitting it reduces copying and
publication-time hashing without requiring a host `strip` tool.
Explicit release builds retain their existing profile. This builder change
invalidates the source key once, so an existing cache requires one cold rebuild;
subsequent launches reuse the smaller verified bundle.

A static Linux host client is reused only when ELF validation confirms the requested guest
architecture. Otherwise it separately builds the Linux client for
`x86_64-unknown-linux-musl` or `aarch64-unknown-linux-musl`; that standard Rust
target and corresponding linker must already be available. The builder does
not install toolchains. Select a
guest architecture explicitly with `--guest-platform linux/amd64` or
`--guest-platform linux/arm64`, before the repository argument. An independently
built static Linux client may instead be supplied with
`--guest-client /path/to/ti-proxy --guest-platform linux/amd64`. These options
never make a Darwin executable usable in Linux. The helper verifies ELF
architecture and rejects PT_INTERP, unsupported ABI, and Mach-O.

Build output remains in ignored `target/tic-proxy-build/`. The final
`staged bundle:` line identifies a content-addressed bundle:

```text
bundle-<manifest-sha256>/
  manifest.json
  native/ti
  native/ti.tic-proxy.json
  host/tic-broker
  guest/ti-proxy
```

`manifest.json` is the one bundle selection authority. Schema 2 records the
native revision, policy version, three fixed relative artifact paths and hashes,
guest platform, and a `build` identity. That identity contains `proxy_source`,
`native_revision`, `policy_version`, `wire_version`, `host_platform`, and
`guest_platform`. The source hash covers Cargo.toml, Cargo.lock, native-revision,
the builder and bundle validator, and Rust source paths/bytes. It does not use
mtime or checkout location. Source changes during a build cause failure. The
native sibling binding remains strict schema-1 JSON
`{native_revision, policy_version, sha256}`; the Rust broker checks its metadata
against launch authority before readiness without rereading native executable
contents, running a version command, or opening SQLite.

## Normal launcher resolution

Tic-enabled startup resolves the current source/native/policy/host/guest identity
before starting the per-launch broker. The cache layout is:

```text
~/.cache/codex-sandbox/tic/<source-key>/bundle-<manifest-sha256>/
```

A matching cache entry is selected by current build inputs and its small
manifest, with canonical paths, ownership, modes, regular-file/link protection,
and guest platform checked without hashing executable contents. A cache miss
invokes the ordinary pinned builder, fully verifies the returned bundle's bytes,
and copies it into the protected cache before any executable runs. Incoming
development bundles and cache publication retain full artifact/copy SHA-256
verification; ordinary warm resolution, installed-build checks, private client
staging, and broker readiness do not repeat it. A cache-root file lock serializes
resolution through publication; the complete source-key directory is renamed
into place only after copying and verification. Concurrent first launches
therefore reuse one result rather than observing an in-flight partial entry.
The builder separately holds a build-output file lock across its Cargo commands,
native binding, and bundle copy, including direct development builds. These
locks contain no process identifiers or current-build selection records. An old bundle cannot be selected
merely because its native pin matches: a changed proxy source or wire version
has a different source key. There is no global current-build record,
`installed.json`, absolute-path artifact record, or required manual installation.
The launcher derives absolute executable paths from the relative manifest.

A normal cold-cache launch needs no source flag or manual build. If there is no
explicit host source setting, it uses setup's existing exact-revision Git fetch
and private-stage/atomic-install primitive to acquire the public native fork over
HTTPS into `~/.cache/codex-sandbox/tic-native/<native-revision>/`. The existing
bundle-resolution lock covers source acquisition as well as build/publication.
Revision-specific source directories allow a pin update to acquire its new
commit without mutating or accidentally reusing an older checkout. Failed
fetches leave no accepted source checkout or bundle; an authored partial checkout
is rejected rather than repaired. Source caches must be canonical, launcher-owned,
not group/other writable, and outside guest-writable mounts. No credentials,
project-selected URL, or new version pin are introduced. A cached source can
serve later cold bundle builds offline, subject to Cargo/toolchain availability.

An existing host-owned `~/.config/codex-sandbox/tic-native-source` remains an
optional explicit local-source choice and is never rewritten by fetching. It
contains the absolute local native repository path and an optional final newline.
The regular single-link file must belong to the launcher user, have mode `0600`,
and be outside guest-writable mounts. It is machine configuration, not a project
capability option or artifact record. To deliberately select a local development
checkout instead of automatic fetching:

```sh
pi --set-tic-native-source /path/to/native-repository
```

Run that command on the host, not inside the agent container. The launcher checks
that the local repository contains the pinned commit, atomically creates or
updates only this known setting, removes the option from Pi's arguments, and
continues ordinary startup. Plain `pi` works without ever using this option;
no global TicGit installation is needed. Explicit local configuration does not
override a repository's opt-out. Invalid or stale explicit settings report their
error rather than silently selecting another source. No host setting is written
by fetching, building, or testing.

Fetch, build, unsupported repository, inspection, and readiness failures use
the same warn-and-disable behavior, even with explicit `tic: true`; unrelated
metadata/provider rejection
remains fatal. No failed startup projects a TicGit endpoint, token, client mount,
or network attachment. The fixed guest `ti` guard reports unavailable and
never searches PATH for native TicGit. Every launch binds a private read-only
copy at `/libexec/sandbox-wrappers/ti`, independently of accepted-image age and
Tic artifact availability; explicit opt-out needs no Tic build or cache lookup.
The existing launch-owned skills scratch holds the copy outside guest-writable
bind sources and owns its cleanup. Unavailable launches also clear stale
image-baked endpoint/token values. A ready broker's later request failures
still fail closed without fallback or replay. A matching warm cache does not
need the source setting or native source access.

Development bundles use the same `resolve_bundle(..., local_bundle=...)`
validation and staging path as ordinary builder output. The small optional
`install-bundle BUNDLE --prefix CACHE_ROOT` CLI uses the same copy validator;
it writes only the relative bundle, not a current-build selector. It is not a
prerequisite for ordinary startup.

The cache must be outside every actual guest-writable source, including resolved
workspace aliases and separately mounted skills. The launcher rejects a cache
root that overlaps those sources, traverses a symlink alias, or has unsafe owner
or write permissions. Bundle directories and executable snapshots are `0555`,
manifests `0444`; symlinks, hardlinked protected files, unexpected entries,
partial keys, and mismatched manifests fail without repair or adoption. Changed
artifact bytes are rejected during build/publication, not repeatedly on warm
startup. Writable build output, including output under a mounted dotfiles
checkout, is never executed in place. The trusted host manually rewriting an
already-published immutable cache file is unsupported, not a guest-tampering
threat that runtime hashing promises to detect. Actual provider mount-source
accounting, not hashes or file modes against the host owner, protects the guest
boundary.

Python bundle/cache and mocked-launcher tests are discovered by `dev/test`.
The native Cargo suite is opt-in: set
`TIC_PROXY_NATIVE_REPOSITORY=/path/to/native-repository` and run `dev/test` or
focused `dev/pytest tools/tic-proxy/tests`. Without that local fork input, the
suite reports an explicit skip, not native acceptance. The launcher integration
suite accepts `TIC_LAUNCHER_TEST_BUNDLE` for real cached-artifact/local-transport
checks; additionally setting `TIC_LAUNCHER_TEST_NATIVE_REPOSITORY` exercises real
normal cold-cache provisioning from a source setting in disposable HOME. These
checks start only test-owned local brokers/relays, not actual providers.

## Disposable normal-Pi acceptance

Before launching ordinary `pi` in an authorized standalone disposable fixture, check its canonical repository authority on the host:

```sh
cd /path/to/disposable-fixture
pwd -P
git rev-parse --show-toplevel
jj root
git rev-parse --path-format=absolute --git-common-dir
```

For a conventional standalone fixture, the first three paths must identify the same root and the common directory must be that root's `.git`.
Any checker must also belong to that root.
Check the roots again inside the guest with the admitted pure query `jj root`, before any `ti` command; stop on a mismatch.
A nested Git-only fixture can make normal Pi select an ancestor JJ repository's workspace and accepted capability settings.
Prepare a standalone co-located JJ root on the host before launching such a fixture, rather than changing global root selection or guest proxy policy.
Check root authority before diagnosing an unavailable client or empty endpoint/token as a native build failure.
Then use ordinary `pi`, not a custom runner. The default source acquisition needs no source option.
These fixture prerequisites do not require JJ or a separate Pi frontend for ordinary host-native Git-linked worktree checks.

To attribute an actual provider run to a pinned build, inspect the selected protected cache manifest's build identity, platforms and client hash.
Expected fixture metadata or a source-equivalent local bundle does not attest the selected host artifact.
Use immutable bundle snapshots for exact-artifact replays: writable Cargo debug outputs can change independently and are not that bundle's authority.
Preserve original smoke reports and ticket IDs; do not rerun creation to manufacture warm-launch evidence or blindly retry an uncertain outcome.

### Repeatable Linux workflow

This functional smoke test lives under `tests/`; it is not another Pi frontend
or a lifecycle/concurrency proof.
Default `dev/test` discovery runs their offline safety tests. For a retained
local native/client/broker run, select an immutable pinned build bundle:

```sh
TIC_LINUX_COMPONENT_BUNDLE=/absolute/path/to/bundle-MANIFEST_HASH \
  dev/pytest -q -s tools/tic-proxy/tests/linux_acceptance_test.py
```

That opt-in creates only test-owned local brokers and repositories under
`target/tic-acceptance/components/`. It does **not** establish actual host Pi or
provider acceptance. A skipped component case is not a pass.

For Linux host/guest functional smoke, run the following **on the Linux host**, from the
dotfiles checkout in an interactive terminal. This is an explicit exception to
HOME isolation: ordinary Pi needs its installed configuration and credentials.
Do not wrap this command in `dev/test-environment`, pipe its streams, or run it
inside a guest. It makes live model requests and may incur model cost.
The script uses the ordinary launcher's bundle resolver and runtime platform
provider: a valid warm cache needs no source/network access, while a cold cache
may fetch the pinned public source and build/publish the bundle normally. It
announces selection before that work and retains the selected manifest in its
receipt. No source setting or profile change is needed.

```sh
python3 tools/tic-proxy/tests/linux_acceptance.py --actual-linux-host
```

For an exact-artifact replay, optional `--bundle /absolute/path/to/bundle` bypasses
automatic resolution but still requires an actual protected launcher-cache bundle;
do not substitute writable builder output or a guessed source-equivalent bundle.

The script creates a **new** standalone main JJ/Git repository and a genuine Git
linked worktree, with fixture-local synthetic identity and namespace. It invokes
this checkout's ordinary `bin/pi` twice, preserving the interactive terminal and
using an `@prompt` file. In each **new TEST Pi**, let the ordinary guest bash tool
run the supplied checker once; after it reports PASS, exit only that TEST Pi
normally. No separate frontend is launched from the linked worktree.
The first launch checks host creation → guest read and guest comment → host reads
and history from both worktrees. A file handshake starts independent host and
guest writer loops; every successful ticket must have distinct identity, content,
and creation history in both worktrees and the shared SQLite store. After that
TEST Pi exits, host native use must still work. The second launch uses a fresh
fixture with an unsupported local Git include: the guest guard must report
unavailable, ordinary tools must work, and no endpoint/token or store may appear.

Receipts retain the selected protected manifest, actual guest client hash, CLI
results, Pi exit status, and SQLite checks. Reports are kept on failure, too.
There is no PID sampling or timing assertion: concurrent writer dispatch does
**not** prove interleaving or simultaneous SQLite commits, and Pi exit does not
prove broker/native cleanup or in-flight cancellation. Precise lifecycle edge
cases remain in the existing automated lifetime suite.

Results remain under `target/tic-acceptance/linux/run-…/`. On failure, stop and
inspect the retained reports: mutations are never retried, a checker claim
prevents replay, and no store or sidecar is reset or deleted. Start a new run only
after inspecting an uncertain outcome. The workflow does not reset real
profiles/stores, reuse old fixtures or user Pi sessions, or stop shared VMs.
Retained test fixtures can be removed manually after their owning TEST Pi exits. VM-stopped
host use, macOS composition, and other specification checks are not established
by this bounded workflow, even when its receipt says PASS.

## Dependency scope

Cargo remains this subsystem's package manager. The native parser dependency is
the exact archived fork commit, fetched automatically or supplied locally.
The implementation adds no dependency framework, OS confinement, SQLite broker, external runtime,
or native Ticket API. The cache is an artifact snapshot, not a shared broker:
per-launch Rust broker ownership, lifetime pipe, provider cleanup, relay, and
Python TCP bridge are unchanged.
