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

Setup creates `sandbox-host-docker` with 8 CPUs, 8 GiB RAM, and a 100 GiB disk.
Existing VMs retain their resource sizes when setup is rerun.
It shares your home directory with the VM; containers retain the launcher's
narrow mounts. Setup copies the real Homebrew Docker CLI 29.8.0 into private
state, so Homebrew cleanup and the `docker` → Podman alias cannot replace it.
New VMs allocate `/24` bridge networks from `172.16.0.0/12` and configure twenty
SSH sessions per connection. Docker's default address pools otherwise run out
before twenty sandboxes can each allocate their two gateway networks. Existing
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
Docker environment files are private host temporary files, read by the host
client and deleted after use. They require no guest share or guest bind check.

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

## Container cache reclamation

New VMs put containers under a persistent `sandbox.slice`. A guest systemd
timer can reclaim one cache batch every 30 seconds after the previous job
finishes, including after the last container exits. The batch is 32 MiB, with
1-second timer accuracy, a 10-second execution timeout, and a 5-second stop timeout.
New VM generations enable the timer after their provisioning audit succeeds;
these settings are experimental, not a proven host-descriptor budget.

```sh
python3 tools/codex-sandbox/lima/docker_host.py reclaim once
python3 tools/codex-sandbox/lima/docker_host.py reclaim enable
python3 tools/codex-sandbox/lima/docker_host.py reclaim disable
python3 tools/codex-sandbox/lima/docker_host.py status
python3 tools/codex-sandbox/lima/docker_host.py doctor
```

`enable` restores periodic reclaim; `disable` stops the timer and job and
checks that no worker still holds the reclaim lock. Disablement survives Docker
restart, VM reboot, and setup repair. An unsettled worker is reported as an
error; do not delete its lock file. Inspection reports timer enablement, next
activation, and the last job result. Job success means a reclaim request ran,
not that host descriptor pressure was resolved; partial reclaim is normal.
For guest diagnostics use `sudo journalctl _SYSTEMD_USER_UNIT=sandbox-reclaim.service`
inside the selected VM (the guest user may lack journal read permission).

Containers keep running, and may reload evicted data. The timer neither measures
host pressure nor prevents ENFILE when active demand outruns reclamation.
Daemon/BuildKit caches are outside the container slice. The
[replay results](../experiments/reclaim-timer.md) record a 6% median slowdown;
the [specification](../reclaim-before-exhaustion.typ) defines the ownership and lifecycle rules.

Existing VMs keep their immutable provisioning snapshots and report reclamation
as `not-installed`. Use a new `--state` directory and `--instance` to adopt this
layout, then recreate containers there. A scheduled VM stop clears earlier cache
ownership; setup does not move live containers or rewrite old policy hashes.

## Runtime policy checks

Launches check the recorded engine identity and service readiness; they do not
audit, install, or repair policy. The Docker service installs its firewall in
`ExecStartPost`; failed installation prevents the service becoming ready.
Ordinary operations trust that admitted runtime. Cleanup still checks engine
identity before removing resources, including when policy is damaged.

Setup performs the full configuration audit. To check for configuration drift
explicitly, run:

```sh
python3 tools/codex-sandbox/lima/docker_host.py doctor
```

Pass `--state DIRECTORY` before `doctor` for a non-default VM. The command checks
installed policy files, rootless Docker configuration, network rules, and shares;
it reports failures without repairing them. Out-of-band configuration changes
are an operator responsibility: run `doctor` after making them. `status` and
`start` check readiness without the full audit.

Service-readiness queries reuse Lima's generated SSH configuration directly.
Guest commands also use that SSH configuration, retaining Lima's login shell
and `/tmp` working directory. Credential transfers remain on stdin.
In-process proxy helpers reuse the launcher's runtime. Proxy labels and image
identity come from one live container inspection. Image preparation completes
before network workers start; independent image checks run concurrently.
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
internal gateway links cannot route between sessions. Each sandbox gateway has
one private egress network and fixed editor and optional Podman SSH listeners.
Neither listener accepts a client-selected destination.
Docker restarts stop workloads and reinstall filtering;
live restore and workload restart policies are disabled.

The root-owned daemon configuration enables `userland-proxy` and ICC. Both
bridge IP traversal sysctls stay zero inside RootlessKit's network namespace;
native bridge and IP hooks distinguish bridged traffic from routed traffic.
The setup/doctor audit compares complete native JSON against the recorded policy compiled
in a temporary namespace, rejects ICC-disabled networks, and checks both sysctls.
Relay creation checks the sysctls again, since network creation can change them
after service activation. Do not apply these settings
to an arbitrary Docker installation: they change inter-container filtering.

Lima-Docker reads repository images from an executable `.agents/sandbox/bake`.
Run it from the repository root; stdout must contain fresh Docker Bake HCL or
JSON with source-input hashes in target tags, and diagnostics belong on stderr.
The launcher passes the declaration to pinned Buildx `bake --print`, selecting
the recorded engine's platform through `BUILDPLATFORM`. No build runs during
metadata resolution.

The `base` target supplies the agent base. Repository proxy manifests select
targets with `image-target`; when both fields exist, Docker prefers that target.
The installed auth, JJ, and Zulip helpers share a fresh Bake declaration and the
launcher's admitted runtime. Their compatibility commands use the same source
keys with `sandbox-image` on other backends. Repository targets cannot replace
the installed helpers.
The Docker CLI shim has been removed: repository builders must migrate their
Docker calls to Bake declarations before using this backend.

The producer owns input freshness, including added, removed, renamed, and
edited sources. A checked-in generated Bake file alone cannot establish that.
Owned image keys cover packaged runtime inputs; tests, documentation, and Python
bytecode do not belong in the agent or Zulip image inputs.
The launcher derives private cache tags from resolved target options, platform,
and actual dependency image IDs. Existing tags skip the build entirely.
Within a launch, immutable image metadata is reused for command selection and
validation; mutable tags are read afresh. Cached proxies use one live container
snapshot for running state, identity, and socket mounts, retaining volume-owner
and forwarding-health checks.
A changed proxy source key rebuilds only the proxy; a changed base identity
also invalidates its dependent targets. Manual Bake tags remain separate from
these launcher-owned tags.

Supported declarations use local contexts and Dockerfiles, string build
arguments and labels, input-keyed tags, an optional build stage, a single
engine-matching platform, and named `target:` contexts. Unsupported options,
cycles, missing dependencies, and external outputs fail before any build.
Dockerfiles resolve relative to their contexts. Missing targets build through
pinned Bake with local image output; resolved dependencies use verified local
tag-plus-digest contexts instead of rewriting `BASE_IMAGE` CLI arguments.

Actual builds serialize their native progress displays across launches.
Independent targets in a ready dependency layer build together.
Each launch finishes its builds before starting container workers; the existing
builder supervisor owns declaration, metadata, and build subprocesses.
Docker preparation returns one base/auth/proxy image result before container
workers start. Bake references are reused within that process; serialized proxy
references are verified again in the receiving process against its engine.
Independent executable-image checks run concurrently within preparation.
Warm launches produce no build transcript. Build failures preserve BuildKit's
diagnostic and failure status. No additional cache manifest is required.

Network setup failures include the runtime diagnostic and exit status.
On Lima-Docker this step verifies the provisioned network rather than creating it.

Returned references retain both tag and digest because BuildKit needs
the tag to resolve a local base; execution uses the verified configuration ID
with pulling disabled. Custom image entrypoints survive credential injection.
Engine and image metadata use direct reads from the recorded Docker socket;
ambient Docker contexts and HTTP proxy settings do not select another engine.

Monitor waits use host Docker clients. Proxy requests use the session-owned
socket transport described above; they do not use Docker exec cancellation.

## Default readiness

Podman remains the default. Recorded September 10 validation completed twenty
simultaneous Pi sessions, 400 JJ requests, subsequent input/cancellation, and
container/network/volume cleanup. This was a small shared repository; it did not
measure sustained output or input during active large-tree/subagent work.
Policy restart/failure and raw-packet isolation probes also passed. These are
historical results, not a rerun against every subsequent launcher change.
See the [validation record](../../../notes/lima-docker-remaining-gaps.md#2-validate-sustained-concurrency-and-failure-cleanup).

Host-wide `ENFILE` recurred during real work, with many descriptors retained by
the VirtioFS VM processes and few open guest files. No durable pressure remedy
is installed. See the [incident record](../../../notes/virtiofs-file-table-pressure.md)
and [September 12 investigation](../experiments/enfile.md): cgroup reclamation
released retained descriptors in an owned fixture, but sustained recovery is
not yet validated. Use the [bounded sampler](../experiments/file-pressure.md)
to measure current headroom.
The [cause investigation](../experiments/enfile-causes.md) also found substantial
retention in Podman and nerdctl VMs with no running containers; rollback engines
need an explicit cold-standby or shared-budget policy.
New provisioning enables a [reclamation timer](#container-cache-reclamation).
Its [replay](../experiments/reclaim-timer.md) passed the selected cost and sampled
headroom criteria; it does not establish a host-wide budget for concurrent VMs.
Before switching the default, establish a host file-table budget under repeated
large-tree work and concurrent sessions, and rerun the disposable Docker gates
against the selected revision. `dev/test --lima` exercises nerdctl, not Docker.

Zulip's Docker fixture passed dummy-credential TLS and upstream-401 cases;
this does not establish configured end-to-end parity. The gateway has its own
editor/SSH fixture below. Long-running interactive work, configured Agent
Podman/Zulip smoke tests, and rollback remain cutover checks.

The [backend review](docker-review.md) records compatibility gaps and
maintenance findings at revision `b4930191`.

The [nftables differential probes](../experiments/nftables/README.md) retain
the historical policy and a rejected alternative as regression controls.
The [forwarding findings](forwarding-review.md) preserve the discarded experiments'
measurements, transport-status difference, adoption rationale, and validation limits.

## Gateway validation

With Agent Podman running and its SSH access configured, test the gateway using
an existing sandbox agent image (with Python and SSH):

```sh
python3 tools/codex-sandbox/tests/gateway_integration.py --agent-image IMAGE_REFERENCE
```

This creates two owned gateways, checks editor and SSH authentication,
cross-session isolation, upstream refusal, listener failure, and cancellation,
then removes its resources without resetting the VM or existing sessions.

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
