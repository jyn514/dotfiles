# Codex sandbox operator guide

## Purpose

`codex-sandbox` launches Pi in a disposable agent container. Launcher-owned sibling services provide narrowly scoped access to protected repository operations, Codex authentication, the host editor, optional Zulip, and optional Agent Podman. The agent can write the working tree, but Git, Jujutsu, sandbox policy, and reusable credentials remain outside its direct authority.

## Prerequisites and setup

- Run from a Git checkout. The launcher uses the current Jujutsu workspace root and initializes a colocated Jujutsu workspace if needed.
- Install Python 3, Git, Jujutsu, tmux, and a `docker`-compatible Podman/Docker CLI. Image builds require network access on first use.
- Put this repository's `bin/` on `PATH`; `pi` delegates to `codex-sandbox`.
- Provide `~/.codex/config.toml`. Export `GH_TOKEN` when the agent needs GitHub access.
- Run inside tmux to use the injected host editor and tmux session restart support.
- Optional: create dedicated model credentials with `codex-sandbox auth login`. The directory defaults to `~/.codex-sandbox-auth` and may be changed with `CODEX_SANDBOX_AUTH_DIR`.
- Optional: configure Agent Podman separately under `~/.agent-podman-access` or set `AGENT_PODMAN_ACCESS_DIR`.
- Optional: configure [read-only Zulip access](../zulip-proxy/README.md).

A repository may provide executable `.agents/sandbox/base-image` and a version 1 `.agents/sandbox/proxy-commands.json`. Repositories without extra command proxies may omit the manifest. These files are trusted startup policy, not agent configuration.

Alpine images run Pi's bundled Node CLI to reduce module-loading overhead. Other images use the standalone Bun executable.

## Common commands

```sh
pi                              # start a new resumable sandbox session
pi --session SESSION_ID         # resume a Pi session
codex-sandbox auth login        # create/update dedicated sandbox OAuth state
codex-sandbox restart-all       # restart registered sessions; run inside tmux
CODEX_SANDBOX_TIMING=1 pi       # report preparation, launch, runtime, and cleanup timings
```

Set `CODEX_SANDBOX_HOST_EDITOR` to override the host editor; otherwise `VISUAL`, `EDITOR`, then `vi` is used.

Timing separates launch setup from `docker run`, then uses daemon timestamps to report container creation-to-start and start-to-exit intervals. It also enables Pi's `PI_TIMING=1` startup breakdown, which excludes initial module imports. The runtime interval includes the whole session; use `CODEX_SANDBOX_TIMING=1 pi --help` for a bounded probe, not a measurement of interactive readiness.

Timestamp inspection runs after exit, has a five-second timeout, and preserves the agent's exit status.

## Safety and recovery

### Operational and security boundaries

- Treat the agent, including container root, as untrusted. It can modify ordinary working-tree files, the host's shared `~/.agents/skills` directory, and call every mounted proxy, but must not receive the outer daemon or direct writable access to `.git`, `.jj`, or `.agents/sandbox`.
- Trust the checkout and manifest authors before startup. Image builders and proxy images are part of the trusted computing base; a read-only mount does not make hostile policy safe.
- Networking blocks private and special-use IPv4 ranges. A manifest must explicitly enable network access for a proxy.
- The Codex sidecar keeps reusable OAuth tokens outside the agent, but the agent can submit model requests, disclose their contents, consume quota, and incur charges.
- Zulip credentials are mounted only into its proxy. Agent Podman, when configured, is exposed through a separate SSH relay rather than the outer daemon.
- On native Linux, dropped capabilities and `no-new-privileges` disable effective sudo elevation. A Podman Machine preserves container sudo without weakening host isolation.
- Proxy and authentication failures fail closed; they do not fall back to privileged local execution or mounting credentials in the agent.

### Failure recovery

The launcher preserves the agent's exit status and attempts to remove its containers, relays, networks, temporary files, and—after the final attached session exits—shared proxies. `SIGINT`, `SIGHUP`, and `SIGTERM` also trigger cleanup.

- If startup reports invalid repository metadata or sandbox policy, repair the named path; do not bypass the validation.
- If authentication is disabled, run `codex-sandbox auth login`, then start a new sandbox.
- If Agent Podman reports an SSH handshake `EOF`, inspect the relay log before restarting the sandbox. A relay that accepts the sandbox connection but reports `host.docker.internal:<port>: Connection refused` means the Agent Podman machine is stopped; run `tools/agent-podman/start.sh` on the host. See [Agent Podman recovery](../agent-podman/README.md#recovery).
- If cached proxy/auth state changed or belongs to another network, stop all sandbox sessions for that checkout and run `codex-sandbox restart-all` from tmux. The command resets shared session metadata before resuming registered sessions.
- If automatic cleanup warns about a named resource, inspect and remove only that generated resource with the container CLI, then retry. Do not delete the host coordination lock files manually.
- A stopped shared proxy terminates attached agents. Restart the sandbox rather than running the protected operation locally.

## Tests

Run unit tests from the repository root:

```sh
python3 -m unittest tools/codex-sandbox/tests/codex_sandbox_test.py
python3 -m unittest tools/codex-sandbox/tests/sandbox_proxies_test.py
```

The runtime integration test builds real images and requires a working Docker-compatible daemon and network access:

```sh
python3 tools/codex-sandbox/tests/image_runtime_integration.py
```

## Design and reference

The authoritative [sandbox command proxy design](proxy-design.typ) defines the trust model, proxy manifest contract, and lifecycle. Read it before changing a security boundary.
See the [tools overview](../README.md).
