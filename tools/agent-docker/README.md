# Rootless Docker for nested builds

The sandbox's `docker` command controls a separate Lima build VM. For example,
an image built in the agent is available to a staged Woodpecker run in that
same VM. The infrastructure VM continues to own the agent and trusted proxies;
exposing its daemon would let builds replace those services.

The build VM has no host filesystem shares, forwarded SSH agent, or host
credentials. Its `agentbuilder` account has rootless Docker and no sudo access.
A separate SSH key grants arbitrary commands as that account. The launcher
mounts only this key and the pinned guest host key into the agent, then routes
SSH through its authenticated gateway. Administrator SSH and Lima lifecycle
state stay on the host.

## Setup

Use the dotfiles checkout on the host. Install Python 3, OpenSSH, and Lima.
Linux requires x86_64, QEMU, and readable/writable `/dev/kvm`; macOS requires
Apple Silicon. The platform and pinned Ubuntu image come from the
[infrastructure Docker provisioner](../codex-sandbox/lima/docker.md).

```sh
python3 tools/agent-docker/vm.py setup
python3 tools/agent-docker/vm.py doctor
```

Setup creates `agent-build-docker` with 6 CPUs, 8 GiB RAM, and a 60 GiB disk.
It reuses the pinned Docker package and slirp4netns installers. Build access
lives in `~/.agent-docker-access`; private provisioning state lives in
`~/.local/state/agent-docker`. It leaves your host Docker context unchanged.
The guest also receives a pinned Woodpecker CLI and its workspace supervisor.

Enable `nested-containers` in the repository's sandbox manifest, then restart
that repository's sandbox so it loads the new image, connection, and gateway:

```sh
codex-sandbox restart --repo /path/to/repository
```

Inside the restarted agent, run `docker info`. It must report rootless Docker.
No local daemon fallback is selected when access is missing or stopped;
startup warns with the host setup or start command.

## Recovery and lifecycle

```sh
python3 tools/agent-docker/vm.py stop
python3 tools/agent-docker/vm.py start
python3 tools/agent-docker/vm.py doctor
```

Start checks the VM configuration, identity, running network policy, and
rootless engine before publishing its current SSH port. Restart the sandbox
after a port change. Setup reruns start for a ready provision; it does not
upgrade its immutable installation snapshot.
`doctor` allows 30 seconds for its checks and fails immediately if another lifecycle operation holds its lock.
For QEMU VMs, it checks execution state through QMP before contacting the guest.
Lima can report `Running` while QEMU is paused after a disk write failure.
If it reports `io-error` with `nospace`, follow [resume after disk-space exhaustion](../codex-sandbox/lima/docker.md#resume-a-qemu-vm-after-disk-space-exhaustion).
The check never resumes or restarts a VM automatically.
The build service uses a persistent guest-root-owned SSH host key; Lima's
per-boot administrator host-key rotation does not change this pin.

A failed setup retains its state and VM for inspection. Inspect the failure
before rerunning setup with the same arguments. If enabling linger fails,
setup prints guest logind and D-Bus status, logind CPU usage, and recent service
logs. Each diagnostic has a five-second limit; setup still fails if they are
unavailable. Repair the guest service before retrying the same host command.
Creation recovery refuses a VM with a different recorded generation.
Configuration or installation changes
require a fresh provision. To keep an existing VM while trying another:

```sh
python3 tools/agent-docker/vm.py --instance agent-build-docker-test \
  --state ~/.local/state/agent-docker-test --access ~/.agent-docker-test setup
```

Use those same options for lifecycle commands. Set `AGENT_DOCKER_ACCESS_DIR`
when launching a sandbox against custom access state.

Explicit teardown destroys all build images, volumes, and staged workspaces:

```sh
python3 tools/agent-docker/vm.py teardown
```

It removes only the recorded VM and known access files, retaining the host
provisioning snapshot. Rerun teardown if access cleanup fails after VM deletion.
Never point it at infrastructure VM state.

## Local CI and isolation

The agent's `woodpecker-cli exec` adapter transfers the supplied repository and
pipeline into a private per-run directory beside the build daemon. Woodpecker
uses that daemon's socket and guest-local bind sources. The adapter preserves
arguments and status, terminates the remote process group on cancellation,
and removes the workspace after exit or cancelled staging. `WOODPECKER_SECRETS`
travels over SSH standard input, never command arguments or adapter logs.
A guest timer reaps abandoned workspaces older than a day when their recorded
process is no longer running.
The supervisor defaults Docker's container stop timeout to one second so it
fits Woodpecker 3.15's five-second cancellation cleanup budget. An explicit
`--backend-docker-stop-timeout` overrides this default; longer values can leave
resources behind on cancellation. The supervisor allows 30 seconds before
forcing the CLI process group down.

Root-owned guest nftables rules restrict all sockets owned by `agentbuilder`,
including RootlessKit's network helpers. They reject IPv6 and local, private,
link-local, multicast, and reserved IPv4 destinations. Public downloads remain
available; DNS uses public resolvers. The build account cannot remove these
rules through its rootless Docker API, including privileged containers.
These restrictions do not identify privately routed public address space.
The boundary assumes the guest kernel and VM runtime enforce their isolation;
a guest-root or VM escape can defeat it. Build inputs and the build account
are untrusted. Do not share this VM across different trust domains.

Persisted Podman access is never interpreted as Docker access. Existing macOS
Podman deployments retain their [old teardown procedure](../agent-podman/README.md);
new sandbox launches use only Agent Docker state.

Run unit tests through `dev/test-environment`; the top-level test discovery
includes this directory. The opt-in VM/gateway acceptance test is documented
in [sandbox development](../codex-sandbox/development.md).
