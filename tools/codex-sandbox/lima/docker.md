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
narrow mounts. Setup copies the real Homebrew Docker CLI 29.8.0 into private
state, so Homebrew cleanup and the `docker` → Podman alias cannot replace it.
New VMs allocate `/24` bridge networks from `172.16.0.0/12` and configure twenty
SSH sessions per connection. Docker's default address pools otherwise run out
before twenty sandboxes can each allocate their two editor networks. Existing
VMs retain their pinned daemon configuration until explicitly migrated.

For existing state, or to repair a missing or altered private CLI, run:

```sh
python3 tools/codex-sandbox/lima/docker_host.py pin-client
```

This validates the copied executable and atomically records its digest without
restarting the VM or changing engine identity. It works even if the previously
recorded Cellar path has disappeared. Install Docker 29.8.0 first; an explicit
`--source PATH` after `pin-client` selects another copy of that version. For
non-default state, pass `--state DIRECTORY` before `pin-client`. Missing or
non-executable pins fail with a repair command; they never fall back to PATH.

Setup copies host Buildx v0.37.0 into private state. Builds
invoke it directly with the recorded Docker socket and private builder settings;
Homebrew upgrades and plugin discovery cannot replace it. For a VM created before
host Buildx pinning, run this once from dotfiles (no VM restart):

```sh
python3 tools/codex-sandbox/lima/docker_host.py pin-buildx
```

Use the same command to repair a missing or changed copy, after installing the
supported Buildx version; add `--state DIRECTORY` before `pin-buildx` for a
non-default VM. An unavailable or non-executable pinned binary blocks builds rather
than falling back to another plugin.

Docker and Buildx copies are version-checked and hashed during pinning.
Startup checks their file type, ownership, and permissions without rehashing
their contents; Homebrew does not manage these private copies.

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
Service-readiness queries reuse Lima's generated SSH configuration directly;
each query still checks the VM identity and Docker service invocation ID.
Guest commands also use that SSH configuration, retaining Lima's login shell
and `/tmp` working directory. Credential transfers remain on stdin.
In-process proxy helpers reuse the launcher's runtime. Proxy labels and image
identity come from one live container inspection; Docker operations still
check the recorded VM and engine as before.
After builds finish, read-only image checks overlap network preparation;
proxy attachment waits for both.
Host-routed commands use a private Unix-socket forward per cached proxy on Lima's
existing SSH master. The transport creates no per-request container or SSH process;
the router still performs its runtime and proxy identity checks.
The shared proxy state owns listener registration and short guest aliases;
reset removes both. Cancelling a router closes its connection, without promising
cancellation of a command already accepted by the server.

After upgrading from forwarding containers, exit existing sandboxes before
launching again so their cached proxies can be rebuilt. If Lima's SSH master
restarts during a session, exit and relaunch; the next exclusive launch replaces
stale listeners. No VM recreation is needed for this forwarding change.
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

Startup uses the existing executable `.agents/sandbox/base-image` and each
proxy's `image-command`, just like Podman. Builders own their input keys and
build-if-missing decisions. A changed key selects a new tag; an existing tag
skips the build entirely. The launcher retains its existing agent key, which
includes copied sources, base image identity, UID, GID, and terminal type.
No additional cache manifest or Bake definition is required.

Builder subprocesses receive a private `docker` adapter on PATH. It uses the
recorded engine and pinned clients, ignoring ambient Docker contexts and the
host's Podman alias. `docker build` invokes pinned Buildx directly, loading its
output locally. Builders may return a local `sha256:` image ID or a repository
digest; the launcher verifies it in that engine. For existing builders that pass
an image ID as `BASE_IMAGE`, the adapter resolves it to a local tag plus digest:
BuildKit otherwise treats the ID as a registry image name.

Actual builds serialize their native progress displays across launches.
Independent image builders run up to four at a time within a launch.
Each launch finishes its builders before starting container workers, so
cancellation stops owned builder groups, including nested native builds and
output-lock waiters, before cleanup.
Warm launches produce no build transcript.
On failure, BuildKit prints its diagnostic and the launcher preserves failure
status. Repository Bake files remain available for manual builds, but startup
uses `image-command`; `image-target` annotations do not select startup images.

Network setup failures include the runtime diagnostic and exit status.
On Lima-Docker this step verifies the provisioned network rather than creating it.

Returned references retain both tag and digest because BuildKit needs
the tag to resolve a local base; execution uses the verified configuration ID
with pulling disabled. Custom image entrypoints survive credential injection.
Engine and image metadata use direct reads from the recorded Docker socket;
ambient Docker contexts and HTTP proxy settings do not select another engine.

Monitor waits use host Docker clients. Proxy requests use the session-owned
socket transport described above; they do not use Docker exec cancellation.

This is not yet a default-backend recommendation. Long-running interactive Pi,
20 simultaneous sessions, and optional Agent Podman/Zulip
integration still need Docker-specific validation.

The [backend review](docker-review.md) records compatibility gaps and
maintenance findings at revision `b4930191`.

The [nftables differential probes](../experiments/nftables/README.md) retain
the historical policy and a rejected alternative as regression controls.
The [forwarding findings](forwarding-review.md) preserve the discarded experiments'
measurements, transport-status difference, adoption rationale, and validation limits.

## Disposable validation

`tests/docker_forwarding_integration.py` accepts `--state`, `--repo`, and
`--image`. Supply an owned disposable colocated repository containing Paracress's
bug manifest and an empty `.agent-git-bug` directory, plus its cached bug image;
never supply a working repository. It checks manifest mounts, normal and malformed
responses, TERM/KILL cancellation, long socket paths, cached-session admission,
and stale-listener cleanup without restarting the VM or touching other sessions.

Use an otherwise idle test VM: the policy test deliberately restarts Docker
and injects a failed policy activation. Tests own their temporary resources;
the caller owns VM teardown. The launcher fixture uses dummy credentials and
checks interactive Pi input and cancellation as well as proxy requests.
Add `--interactive-runs 5` to repeat sequential launches and emit `TERMINAL TIMING`
JSON records for readiness, key delivery and cancellation. Readiness means the
observer's session-start hook fired; key delivery means its stdin listener saw
the probe, not that Pi finished rendering. These are warm-launch measurements
after the fixture builds its images, not a concurrency test.
`PROXY TIMING` records measure complete host-routed JJ status requests, including
router startup, identity checks, and the session's SSH socket transport.
Use `--concurrent-sessions 20 --hold-seconds 60` for a bounded shared-repository
concurrency check. Each Pi must reach its observer hook before any receives the
key probe; all remain open for the hold interval, then each is cancelled and
cleaned up. This covers idle concurrent sessions, not large-tree or subagent
load. Start with two sessions and monitor host file-table headroom before scaling.
Add `--proxy-requests 20` to run twenty sequential `jj status` requests inside
each concurrent Pi session. All requests must succeed before the hold interval
ends; increase `--hold-seconds` to set that budget. This exercises shared proxies
without model calls, but does not substitute for large-tree or subagent load.
Failed launcher fixtures retain their directory and print its path for diagnosis
and recovery; successful fixtures remove it. Docker fixtures require container,
network and volume identities to return to their initial sets after cleanup;
images remain cached. Run them in a disposable VM without concurrent external
resource changes, which would invalidate that comparison.

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
python3 tools/codex-sandbox/tests/builder_integration.py \
  --state /private/tmp/docker-sandbox-test/state
limactl delete --force sandbox-host-docker-test
```
