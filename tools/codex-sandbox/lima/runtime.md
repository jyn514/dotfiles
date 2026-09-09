# Exercise outer runtime operations

The image helper and runtime contracts support Podman and the provisioned Lima
store. Podman remains the default; [opt-in Lima launches](launch.md) use the same
runtime as their image builders. Full daily-use validation and rollback precede
the default switch.
The [rootless Docker prototype](docker.md) selects `--provider lima-docker` and
`CODEX_SANDBOX_DOCKER_STATE`; its host API accepts build contexts outside VM shares.
It returns local `repo:tag@sha256:HASH` references and uses a separate image store.
Docker startup [composes native Bake targets](docker.md), sharing one
progress renderer across the base, agent, and proxy targets.

## Deferred integration prototype

The local jj bookmark `lima-deferred-prototype` (`8d9bfb6b`, based on `1cff23d0`)
preserves builder migration, per-agent tmpfs credential copies, relay CNI setup,
volume initialization, and their tests. The launcher now uses the builder, relay,
and volume operations with ownership-aware cleanup; per-agent credential copies
remain deferred because the entrypoint can read the boot cache directly. Inspect with
`jj show lima-deferred-prototype` and restore selected files or hunks, then retest.

The last acknowledgement/volume ownership fixes in that checkpoint are untested.
Credential copies need a lost-acknowledgement cleanup test; volume callers must
prove ownership before cleanup so a creation collision cannot delete another
creator's volume. Existing network, image, boot-cache, and recorded-runtime
checks remain active because they protect established boundaries.

## Image helper

After [explicit host setup](host-setup.md), build or resolve images in that store:

```sh
tools/codex-sandbox/sandbox-image --provider lima build \
  --tag localhost/example:test --file ./Dockerfile .
tools/codex-sandbox/sandbox-image --provider lima resolve localhost/example:test
```

Use `--state DIRECTORY` before the operation for a separately provisioned host.
`--provider podman` selects the existing host `docker` entrypoint. The helper
defaults to `CODEX_SANDBOX_RUNTIME`, or Podman when unset;
`CODEX_SANDBOX_LIMA_STATE` selects its host-state directory.
No operation starts a VM, changes the launcher's provider,
transfers images between stores, or silently pulls a missing image during
resolution. BuildKit may fetch Dockerfile bases that are not local.

Successful stdout contains exactly one local immutable reference followed by a
newline. Progress and diagnostics go to stderr; a failed producer exits nonzero.
`build` accepts repeated `--build-arg KEY=VALUE` and an optional `--target STAGE`.
The Dockerfile and context must be visible through verified Lima shares.
`build --if-missing` reuses a content-keyed image. Missing images trigger a build;
malformed native identity remains an error. Dotfiles' base, Jujutsu, Zulip, and
authentication proxy builders use this helper through `bin/sandbox-image` or
its repository path, preserving their content-based cache keys.

Podman returns a configuration digest. Lima returns a registered
`localhost/codex-sandbox:sha256-HASH@sha256:HASH` reference, with the native
manifest or index digest. These values are provider-specific; do not pass a
Podman configuration ID to nerdctl or assume a reference belongs to both stores.

BuildKit 0.31.2 resolves a canonical `FROM` through its tag before checking the
digest. When the canonical reference and its tag already exist, the helper checks
their native content, config, and root filesystem identities and reuses them
without writing tags.
Otherwise it snapshots the source under a private registration, verifies it,
and publishes canonical and content-derived tag registrations without overwriting
existing names. Conflicting identities are errors. A bare registered `repo@digest`
runs locally but can still trigger a registry request in `FROM`. The returned reference supports
both uses, and workload execution specifies `--pull=never`.

Successful container creation omits nerdctl's existing-volume notice for named
mounts. Other warnings and all failed-creation diagnostics remain visible.
An agent-wait error is lost supervision, not a completed agent; both backends
terminate the agent in that case. Lima bounds its fallback removal to ten seconds.

## Runtime contract tests

The monitor fixture creates only disposable containers from an already local
image containing `sleep`. It checks agent exit, proxy failure, deliberate
cancellation, lost supervision, and SSH transport failure, including wait cleanup:

```sh
python3 tools/codex-sandbox/tests/lima_monitor_integration.py --image LOCAL_IMAGE
```

The unit suite checks alias disagreement, registration races, snapshot ancestry,
live CNI allocation ownership, private environment staging, missing VM/policy,
and transport exit statuses:

```sh
python3 tools/codex-sandbox/tests/sandbox_runtime_test.py
```

For a running provisioned host, check launch-scoped verification reuse across
real child processes and compare full versus reused check timings. The fixture
also checks an owned batch of bind sources and removes its temporary files:

```sh
python3 tools/codex-sandbox/tests/lima_verification_integration.py --state "$fixture_state"
```

For an already provisioned disposable instance with a local Alpine-compatible
base, run:

```sh
python3 tools/codex-sandbox/tests/runtime_integration.py \
  --provider lima --state "$fixture_state" --base "$local_base"
python3 tools/codex-sandbox/tests/runtime_integration.py \
  --provider podman --base alpine:3.22
```

The Podman test requires its existing `codex-public-only` network. Both tests
build an owned image, move its mutable tag, verify the original image still runs,
correlate live network membership, preserve literal argv and stdin/EOF, and check
exec failure, daemon-side cancellation, and host SIGTERM cleanup. They use dummy
environment data and remove their owned containers and image registrations.

`python3 tools/codex-sandbox/tests/lima_host_integration.py` provisions its own VM
and runs these contracts before and after reboot alongside the network/share
gates. `dev/test --lima` runs that gate after repository checks; it leaves the
unrelated `--containers` suites on their existing runtime.

The [launcher fixture](launch.md#exercise-an-owned-host) covers PTY startup,
shared proxies, dummy boot credentials, and host editing. Ctrl-C, launcher build
interruption, VM loss during a session, and configured integrations remain
full-session gates.

Two native CLI behaviors need explicit handling. Nerdctl copies image-directory
ownership onto empty volumes, so proxy-volume initialization leaves a marker to
preserve the caller's UID. Containerd can observe stdin EOF before registering
its closer; host routing waits for a native exec PID before sending input and
reconciles that exec on cancellation. Inspection commands use closed stdin so
SSH cannot consume the request itself.

## Shared-session ownership

New publications use session schema 2 and record the outer runtime in shared
state. Lima ownership includes the host-state locator, instance, generation,
hardware identity, namespace, and network digest. Schema 1 is explicitly Podman;
schema 2 without an owner is rejected.

The repository coordination lock remains shared across providers. A launcher
cannot reuse another runtime's session. Routing, monitoring, and cleanup resolve
the recorded owner, regardless of the current default; a missing or changed Lima
owner stops recovery without discarding its metadata. Reset removes metadata only
after successful engine listings confirm the recorded containers and volumes are
absent. Local command fallback preserves stale records for the next recovery.

Proxy publication, reuse, and command routing verify repository/command labels
and native image identity. Displayed image names alone do not establish identity.
Launcher cleanup also checks the pinned VM identity and relay/volume creator
labels before deletion. Failed cleanup retains recovery metadata.

`tests/session_owner_integration.py --provider podman --base alpine:3.22` checks
native proxy identity and recorded-owner cleanup using owned resources. The
disposable Lima host gate runs the same checks before and after reboot.
