# Try rootless Docker in Lima

This opt-in prototype uses Docker's host API and BuildKit in a separate VM.
Podman remains the default. Existing nerdctl/Lima and Podman VMs, images, and
sessions are not migrated.

From the dotfiles checkout on Apple Silicon macOS:

```sh
brew install lima docker docker-buildx
python3 tools/codex-sandbox/lima/docker_host.py setup
CODEX_SANDBOX_RUNTIME=lima-docker codex-sandbox --help
CODEX_SANDBOX_RUNTIME=lima-docker pi
```

Setup creates `sandbox-host-docker` with 4 CPUs, 4 GiB RAM, and a 64 GiB disk.
It shares your home directory with the VM; containers retain the launcher's
narrow mounts. Docker's real Homebrew executable is recorded explicitly, so
the existing `docker` → Podman alias need not change.

State defaults to `~/.local/state/codex-sandbox-docker`. For another instance,
pass `--state DIRECTORY` before `setup` and `--instance sandbox-host-docker-NAME`
after it, then set `CODEX_SANDBOX_DOCKER_STATE=DIRECTORY` for launches and builders.
Explicit `--share-read PATH` / `--share-write PATH` options replace home sharing;
setup adds its private scratch share automatically.

The existing [Keychain credential](credentials.md) is reused and cached once per
boot of this VM. If it has not been imported, run the documented `import-podman`
command first. To prepare or invalidate this VM's cache explicitly:

```sh
python3 tools/codex-sandbox/sandbox_credentials.py --provider lima-docker prepare
python3 tools/codex-sandbox/sandbox_credentials.py --provider lima-docker invalidate
```

Stop or resume this VM with:

```sh
python3 tools/codex-sandbox/lima/docker_host.py stop
python3 tools/codex-sandbox/lima/docker_host.py start
```

Launches verify an already running VM; they do not install or repair policy.
Setup snapshots its installation source. A changed prototype policy requires
a new instance and state directory rather than silently rewriting a ready VM.
Omit `CODEX_SANDBOX_RUNTIME=lima-docker` to return to the default backend.

## Prototype boundaries

Docker Engine 29.8.0, containerd 2.3.5, Buildx 0.37.0, and slirp4netns 1.3.5 are
pinned in setup. Docker packages come from Docker's signed Ubuntu repository;
the signing key and Ubuntu image have pinned SHA-256 digests. Rootful Docker's
service and socket are masked before package installation.

The rootless service installs bridge filtering on every activation before
systemd reports it ready. Agent traffic rejects private destinations and IPv6;
internal relay links cannot route between sessions. Host-facing relays have
separate egress networks. Docker restarts stop workloads and reinstall filtering;
live restore and workload restart policies are disabled.

Image builds use the forwarded Docker socket and preserve interactive BuildKit
progress. Returned references retain both tag and digest because BuildKit needs
the tag to resolve a local base; execution uses the verified configuration ID
with pulling disabled. Custom image entrypoints survive credential injection.

Monitor waits use host Docker clients. Each host-routed proxy request uses a
temporary container with only the proxy socket volume, allowing cancellation
through Docker's ordinary container API; Docker has no individual exec-kill API.
This adds container startup cost to host-routed commands.

This is not yet a default-backend recommendation. Long-running interactive Pi,
20 simultaneous sessions, raw-packet attacks, and optional Agent Podman/Zulip
integration still need Docker-specific validation.

## Disposable validation

Use an otherwise idle test VM: the policy test deliberately restarts Docker
and injects a failed policy activation. Both tests own their temporary resources;
the caller owns VM teardown. The launcher fixture uses dummy credentials.

```sh
mkdir -p /private/tmp/docker-sandbox-test/work
python3 tools/codex-sandbox/lima/docker_host.py \
  --state /private/tmp/docker-sandbox-test/state setup \
  --instance sandbox-host-docker-test \
  --share-read "$PWD" --share-write /private/tmp/docker-sandbox-test/work
python3 tools/codex-sandbox/tests/lima_launcher_integration.py \
  --provider lima-docker --state /private/tmp/docker-sandbox-test/state \
  --work /private/tmp/docker-sandbox-test/work
CODEX_SANDBOX_RUNTIME=lima-docker \
CODEX_SANDBOX_DOCKER_STATE=/private/tmp/docker-sandbox-test/state \
  .agents/sandbox/base-image
```

Pass that last command's image reference to the restart test:

```sh
python3 tools/codex-sandbox/tests/docker_policy_integration.py \
  --state /private/tmp/docker-sandbox-test/state \
  --disposable-instance sandbox-host-docker-test --image IMAGE_REFERENCE
python3 tools/codex-sandbox/tests/docker_monitor_integration.py \
  --state /private/tmp/docker-sandbox-test/state --image IMAGE_REFERENCE
limactl delete --force sandbox-host-docker-test
```
