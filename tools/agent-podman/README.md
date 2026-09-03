# Disposable agent Podman machine

`setup.sh` creates a rootless Podman Machine under the fixed hidden, locked, non-login macOS role account `_agentpodman`.
It dynamically assigns an unused role-account UID in macOS's 450–499 range, gives the account a dedicated primary group, and verifies that it is not a member of `staff`, `admin`, `wheel`, or `_developer`.
It disables Podman's default `$HOME:$HOME` mount and rejects `/Users`, `/Volumes`, 9p, and virtiofs mounts found in the guest.
It creates the non-sudo Linux user `agentbuilder`, starts her rootless Podman socket, and creates VM-specific SSH client and host-key files in `~/.agent-podman-access`, outside the project directory normally shared with the sandbox.
That key permits arbitrary non-PTY SSH commands as `agentbuilder`, which has the same arbitrary-code authority as her Podman API.
Podman's separate VM lifecycle key remains confined to the locked macOS worker home.
The worker's Podman subprocesses and the SSH client run with minimal environments.

The setup also installs a macOS PF anchor for processes owned by `_agentpodman`.
It allows stateful inbound connections to the worker-owned guest SSH port and public DNS, then blocks other TCP and UDP traffic to local, private, link-local, multicast, and reserved address ranges.
Public Internet access remains available for image and package downloads.

The machine also contains a pinned `woodpecker-cli` and a supervisor used by
the sandbox's `woodpecker-cli exec` adapter. The adapter stages the requested
repository inside the machine, applies a shared SELinux label only to that
per-run workspace, streams Woodpecker output, and safely reaps abandoned runs.

This is a meaningful VM boundary, not protection against VM-runtime vulnerabilities.
The threat model treats the host administrator, setup environment, and installed scripts as trusted, while treating the agent container, submitted build inputs, and eventually the entire guest as hostile.
The guest retains public network access.
The PF rules substantially restrict standard host and LAN ranges, but they are not an egress allowlist and cannot identify privately routed public address space.
The restricted macOS account may also read files that host permissions make world-readable.
Don't expose host credentials, an SSH agent, the Docker socket, or sensitive services.
The exposed Podman API permits arbitrary code execution as `agentbuilder`;
treat the VM as compromised after every agent session and recreate it before another trust domain uses it.

## Setup

Install Podman on the Mac.
Install the scripts somewhere the sandboxed agent cannot write;
for example:

```sh
sudo install -d -m 755 -o root -g wheel /usr/local/libexec/agent-podman
sudo install -m 755 -o root -g wheel setup.sh teardown.sh woodpecker-supervisor.sh /usr/local/libexec/agent-podman/
```

Run the installed setup script:

```sh
sudo /usr/local/libexec/agent-podman/setup.sh
```

The scripts find `podman` on the standard Homebrew or system path.
If it is elsewhere, pass the trusted absolute path to both setup and teardown as `AGENT_PODMAN_BIN=/path/to/podman`.

The script refuses existing account, home, marker, and access-directory state.
On failure it retains state and root-owned provenance for inspection and explicit teardown;
it doesn't attempt a risky automatic rollback.

Optional resource controls are positive integers:

```sh
sudo \
  AGENT_PODMAN_CPUS=6 \
  AGENT_PODMAN_MEMORY=12288 \
  AGENT_PODMAN_DISK_SIZE=30 \
  /usr/local/libexec/agent-podman/setup.sh
```

Mount only the generated client key and sandbox known-hosts file into the Docker sandbox:

```sh
docker run ... \
  --env AGENT_PODMAN_KNOWN_HOSTS=/run/secrets/agent-podman-known-hosts \
  --mount type=bind,src="$HOME/.agent-podman-access/id_ed25519",dst=/run/secrets/agent-podman-key,readonly \
  --mount type=bind,src="$HOME/.agent-podman-access/known_hosts.sandbox",dst=/run/secrets/agent-podman-known-hosts,readonly \
  sandbox-image
```

Pass the four values recorded in `~/.agent-podman-access/connection.env` as environment variables, then run `podman --remote info` inside the sandbox.
The adapter uses the stable `agent-podman` host-key alias because its relay IP changes per sandbox session.
Don't mount `connection.env` or the whole access directory.

The forwarded port exposes only authenticated guest SSH; it does not expose an unauthenticated Podman TCP API.

## Recovery

The sandbox reaches the machine through a per-session `socat` relay.
If the machine stops, the relay may continue accepting TCP connections while its upstream host port refuses them.
SSH then closes before presenting a server banner, and Podman reports a handshake `EOF` rather than saying that the machine is stopped.

Confirm the failure at the authoritative boundaries before changing credentials:

```sh
# In the sandbox: Podman reports an SSH handshake EOF.
podman info

# On the host: the relay log names a refused host.docker.internal port.
podman logs --tail 100 <agent-podman-relay-container>
```

When the relay's upstream port is refused, start the existing machine from the dotfiles checkout:

```sh
tools/agent-podman/start.sh
```

Do not recreate keys, known-hosts files, or the relay first.
If the machine is already running or its forwarded port changed, restart the sandbox so the launcher regenerates the relay and connection metadata together.
Use teardown and setup only when the existing machine or persisted access state cannot be recovered.

## Teardown

```sh
sudo /usr/local/libexec/agent-podman/teardown.sh
```

Teardown checks the root-owned provenance marker, asks Podman to remove the VM, verifies that no worker processes remain, releases the PF enable reference, and deletes the fixed worker account, group, and home.
It retains the provenance marker and reports failure if any required deletion cannot be verified.
It never deletes caller-owned credentials as root;
after teardown, run the exact `rm` and `rmdir` commands it prints.
