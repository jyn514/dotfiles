# Exercise outer runtime operations

The image helper and runtime contracts support Podman and the provisioned Lima
store. Ordinary sandbox launches and existing repository builders still use
Podman. Lima sessions remain gated on runtime-bound shared state, credential
provisioning, trusted relay networks, and full launcher recovery tests.

## Image helper

After [explicit host setup](host-setup.md), build or resolve images in that store:

```sh
tools/codex-sandbox/sandbox-image --provider lima build \
  --tag localhost/example:test --file ./Dockerfile .
tools/codex-sandbox/sandbox-image --provider lima resolve localhost/example:test
```

Use `--state DIRECTORY` before the operation for a separately provisioned host.
`--provider podman` selects the existing host `docker` entrypoint; it is the
helper's default. No operation starts a VM, changes the launcher's provider,
transfers images between stores, or silently pulls a missing image during
resolution. BuildKit may fetch Dockerfile bases that are not local.

Successful stdout contains exactly one local immutable reference followed by a
newline. Progress and diagnostics go to stderr; a failed producer exits nonzero.
`build` accepts repeated `--build-arg KEY=VALUE` and an optional `--target STAGE`.
The Dockerfile and context must be visible through verified Lima shares.

Podman returns a configuration digest. Lima returns a registered
`localhost/codex-sandbox:sha256-HASH@sha256:HASH` reference, with the native
manifest or index digest. These values are provider-specific; do not pass a
Podman configuration ID to nerdctl or assume a reference belongs to both stores.

BuildKit 0.31.2 resolves a canonical `FROM` through its tag before checking the
digest. The helper snapshots the source under a private registration, verifies it,
and publishes canonical and content-derived tag registrations without overwriting
existing names. A bare registered `repo@digest` runs locally but
can still trigger a registry request in `FROM`. The returned reference supports
both uses, and workload execution specifies `--pull=never`.

## Runtime contract tests

The unit suite checks alias disagreement, registration races, snapshot ancestry,
live CNI allocation ownership, private environment staging, missing VM/policy,
and transport exit statuses:

```sh
python3 tools/codex-sandbox/tests/sandbox_runtime_test.py
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

These tests do not establish full-session equivalence: PTY/Ctrl-C behavior,
launcher build interruption, VM loss during a session, shared-service reuse,
credentials, host editor, and Agent Podman relays remain later gates.

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
This ownership preparation does not enable Lima launches or change image builders.

`tests/session_owner_integration.py --provider podman --base alpine:3.22` checks
native proxy identity and recorded-owner cleanup using owned resources. The
disposable Lima host gate runs the same checks before and after reboot.
