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

Setup copies host Buildx v0.37.0 into private state. Builds verify its SHA-256 and
invoke it directly with the recorded Docker socket and private builder settings;
Homebrew upgrades and plugin discovery cannot replace it. For a VM created before
host Buildx pinning, run this once from dotfiles (no VM restart):

```sh
python3 tools/codex-sandbox/lima/docker_host.py pin-buildx
```

Use the same command to repair a missing or changed copy, after installing the
supported Buildx version; add `--state DIRECTORY` before `pin-buildx` for a
non-default VM. An unavailable or altered pinned binary blocks builds rather
than falling back to another plugin.

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

After sessions have exited, recover their shared proxies with
`python3 tools/codex-sandbox/sandbox-proxies.py reset --repo /path/to/repository`
from the dotfiles checkout. Cleanup verifies the
recorded VM, socket, and rootless engine identity even when installed policy is
damaged; it cannot launch workloads or repair the firewall. An unavailable or
replaced engine leaves recovery metadata intact.

## Prototype boundaries

Docker Engine 29.8.0, containerd 2.3.5, Buildx 0.37.0, and slirp4netns 1.3.5 are
pinned in setup, along with Ubuntu nftables 1.0.9-1ubuntu0.1.
Docker packages come from Docker's signed Ubuntu repository;
the signing key and Ubuntu image have pinned SHA-256 digests. Rootful Docker's
service and socket are masked before package installation.

New VMs use native nftables tables for sandbox filtering; Docker retains its
iptables backend for networking and NAT. Existing VMs keep their pinned policy.
Use a new instance and state directory to adopt nftables.

The rootless service installs filtering atomically on every activation before
systemd reports it ready. Agent traffic rejects private destinations and IPv6;
internal relay links cannot route between sessions. Host-facing relays have
separate egress networks. Docker restarts stop workloads and reinstall filtering;
live restore and workload restart policies are disabled.

The root-owned daemon configuration enables `userland-proxy` and ICC. Both
bridge IP traversal sysctls stay zero inside RootlessKit's network namespace;
native bridge and IP hooks distinguish bridged traffic from routed traffic.
Verification compares complete native JSON against the recorded policy compiled
in a temporary namespace, rejects ICC-disabled networks, and checks both sysctls.
Relay creation checks the sysctls again, since network creation can change them
without changing the daemon's verification receipt. Do not apply these settings
to an arbitrary Docker installation: they change inter-container filtering.

Startup collects the base, agent, authentication, and command-proxy builds into
one `docker buildx bake` invocation with one interactive progress display.
BuildKit checks its cache on every launch. The base feeds the agent through a
Bake target dependency; existing tags never substitute for checking changed inputs.
On failure, BuildKit prints the failed step and the launcher adds a short build
failure summary, preserving the exit status without dumping its internal command.

Repositories provide `.agents/sandbox/docker-bake.hcl` with a `base` target.
Paths resolve from the repository root.
Command proxies select targets through `image-target` in `proxy-commands.json`.
Use `contexts = { sandbox-base = "target:base" }` and
`args = { BASE_IMAGE = "sandbox-base" }` for a proxy Dockerfile derived from the base.
Buildx resolves HCL variables, inheritance, and target dependencies.

The file also works independently, from the repository root:

```sh
docker buildx bake -f .agents/sandbox/docker-bake.hcl --load base
```

The launcher replaces output tags with private local tags, loads into its verified
engine, disables cache exports, and checks output digests before starting containers.
Repository exporters cannot publish images or caches during launch.
Podman and nerdctl continue to use `base-image` and `image-command`; keep those
builders when a repository supports both interfaces. A missing Docker Bake
definition for an existing builder fails with a migration error.

Returned references retain both tag and digest because BuildKit needs
the tag to resolve a local base; execution uses the verified configuration ID
with pulling disabled. Custom image entrypoints survive credential injection.

Monitor waits use host Docker clients. Each host-routed proxy request uses a
temporary container with only the proxy socket volume, allowing cancellation
through Docker's ordinary container API; Docker has no individual exec-kill API.
This adds container startup cost to host-routed commands.

This is not yet a default-backend recommendation. Long-running interactive Pi,
20 simultaneous sessions, and optional Agent Podman/Zulip
integration still need Docker-specific validation.

The [nftables differential probes](../experiments/nftables/README.md) retain
the historical policy and a rejected alternative as regression controls.

## Disposable validation

Use an otherwise idle test VM: the policy test deliberately restarts Docker
and injects a failed policy activation. Tests own their temporary resources;
the caller owns VM teardown. The launcher fixture uses dummy credentials and
checks interactive Pi input and cancellation as well as proxy requests.

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
python3 tools/codex-sandbox/tests/docker_recovery_integration.py \
  --state /private/tmp/docker-sandbox-test/state \
  --disposable-instance sandbox-host-docker-test --image IMAGE_REFERENCE
python3 tools/codex-sandbox/tests/docker_raw_network_integration.py \
  --state /private/tmp/docker-sandbox-test/state \
  --disposable-instance sandbox-host-docker-test --image IMAGE_REFERENCE
python3 tools/codex-sandbox/tests/bake_integration.py \
  --state /private/tmp/docker-sandbox-test/state
limactl delete --force sandbox-host-docker-test
```
