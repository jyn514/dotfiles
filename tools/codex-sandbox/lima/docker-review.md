# Lima-Docker review

Reviewed revision `b4930191` on 2026-09-10. The backend is viable as an opt-in
prototype; simplify process ownership before further startup optimization.
This review does not establish full Podman parity.

## Cancellation and abandoned orchestration

`Docker.bake()` always starts a new session, even inside `run_builder()`.
A disposable local-process probe confirmed that its child survives cancellation
of the enclosing builder. The probe killed its owned survivor. Ordinary Pi
startup bypasses Bake, so this is not evidence that current Pi cancellation leaks.

`sandbox_build.BuildBatch` has only test callers. Commit `33912087` restored
executable `base-image` and `image-command` builders, but retained the alternate
Bake contract and supervisor. Remove that unused path rather than repairing it.
Preserve coverage for nested build cancellation, output-lock waiters, failed
wrappers leaving children, and concurrent peer cleanup on the active API.
Single and concurrent builder runners still duplicate lifecycle ownership;
consolidation is a separate candidate, not a prerequisite for deleting Bake.

## Podman compatibility

- **Wait timeout:** a controlled subprocess probe showed inherited `Docker.wait()`
  receives `Docker.run()`'s 30-second timeout; Podman waits indefinitely.
  The interactive monitor uses `Popen` directly, so this is not a session limit.
- **Local images:** the same metadata containing a valid config ID but no
  `RepoDigests` is accepted by Podman and rejected by `Docker.inspect_image()`.
  BuildKit needs a tag plus digest for a local build base; enforce that requirement
  at base selection rather than during every inspection. The documented local-ID
  contract currently depends on the image also having a repository digest.
- **Routed commands:** `Docker.forward_proxy()` creates and removes a container
  per request; Podman uses `exec`. This adds latency but gives each request a
  cancellable container lifetime. Plain Docker `exec` would lose that guarantee.
  Measure complete routed commands before choosing another transport.

The first two differences were reproduced without a VM. The forwarding difference
was established by reading both implementations; no comparative timing was taken
for this review. Long-running Pi, twenty-session load, and optional Agent
Podman/Zulip parity remain validation gates in [the backend guide](docker.md).
Policy updates also require a fresh VM and state directory.

## Ownership and existing tools

`Docker` inherits through `VMRuntime(Podman)`, allowing command defaults to leak
across backends, as the wait timeout demonstrates. `Docker.argv()` also verifies
VM/service state and selects recovery authority from command tokens. Prefer
explicit operation boundaries and one build-lifecycle owner over a new generic
backend framework.

The small standard-library Unix-socket HTTP reader in `lima/docker_api.py` is a
reasonable metadata adapter, not a Docker SDK replacement. Keep it narrow.
The nftables implementation owns sandbox isolation policy while delegating
compilation and execution to nftables; deleting it requires equivalent isolation.

The `builder-bin/docker` adapter is a partial CLI compatibility layer. Prefer the
existing `sandbox-image` build/resolve interface for owned builders rather than
expanding that parser. Bake orchestration delegates HCL parsing to Buildx, but
duplicates target composition and process supervision for an unused launch path.
