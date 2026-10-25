# Pinned bundles and launcher cache

TicGit defaults on for new sessions; explicit `capabilities.tic: false` opts out.
Building does not launch a provider, change ordinary host `ti`, or modify project
capability settings. Linux disposable tests do not establish actual provider
composition or macOS support.

## Build and test

The native input is `native-revision`, an exact Git commit, not the checkout's
working tree. `build-local /path/to/native-repository` captures it with
`git archive` into a fresh private build context and passes a mandatory Cargo
path override for `ticgit`. The unpublished fork has no assumed remote or release
source. Do not substitute crates.io's unmodified package: it lacks the reviewed
parser/native changes. Cargo.lock binds registry dependencies; builds/tests use
`--locked` and fail rather than updating it.

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

Cold-cache source selection reads one host-owned file,
`~/.config/codex-sandbox/tic-native-source`, containing the absolute local native
repository path and an optional final newline. The regular single-link file must
belong to the launcher user, have mode `0600`, and be outside guest-writable
mounts. It is machine configuration, not a project capability option or artifact
record. Configure the approved local checkout once while starting normal Pi:

```sh
pi --set-tic-native-source /path/to/native-repository
```

Run that command on the host, not inside the agent container. The launcher checks
that the local repository contains the pinned commit, atomically creates or
updates only this known setting, removes the option from Pi's arguments, and
continues ordinary startup. Later launches use plain `pi`; no per-launch source
flag or global TicGit installation is needed. Configuration does not override a
repository's explicit opt-out. No host setting is written by building or testing.

Without that setting, ordinary cold-cache Tic startup warns about the missing
source and Pi starts with TicGit unavailable for that session, rather than
scanning sibling repositories or downloading an unknown fork. Build, unsupported
repository, inspection, and readiness failures use the same warn-and-disable
behavior, even with explicit `tic: true`; unrelated metadata/provider rejection
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
Then use ordinary `pi`, with the one-time host source option above only if needed, not a custom runner.
These fixture prerequisites do not require JJ or a separate Pi frontend for ordinary host-native Git-linked worktree checks.

To attribute an actual provider run to a pinned build, inspect the selected protected cache manifest's build identity, platforms and client hash.
Expected fixture metadata or a source-equivalent local bundle does not attest the selected host artifact.
Use immutable bundle snapshots for exact-artifact replays: writable Cargo debug outputs can change independently and are not that bundle's authority.
Preserve original smoke reports and ticket IDs; do not rerun creation to manufacture warm-launch evidence or blindly retry an uncertain outcome.

## Dependency scope

Cargo remains this subsystem's package manager. The native parser dependency is
the exact archived local fork; publication is not required. The implementation
adds no dependency framework, OS confinement, SQLite broker, external runtime,
or native Ticket API. The cache is an artifact snapshot, not a shared broker:
per-launch Rust broker ownership, lifetime pipe, provider cleanup, relay, and
Python TCP bridge are unchanged.
