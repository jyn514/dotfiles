# Codex sandbox operator guide

Choose the section for your task:

- [Set up a host or configure a repository](#prerequisites-and-setup).
- [Start, resume, split, restart, or rebuild a session](#common-commands).
- [Diagnose failures and check security boundaries](#safety-and-recovery).
- [Inspect installed Pi and model-request retries](../../config/pi-agent/README.md#inspect-the-installed-pi).
- [Change terminal ownership, profile startup, or run tests](development.md).
- [Change sandbox contracts](#design-and-reference).

## Purpose

`codex-sandbox` runs Pi on the host with its normal credentials by default,
while its built-in tools and human `!` shell commands run in the guest container.
Host mode requires the Pi installation at
`~/.local/share/pi/node/node_modules/.bin/pi` and the guest tool worker in the
current sandbox image. `./setup local` builds `jyn514/pi` from upstream main
checkout and installs that package at this path; `./setup all` includes it.
To repeat just this step, run `mise run pi-install` from this repository.
Guest Pi builds use the installed host commit recorded in
`~/.local/share/pi/node/.source-revision`, with guest-specific dependencies and binaries.
That commit is part of the image cache key: updating host Pi selects a new guest
image when starting a fresh sandbox. Missing or invalid revision metadata stops
image resolution; rerun `mise run pi-install` to repair it. Joining sessions check
the accepted image's Pi revision and reject a different or unknown commit;
run `codex-sandbox restart-all` to rebuild shared sandboxes after a host Pi update
or when migrating from images without revision labels. Existing sessions keep
their current worker until restarted.
The launcher loads its extensions from this checkout;
dotfile installation is not required for the sandbox path, but its default
Lima-Docker VM must be provisioned with `./setup sandbox` (or `./setup all`).
These commands also create or update the `lima` Docker context and make it the
persistent default for ordinary `docker` commands. Rerunning setup selects it
again; use `docker context use default` to switch back to the local engine.
`DOCKER_HOST` and `DOCKER_CONTEXT` environment variables override this selection.
A successful `/reload` restores the guest tool extension. Failed reload may
restore host-local built-in tools and `!` commands; guest routing is a
normal-operation guarantee, not a malicious-code security boundary.
The [host extension authority contract](spec/proxy-design.typ) still requires
admitted host handlers and brokered model requests; conformance remains unverified.
Proxy and credential failures still fail closed.
[Model-requested session forks](spec/launcher-interface.typ) are selected but not
implemented; they must inherit the parent's guest backend and authority.
Expanded `/skill:name` messages use guest resource paths when sent to the model,
including messages from resumed sessions. Stored messages retain their host paths.
Launcher-owned sibling services provide narrowly scoped access to protected repository operations, the host editor, optional Zulip, and optional Agent Podman.
Guest tools can write the working tree, but Git, Jujutsu, and sandbox policy remain outside their direct authority. Host Pi retains its own credentials.
Host `~/.pi/agent/sessions` is mounted read-only at
`/home/codex/.pi/agent/sessions` so guest tools can search past conversations.
Pi continues to write sessions on the host.

Guest `jj` calls snapshot the invoking Pi's model at dispatch, including in side
panes and ordinary subagents; later model changes cannot alter in-flight
attribution. Close existing sandbox panes and start a new sandbox to deploy the
host extension and guest worker together; `/reload` alone does not replace the
worker.

Agent containers drop `NET_RAW` on every backend, including after container-local sudo.
Sidecars drop all capabilities.
This takes effect on new launches;
restart existing sessions to apply it.

The launcher mounts `~/src` read-only at `/src`, then overlays the active repository writable at the same relative path when it is beneath `~/src`—for example, `~/src/dotfiles` becomes `/src/dotfiles`.
Repositories outside `~/src` use `/src/repository`.
The selected path is also the agent and proxy working directory.

For external worktrees whose mountpoints are missing beneath `/src`, the launcher stages those directories in temporary sandbox state and binds the existing source subtrees read-only.
This also accommodates linked Git metadata without creating placeholder directories under `~/src`.
Before launch, it rejects duplicate mount destinations in the assembled container arguments.
When this staging is needed, new entries in staged parent directories appear on the next launch;
the contents of bound subtrees remain live.

The launcher owns the selected repository's `.git` overlay. Linked worktrees
retain their pointer file as a read-only file mount, with backing metadata
mounted read-only at both host and guest paths so absolute and relative pointers
resolve. Directory overlays use the selected Git metadata root. Other metadata
mounts must not emit a second mount at the workspace's `.git` path.

### Host instructions and guest-readable guidance

Host Pi loads instructions from the host filesystem. `/reload` refreshes host
resources, but does not restage configuration or replace guest mounts. An updated
prompt can therefore point to a file that the guest cannot read.

Guest visibility depends on how the resource is exposed:

- **Staged configuration:** entries in the launcher's
  [`STAGED_CONFIG`](codex-sandbox), including `~/.agents/shared.md`, are copied
  at launch and mounted read-only. Host edits reach the guest on a fresh sandbox
  launch, not through `/reload`. Adding a Dotbot link alone does not expose a new
  standalone file in the guest.
- **Live skills directory:** the resolved source of `~/.agents/skills` is bound
  at `/home/codex/.agents/skills`. In-place edits and new files under that source
  are readable without restarting the worker. Retargeting the installed directory
  link requires a fresh sandbox launch to select the new source.

Put on-demand guidance under the existing skills directory when it should remain
live, such as `~/.agents/skills/references/change-with-evidence.md`. Plain reference
files do not need skill registration or an additional mount.

After changing an instruction route, reload host instructions, confirm guest
routing is active, and use the agent's guest `read` tool on the advertised path.
Check its contents against the authoritative source. Host-only Dotbot, packaging,
or native Pi tests do not establish guest readability.

## Flower R2 Keychain access

The [launcher interface](spec/launcher-interface.typ) makes optional services explicit.
Version 2 configuration, capability gating, bounded project-command transport, captured image inputs, explicit refresh and clean rebuild, and accepted-policy/image joins are implemented.

On macOS, launches selecting `flower-r2` expose a separate, session-authenticated Keychain relay through `CODEX_SANDBOX_KEYCHAIN_ADDRESS` and `CODEX_SANDBOX_KEYCHAIN_TOKEN`.
It accepts only `flower-r2/read`, reading accounts `access-key` then `secret-key` under service `dev.jyn.flower.r2` with `/usr/bin/security`.
Configure both items to confirm access;
choosing Always Allow can defeat repeated prompts.
An approved read discloses reusable credentials to the untrusted sandbox.
The relay keeps no credential cache and returns the pair only if both reads succeed.

Flower's local CI client consumes the framed protocol in [the relay design](spec/r2-keychain-relay-design.typ);
there is no credential-printing command. It sends one credential frame after connecting, so one
invocation can produce at most one Keychain consent sequence. Bounded connection-establishment
retry is still pending in the read-only `/src/flower` checkout; until Flower implements it, an
early request can fail instead of waiting for the best-effort relay. Explicit R2 environment
credentials bypass the relay, and unavailable relay credentials skip optional upload without
failing CI.
The lifecycle supervisor owns the per-launch Keychain listener, token, container, networks, startup worker, and owner-validated cleanup; R2 remains separate from authenticated HTTP egress.
The two relay networks are created concurrently. Startup joins both creation workers, fixes the relay address and per-launch token, installs peer authorization, and only then projects the capability. Cleanup first closes creation and request admission, joins prompt work, and removes only resources carrying this launch's owner identity. Relay failure remains warning-only and Flower skips optional upload.

Run `python3 tools/codex-sandbox/tests/keychain_bridge_test.py` for socket and dummy-child tests, and `python3 tools/codex-sandbox/tests/keychain_launcher_test.py` for launcher tests.
The opt-in `python3 tools/codex-sandbox/tests/keychain_integration_relay.py` exercises dummy credentials through disposable containers on the existing Docker VM.
The interactive consent probe is `python3 tools/codex-sandbox/tests/r2_keychain_consent_probe.py`;
its disposable Keychain password is `r2-probe-password`.

## Prerequisites and setup

Lima-Docker is the default outer runtime (`lima-docker`).
Follow the [Docker setup guide](lima/docker.md) before launching;
missing setup is an error, not a fallback to another engine.
[Opt-in Lima launches](lima/launch.md) use a separately provisioned VM, Keychain boot credentials, and runtime-aware image builders.
The [network fixture](lima/README.md) and [runtime contracts](lima/runtime.md) preserve the container boundaries;
`dev/test --lima` includes the disposable host, network, and runtime gate.
The [rootless Docker backend](lima/docker.md) uses Docker's forwarded API socket and has its own setup and validation commands.
Its [default-readiness record](lima/docker.md#default-readiness) distinguishes passed bounded tests from unresolved host file-table pressure and sustained-workload validation.

- Run from a Git checkout.
  The launcher uses the current Jujutsu workspace root and initializes a colocated Jujutsu workspace if needed.
- Install Python 3, Git, Jujutsu, tmux, and the Docker CLI used by the Lima-Docker VM.
  Image builds require network access on first use.
- Run `./setup py` to install the Python dependencies, including docker-py for
  `.dockerignore` support.
- Put this repository's `bin/` on `PATH`;
  `pi` normally delegates agent sessions to `codex-sandbox`.
  `pi --export SESSION.jsonl [OUTPUT.html]` must put `--export` first and runs native Pi on the host,
  without a Git checkout, VM, or guest worker. Relative paths use the caller's current directory.
- Provide `~/.codex/config.toml`.
  The [Lima credential helper](lima/credentials.md) can import an existing Podman secret `codex-github-token` into Keychain for migration to `GH_TOKEN`;
  exporting a host `GH_TOKEN` does not provision it.
  guest caching lasts one VM boot.
- Run inside tmux to use tmux session restart support.
  Repositories select host editing separately.
- Optional: create dedicated model credentials with `codex-sandbox auth login`.
  The directory defaults to `~/.codex-sandbox-auth` and may be changed with `CODEX_SANDBOX_AUTH_DIR`.
- Optional: configure Agent Podman separately under `~/.agent-podman-access` or set `AGENT_PODMAN_ACCESS_DIR`.
- Optional: configure [read-only Zulip access](../zulip-proxy/README.md).

A repository may use a version 2 `.agents/sandbox/proxy-commands.json` to select `host-editor`, `zulip`, `nested-containers`, `flower-r2`, and `agent-room` independently.
Host editing and Zulip default on;
`{"version": 2, "capabilities": {"host-editor": false, "zulip": false}}` disables both.
Zulip requires host credentials;
disabling it skips credential validation and proxy startup.
Nested containers, Flower R2, and agent-room default off. Selecting agent-room adds a fixed TCP relay
from the host's loopback-only `127.0.0.1:3000` to the same `127.0.0.1:3000` inside the agent container.
It accepts no agent-supplied destination and never relays the admin port 3001.
Host-editor and nested-container clients tolerate delayed best-effort listener startup for a
bounded readiness interval. Retries stop before the first request byte; after transmission starts,
transport failure is terminal and a possibly accepted operation is never replayed. Flower R2 does
not yet perform this pre-connection retry; see [Flower R2 Keychain access](#flower-r2-keychain-access).
Version 2 images declare one Bake file or project-command resolver and bind command and base image names.
Resolver commands receive the versioned JSON contract in [the launcher interface](spec/launcher-interface.typ) and run against the admitted engine.
The Bake resolver captures local inputs, assigns private content keys, and pins mutable upstream images by provider and platform.
Main contexts apply `.dockerignore`; a `<Dockerfile>.dockerignore` beside the
selected Dockerfile takes precedence. Ignored trees are skipped before copying
or hashing unless an exception requires visiting them. Changing ignored files
does not invalidate the image. The snapshot retains the Dockerfile and selected
ignore file so BuildKit uses the captured rules. Ignore files must be regular
files, not symlinks. Named local contexts remain complete snapshots.
The resolver uses docker-py's pattern implementation with local corrections for
case sensitivity, wildcard exceptions, and ancestor matching. It does not promise
complete equivalence with BuildKit's matcher for every pattern edge case.
Ordinary resolution reuses saved pins, then local image digests, and queries the registry only when neither is available.
It saves each ordinary resolution immediately so failed builds do not repeat registry lookups.
When `.agents/sandbox/docker-bake.hcl` exists, it becomes the default Bake resolver with base target `base`;
a repository using the default capabilities with no project command proxies can omit `proxy-commands.json`.
An explicit image resolver overrides this convention.
Version 1 and executable `.agents/sandbox/base-image` remain temporarily supported for external repositories.
This repository uses the version 2 bundled Bake resolver;
repository Docker CLI shims are no longer supported.
These files are trusted startup policy, not agent configuration.

For a project proxy that needs backing Git metadata, declare
`{"builtin":"git","proxy":"read-write","agent":"read-only"}` in its `mounts` array.
The launcher resolves colocated and non-colocated Jujutsu metadata, mounts it for
the proxy, and supplies its in-container Git directory as `SANDBOX_GIT_DIR`.
The agent retains only its launcher-protected read-only metadata view.

The agent image key hashes source bytes directly, without Git clean filters or line-ending normalization, so it tracks the bytes Docker builds.
Without a project base image, the launcher pulls its default Node image into the selected engine if absent, before computing the agent image key.
Later launches reuse the local base;
a failed pull aborts startup.

Pi runs from the installed host package; the sandbox image supplies only the
guest tool worker.

The agent image provides a `codex` wrapper that routes a base image's Codex CLI through the
session authentication proxy. It does not install Codex; invoking it reports how to repair the
base image when no later `codex` executable is present on `PATH`, or when proxy setup is missing.

The agent's `rg` wrapper disables ripgrep configuration and rejects executable
`--pre`, `--pre-glob`, and `--hostname-bin` options. Those strings remain valid
as `-e`/`--regexp` values or after `--`. Unknown option shapes fail closed for
these strings because the wrapper cannot safely infer their argument roles.
Refresh the sandbox image after changing the wrapper.

The image build installs the packages selected by `config/pi-agent/settings.json` with npm lifecycle scripts disabled, then loads their extensions without network access to seed Jiti's transpilation cache.
Only the cache enters the final image, at `/tmp/jiti`;
build-time package stores and extension runtime state are discarded.

Pi loads the installed host extensions and `/reload` uses Pi's normal host cache.
Local extension and settings changes invalidate the image;
moving Git refs are captured when the package-install layer builds and may produce runtime cache misses after an upstream update.

The goal extension uses the precompiled npm release pinned in `config/pi-agent/settings.json`.
Its Git distribution loads TypeScript, making cache misses more expensive.

## Common commands

```sh
pi                              # start a new resumable sandbox session
pi --session SESSION_ID         # resume a Pi session
pi --export session.jsonl out.html  # export HTML locally without sandbox startup
codex-sandbox auth login        # authenticate the Codex sidecar used by guest tools
codex-sandbox restart --repo "$PWD"  # restart this repo's registered sessions; run inside tmux
codex-sandbox restart-all       # restart all registered sessions; run inside tmux
tools/codex-sandbox/sandbox-image refresh --repo .  # update upstream pins and affected images
tools/codex-sandbox/sandbox-image clean --repo .    # rebuild declared images without build cache
CODEX_SANDBOX_TIMING=1 pi       # report preparation, launch, runtime, and cleanup timings
```

Under tmux, `/split` opens a Pi pane with completed context, a fresh session ID,
and focuses it, using the same guest container. `/split PROMPT` automatically
sends PROMPT in the new pane; `/split` alone starts it idle. It leaves the source and its
running work alone; unfinished tool batches and live subagents are not copied.
Panes share working-tree files, not later messages. Native `/clone`, `/fork`, and
`/resume` are unchanged.

Either pane may close first: the container, relays, and shared-session lock remain
until the final Pi attachment exits. Ordinary subagents remain owned by their Pi.
See [startup terminal ownership](development.md#startup-terminal-ownership) before changing
launcher stdio or process ownership.
Failed startup leaves existing panes running; worker loss affects all attached
panes. `/split` is a human command and is unavailable outside
an interactive sandbox.

`/cd DIRECTORY` validates an existing Jujutsu workspace, releases only this pane's
attachment, and forks into a new sandbox. Peers retain the old guest, which is
cleaned up before handoff only after its final attachment releases. Cross-directory
resume also forks and preserves the saved session. An empty session starts fresh;
unsaved messages block handoff.

`restart --repo DIRECTORY` stops, resets, and resumes registered tmux sessions for
that repository only. Pass the repository root; symlink aliases resolve to the
same path. No matching sessions is an error, not a fallback to restarting all.
Pi reports its selected session file and working directory at startup, `/reload`,
and session switches; restart resumes that file, including custom session storage.
It checks every selected saved file before stopping any pane. Missing, unsaved,
ephemeral, or mismatched-directory sessions fail without stopping sessions.

Run `/reload` once in existing Pi panes to replace old launch-time ID registrations.
If a previous failed restart left a dead pane, start `π --resume` from the original
working directory and select the saved conversation. Do not use `--session-id`
with the missing ID: that can create an empty conversation.

Both restart commands wait up to 60 seconds for sandbox ownership locks after
panes stop: detached owners can still be cleaning up after their UI exits.
A timeout retains recovery metadata and does not forcibly stop remaining owners.
Failed restarted UIs stay visible in their panes; successful exits still close
panes unless they already had `remain-on-exit on`. Use tmux copy mode to read the
error, or `tmux capture-pane -p -S - -t PANE` to include scrollback.

Neither `restart` nor `restart-all` manages side panes or sessions outside tmux.
Close side panes attached to the selected repositories first; they keep the
shared sandbox alive and prevent reset. There is no automatic worker replacement.

`refresh` queries mutable `FROM` and named image-context references, then rebuilds identities affected by changed pins;
it retains BuildKit caches.
Refreshed pins replace the previous pins only after the affected builds succeed.
`clean` retains the current pins but passes `--no-cache`.
Neither command changes images accepted by a live shared session or publishes registry images.

Project resolvers that derive Bake input at startup can delegate capture and building to the installed engine primitive:

```sh
sandbox-image bake --platform linux/arm64 --mode resolve base bug < fresh-bake.hcl
```

Run it from the project root with the launcher's admitted runtime environment.
Stdin accepts Bake HCL or JSON;
`--platform` must match the admitted Lima-Docker engine, and `--mode` is `resolve`, `refresh`, or `clean`.
Stdout contains the version 1 resolver result (`version` and `images`), with immutable references for the requested targets;
diagnostics go to stderr.
The command does not reload repository policy, so a version 2 command resolver can call it without recursion or writing a generated declaration into the checkout.

Set `CODEX_SANDBOX_HOST_EDITOR` to override the host editor;
otherwise `VISUAL`, `EDITOR`, then `vi` is used.
The dotfiles profile selects `config/nvim/host-editor.lua`, which applies hardening before loading plugin-free behavior from `config/nvim/shared.lua`;
normal Neovim loads the same shared behavior before its IDE configuration.

Each sandbox has one gateway for the host editor and, when configured, Agent Podman and agent-room.
It starts in the background after its private link and egress networks are created.
The in-container Python relay binds loopback and verifies its fixed gateway target before Pi starts.
Pi does not start if either step fails; its exit closes the listener and active connections.
Pi reaches its fixed editor and SSH ports by container DNS name. Their clients retry only
connection establishment within a bounded interval and never replay a possibly accepted request.
The separately supervised Zulip and Codex Caddy/helper services and repository-command proxies must be ready
before publication.

Shared proxy identity checks run two at a time during attach and publication.
Every check finishes before metadata is published or failure recovery begins.
Joiners print a notice when they reuse the accepted image and proxies; repository image changes
take effect only after every attached session exits and a new session starts.
Fresh sessions print a preparation notice and stream resolver and BuildKit diagnostics while
retaining stdout for the resolver's machine-readable result.
The launcher holds the session lock directly until cleanup.
The first launcher also holds coordination until publication succeeds;
shared joiners validate concurrently.
Failed publication retains coordination through cleanup, and a launch waiting for another publisher can be cancelled.

Gateway startup failures are reported to stderr and leave Pi running.
On exit, the launcher joins gateway startup before removing its container and networks.
An upstream refusal affects that connection;
a listener process failure stops the whole gateway.
Editor-only gateways retain the editor's CPU, memory, and process limits.
Agent-Podman-enabled gateways have no such limits, preserving build throughput but sharing the Agent Podman resource and failure domain with the editor.

Timing separates launch setup from `docker run`, then uses daemon timestamps to report container creation-to-start and start-to-exit intervals.
It also enables Pi's `PI_TIMING=1` startup breakdown, which excludes initial module imports.
The runtime interval includes the whole session;
use `CODEX_SANDBOX_TIMING=1 pi --help` for a bounded probe, not a measurement of interactive readiness.

Timestamp inspection runs after exit, has a five-second timeout, and preserves the agent's exit status.

Before changing launcher stdio or process ownership, follow
[startup terminal ownership](development.md#startup-terminal-ownership).
For interactive startup profiling, use
[Measure interactive startup](development.md#measure-interactive-startup).

## Safety and recovery

### Operational and security boundaries

- Treat the agent, including container root, as untrusted.
  It can modify ordinary working-tree files, the host's shared `~/.agents/skills` directory, and call every mounted proxy, but must not receive the outer daemon or direct writable access to `.git`, `.jj`, or `.agents/sandbox`.
- Trust the checkout and manifest authors before startup.
  Image builders and proxy images are part of the trusted computing base;
  a read-only mount does not make hostile policy safe.
- Networking blocks private and special-use IPv4 ranges.
  A manifest must explicitly enable network access for a proxy.
- The Codex sidecar keeps reusable OAuth tokens outside the agent, but the agent can submit model requests, disclose their contents, consume quota, and incur charges.
- Codex and Zulip credentials are mounted only into their respective profile-helper containers; Caddy and the agent receive no credential mount.
  Agent Podman, when configured, is exposed through a separate SSH relay rather than the outer daemon.
- The supported outer runtimes are Lima-Docker and opt-in nerdctl/Lima; both run the
  sandbox workload in a VM.
- Proxy and authentication failures fail closed and surface as request failures.
  They do not terminate an existing agent or fall back to privileged local execution or credentials mounted in the agent.
  New attachments reject an unhealthy session.

### Failure recovery

For model-provider errors, use the [installed Pi inspection guide](../../config/pi-agent/README.md#inspect-the-installed-pi)
to locate the provider and retry implementation. Pi owns model-request retries;
the sandbox proxy does not retry application requests. An occasional
`Codex (507): exceeded request buffer limit while retrying upstream` is recognized
by Pi's retry classifier; check Pi's retry outcome before restarting the sandbox.

The launcher preserves the agent's exit status and attempts to remove its containers, relays, networks, temporary files, and—after the final attached session exits—shared proxies.
`SIGINT`, `SIGHUP`, and `SIGTERM` also trigger cleanup.

The first session serializes proxy creation and publication.
Joining sessions validate the published proxies concurrently while holding lifetime locks that prevent reset or replacement;
a join cannot rewrite shared metadata.

- If startup reports invalid repository metadata or sandbox policy, repair the named path;
  do not bypass the validation.
- If authentication is disabled, run `codex-sandbox auth login`, then start a new sandbox.
- If Agent Podman reports an SSH handshake `EOF`, inspect the relay log before restarting the sandbox.
  A relay that accepts the sandbox connection but reports `host.docker.internal:<port>: Connection refused` means the Agent Podman machine is stopped;
  run `tools/agent-podman/start.sh` on the host.
  See [Agent Podman recovery](../agent-podman/README.md#recovery).
- If cached proxy/auth state changed or belongs to another network, run `codex-sandbox restart-all` from tmux.
  It terminates registered launcher processes, resets shared session metadata after cleanup, then resumes their sessions.
  Inherited `remain-on-exit` settings need no pane-local override.
- If automatic cleanup warns about a named resource, reset removes stopped `codex-sandbox-*` agent containers that hold the recorded proxy volumes, then retries cleanup.
  For surviving containers and volumes, the diagnostic includes each resource name and its removal error.
  The shared lifecycle treats a resource confirmed absent after a removal error as successfully removed;
  it briefly retries surviving owned resources while dependencies detach.
  Differently owned resources are never removed and, by themselves, do not cause a retry.
  A volume held by a running container is retained; stop that sandbox before retrying recovery.
  Do not delete the host coordination lock files manually.
- A stopped shared proxy terminates attached agents.
  Restart the sandbox rather than running the protected operation locally.

## Design and reference

The authoritative [sandbox design specification](spec/main.typ) aggregates the sandbox contracts, including the trust model, proxy manifest, image resolution, and lifecycle.
Read it before changing a security boundary.
See the [tools overview](../README.md).
