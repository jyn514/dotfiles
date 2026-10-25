= Sandbox launcher: execution and image ownership

*Status:* Capability declarations, gating, bounded project-command transport,
captured Bake inputs, explicit refresh and clean rebuild, and schema 4
accepted-authority joins are implemented. Version 1 declaration adapters and
pre-schema-4 recovery remain for migration; active legacy sessions cannot join.
Host Pi with guest tool execution is the launcher execution path; the host
extension authority requirements below are not yet fully verified.
The shared-dotfiles workspace contract below is implemented.
Interactive `/split` panes use shared guest-workload lifetime. Native Pi/tmux
checks use a real local tool worker; VM-backed acceptance remains unverified.
This is the canonical execution-attachment, capability-selection, and image-resolution contract for
#link("proxy-design.typ")[the sandbox launcher specification]. It supersedes
the implemented image-command/image-target split, not the proxy trust or
transport contracts. Adopted from the maintainers-ai-guide sketch of 2026-09-12.

== Host virtualization boundary <host-virtualization>

The selected Linux runtime keeps the container engine inside a dedicated Lima
virtual machine. On `x86_64` Linux, Lima uses QEMU with KVM acceleration: QEMU
provides the virtual machine and device model, while KVM lets the guest execute
compatible CPU instructions through the Linux kernel's hardware virtualization
interface. Provisioning must verify that KVM is available and must fail rather
than silently falling back to software CPU emulation.

macOS retains the native VZ Lima backend. Podman remains an explicit backend for
hosts without the VM setup, but it is not equivalent to this VM boundary and
must not be described as the same isolation level. The launcher keeps the
container mounts, protected metadata overlays, and credential boundaries
unchanged across these host backends; only the outer engine and its lifecycle
change.
The Linux path is implemented for `x86_64` hosts but requires native Lima,
QEMU, Docker, Buildx, and KVM validation before it is considered production
ready.

Keep ordinary launches quiet and avoid BuildKit solves when images are reusable.
Simple repositories should declare builds without cache code; projects with an
existing image lifecycle retain ownership of it.

== Host Pi and guest execution <host-pi-execution>

The proposed #link("remote-frontend.typ")[remote frontend contract] separates
the frontend host from the sandbox host for `pi --ssh HOST:/absolute/project/path`.
It specifies a Pi resource-provider API and local SSH extension for startup,
compatibility, guest resource loading, and transport loss;
the attachment and sandbox policy rules here remain authoritative. Remote mode
is not implemented.

The parent Pi and its Pi subagents run on the host. Pi owns conversation
persistence, model requests, and UI; the launcher owns execution attachments,
and the tool backend executes arbitrary model-selected filesystem and process
operations inside the guest during normal operation. Host extensions follow the
#link("proxy-design.typ")[extension authority contract]; guest tool routing is
guaranteed during normal operation only.
Installation alone does not authorize a host handler. Host code and executable
configuration must remain inaccessible to guest writes through every mount alias.

An execution attachment binds one interactive host Pi and its ordinary children
to a guest worker and directory. Human-created `/split` panes have separate
attachments to that worker, not separate containers. Pi conversation files remain
on the host.
The launcher selects the active repository and guest mounts; repository tool arguments use guest paths.
Host-discovered shared skills are mounted at the guest skills path. Recursive project instruction includes and resource reads
resolve in the guest view under the extension authority contract. Rewrite mapped
host resource paths to guest paths in `context_with_system` before each model request,
including goal-triggered turns, structured system-section updates, and resumed sessions;
advertise the guest working directory in the same projection. Stored messages retain host paths. Path
rewriting alone does not constrain the preceding resource reads. Host Pi's README,
docs, and examples are mounted read-only at guest Pi package paths; their
advertised host paths map to those guest paths. Project-relative resources, including project skills, map
from the host repository root to its `/src` guest mount.
Resources under launcher dotfiles project to its selected guest root even when the host checkout is outside the source tree.
Other sibling and historical paths remain unchanged.
A saved conversation's cwd is historical context, not a request to mount that
directory. Cross-directory resume forks into a new session ID under the selected
launch directory.

The host backend sends structured tool calls to a persistent guest worker and
returns progress, text, images, errors, and completion to Pi. Through this
attachment, it reuses Pi's guest tool implementations for normal built-in and
`!` calls. With the guest-tool extension loaded, backend absence or guest failure
returns an error. A failed extension reload may restore Pi's host-local tools;
guest tool routing is a normal-operation guarantee, not a malicious-code security
boundary. Bind each routed call to its inherited attachment until it settles.
The #link("../../jj-proxy/design.typ")[runtime agent identity contract] defines
per-operation model snapshots and their metadata and shell-environment representation.
Cancellation requirements belong to
#link("process-ownership.typ")[process ownership].

=== Directory changes and attachment lifetime

`/cd` is a Pi command handled from human input. Model text, copied conversation
state, and tool requests cannot authorize a new writable repository. It validates
an existing Jujutsu workspace before stopping the current session.

`/cd` is a session handoff, including changes within the same repository:

+ Check the destination path without creating resources. An invalid path leaves
  the current session usable.
+ Abort and settle the current turn, then shut down this Pi and its child manager.
  Release this pane's old attachment before starting the destination. Peer panes
  keep their attachments and guest worker; remove the old workload only
  after its final attachment releases.
+ Start the destination through ordinary startup or accepted-session joining, then
  fork the settled conversation into a fresh Pi session with normal resource
  loading. Preserve historical messages and paths; add the directory transition
  to context. With no saved file and no messages, start fresh; unsaved messages
  block the handoff.

Cross-directory resume uses the same fresh-session rules. At CLI startup there
is no current attachment to shut down; in the UI, close the current session first.

The new session follows Pi's ordinary fork behavior. Historical child results
remain conversation data; live child processes and extension state are not
transferred. Rebuild the runtime rather than rebind a live session.

This pane owns only one attachment during handoff. Destination startup or
session creation failure runs ordinary failed-start cleanup. Preserve the saved
conversation; retain recovery records only for resources whose cleanup failed.
Report failure without claiming rollback or automatically resuming the old session.
The launcher owns attachment release and final guest cleanup. Shared-session locks
and per-launch services remain held while another pane uses that workload.

=== Subagents without a second lifecycle implementation

Keep the subagent extension's host process manager, RPC pipes, transcripts, and
overlay sockets. The child wrapper loads the guest-tool extension and inherits
the attachment; guest processes receive no host Pi credentials. Child tasks and
templates use that backend during normal operation and do not authorize
unreviewed host handlers.

Use the existing `PI_SUBAGENT_PI_BIN` entrypoint override. The wrapper launches
host Pi with the guest-tool extension; it does not own a second guest Pi process.

=== Interactive `/split` panes <interactive-side>

Human `/split` opens a host Pi tmux pane with copied context, using the same guest
worker, working tree, and accepted authority. It creates no container or policy
reload; Pi and saved conversations stay on the host. Use a normal extension command
and leave native `/clone`, `/fork`, and `/resume` unchanged. Without tmux or a live
sandbox attachment, report an error and leave the invoking session alone.

A continues while `/split` opens B. Closing A ends its ordinary subagents, but B
and the container remain; closing B then removes the container. Panes share files,
not subsequent conversation messages.

Pi copies the invoking session's active branch through its supported session APIs
into a fresh session ID with an empty editor. Use completed context; do not copy
or replay an unfinished response or tool batch, live children, or executable
extension state. Do not interrupt the source. Focus the new pane and automatically
submit the optional `/split` argument there; without an argument, start idle.

The launcher owns the guest workload and its Pi attachments; cleanup is not tied
to the first Pi's exit. Reserve an attachment before pane startup and release it
on failure. Keep the worker, launch-scoped relays, and shared-session lock until
final release. Ordinary subagents and model-requested forks remain owned by their
invoking Pi and do not independently retain the workload.

On pane exit, existing Pi/child shutdown and tool cancellation precede attachment
release. `/cd` releases only the invoking attachment; peers keep the old worker.
Final release uses existing workload and trusted-service cleanup.
Failed startup cleans only that attempt; worker loss
affects all panes. Reuse existing owner-loss recovery and unknown-write-outcome
handling; add no cancellation protocol or automatic worker replacement.

Explicit restart commands include every registered Pi attachment in the selected repositories within the current tmux server, including split panes.
Validate every saved conversation before stopping any attachment.
Stop all selected attachments and wait for final-owner cleanup before resetting shared services.
Resume each pane's selected conversation in a new sandbox owner without replaying an initial prompt or live tool work.
Retain resume registrations through old-owner cleanup so a failed restart can be retried from dead panes.

The host derives the conversation, worker, directory, executable, and pane target
from the invoking session. This is a bounded human operation, not a model-facing
host shell or a way to select another container, environment, or capability set.

A detached launcher owns workload lifetime. Each interactive `sandbox-host-pi`
wrapper holds one private lifetime connection; short readiness and `/split` requests
are not leases. Final release acknowledges after existing cleanup. Captured host
environment travels over the private socket, not tmux arguments. The extension
copies context and starts the fixed wrapper with the existing worker connector;
there is no native command interception, Pi patch, durable attachment registry,
or second subagent manager.

Verify on disposable resources:
- B has a fresh session ID and completed source context, uses A's worker, and leaves
  A's running work unchanged. No container creation or pending-call replay occurs.
- Closing either pane first preserves its peer; final release cleans the workload.
  Include source exit during pane startup and parent-bounded ordinary subagents.
- Failed startup leaves A usable. Worker loss has no host-local fallback;
  `/cd` from surviving panes preserves peers and existing cleanup rules.

=== Model-requested session forks <sandbox-session-forks>

A sandboxed agent may request a host-managed fork of its current conversation.
For example, a fork can investigate a second approach using copied context while
its file reads and shell commands still run in the parent's guest worker.
This creates a conversation branch, not a new execution environment or authority.
Unlike human #link(<interactive-side>)[side panes], these forks remain
children of the invoking Pi and do not acquire independent attachments.

Pi owns copying the current branch into a fresh session ID through its session
APIs. The trusted child manager starts and tracks the fork using the same backend
and attachment inheritance as subagents. The host resolves the source from the
requesting session; model input cannot select a host transcript path, executable,
environment, repository, mount, credential source, or attachment.

Copied messages, paths, and tool results remain untrusted context. Do not copy
live child handles, pending tool calls, or executable extension state. A fork
loads only admitted host code and guest-view resources, retains the parent's
accepted capability set, and uses the same authenticated provider routes.
A fork request cannot invoke `/cd` or reauthorize sandbox policy.

Return the new session identity after guest-tool extension loading, attachment
binding, and session creation succeed. Report startup failures and clean up child
resources through the existing manager. Forks share the normal-operation routing
and failed-reload limitation above. The child manager owns cancellation and
cleanup; the fork cannot outlive the attachment that supplies its tools. This is
a selected capability, not an implemented fork API.

=== Execution migration and acceptance

Required acceptance checks are:

- Built-in read, write, edit, shell, and human `!` calls use the guest during
  normal operation and after a successful `/reload`.
- A child or model-requested fork inherits the guest attachment; worker loss
  interrupts its owner, and disconnect cancels outstanding guest work.
- Forked reads and shell commands use the guest during normal operation, including
  with supported child templates and flags; a host-only fixture is inaccessible.
- A fork creates a new session ID without modifying its source or transferring
  live handles or pending calls. Failed startup cleans child resources and leaves
  the parent's session and attachment usable.
- `/cd` validates first, then releases the invoking pane's old attachment before
  starting a destination session; peer panes retain their worker. With no
  remaining attachments, old guest cleanup precedes startup. Invalid paths leave
  the old session usable. Model-originated input cannot authorize that handoff.
- Cross-directory resume forks the conversation under a fresh session ID.
- Unclassified model-executable host handlers are rejected. Guest-modified code
  cannot become host executable code through `/reload` or fork startup.
- Authenticated model requests use admitted broker routes; no reusable provider
  credentials enter guest processes, and failures never select direct fallback.

== Writable workspace authority <workspace-authority>

The trusted launcher derives one immutable description for the active workspace and one for its own `DOTFILES` checkout.
Each description binds the canonical host root, guest root, resolved Git directory/common directory, and JJ workspace/repository metadata.
Derive mounts, resource-path projection, JJ permissions, and accepted-session identity from these descriptions, not guest request fields.
This is not a user-configurable multi-repository facility.

Ordinary files in both workspaces are writable.
Protect `.git`, `.jj`, their external backing paths, and `.agents/sandbox` through every exposed alias in both checkouts.
Other `/src` siblings remain inspection-only; independent container-local repositories retain native JJ operation.
Filesystem access does not authorize unrelated edits or ownership of another contributor's changes.
The active project's accepted policy alone selects optional services and credentials; dotfiles supplies no additional service policy.

Retain the active workspace's guest path and working directory.
Prefer dotfiles' existing source-tree mapping, normally `/src/dotfiles`; otherwise allocate a destination unused by visible source entries and other mounts.
A conventional-name collision must not hide another source tree or reject a valid layout.
When the active root is dotfiles, retain its guest path and deduplicate mounts and authority.
Record the selected path once and derive all consumers from it.
Reject remaining incompatible mount destinations before container creation.
Resolve the installed skills source independently; do not retarget an intentionally different installation.

Before acquiring active-session lifetime/publication locks, the host initializes absent JJ metadata in valid Git-only dotfiles with
`jj git init --colocate` at an explicit host target, without changing launcher cwd.
Use launcher coordination and recheck absence after acquiring it; release initialization coordination before session acquisition.
Never treat malformed existing metadata as absent or replace it automatically.
Validate both layouts before starting runtime resources and report failures against the affected checkout.

One existing JJ service per active shared session receives both exact workspace roots and writable metadata; no second service is added.
Only it receives the persistent mutation-lock mounts described by #link("../../jj-proxy/design.typ")[the JJ contract].
Other command proxies retain active-project scope.

== Configuration belongs to the loader

The configuration loader reads `.agents/sandbox/proxy-commands.json` when present.
Otherwise, `.agents/sandbox/docker-bake.hcl` supplies the bundled Bake resolver with
base target `base`. The loader returns validated capability and command-execution
policy plus a bound image resolver.
It owns declaration versions, defaults, path validation, image-name bindings,
and resolver construction. Loading configuration does not invoke a resolver.

The launcher consumes that normalized policy, selects capabilities under host
authorization, supplies the admitted engine, supervises resolution, verifies
results, and starts consumers. It does not inspect JSON fields, branch on
resolver kinds, or interpret Bake targets, project commands, or cache keys.
The loader binds those details behind the resolver interface. Required installed
helpers remain in a separate trusted namespace that repository declarations
cannot replace.

JSON uses the existing Python parser and manifest format; EDN would introduce
a parser dependency. Build definitions remain in their native files, such as
Bake HCL. A repository using the bundled resolver declares:

```json
{
  "version": 2,
  "capabilities": {
    "nested-containers": true,
    "flower-r2": false
  },
  "images": {
    "resolver": {
      "kind": "bake",
      "file": ".agents/sandbox/docker-bake.hcl"
    },
    "base": "base"
  },
  "commands": {}
}
```

A project-owned resolver replaces only `images.resolver`:

```json
{
  "kind": "command",
  "argv": ["bb", "sandbox-images"]
}
```

The command example names an illustrative project entrypoint, not an installed
command. Its argv is executed directly in the validated repository root during
resolution, never through a shell. Resolver file paths are repository-relative;
the Bake file above is not relative to the configuration file's directory.

Version 2 requires `version`; omitted `images` uses the conventional Bake file when
present and otherwise retains installed default image policy. Omitted `capabilities`
and `commands` mean empty objects. A repository with only the conventional Bake file
needs no manifest.
For example, disabling the default Zulip service needs no image declaration:

```json
{"version": 2, "capabilities": {"zulip": false}}
```

The retired boolean `host-editor` declaration is accepted and discarded during
normalization; it selects no service. Prompt editing uses host Pi's native editor.

Capability values are booleans. `zulip` defaults on;
explicit `false` disables it. `nested-containers` and `flower-r2` default off.
The #link("tic-proxy.typ")[`tic` capability] defaults on for new sessions; raw version 1 and version 2 accept its boolean, and explicit `false` opts out.
It selects a launcher-resolved host broker with best-effort `agent-launch` startup, not a project command or native-TicGit image.
Reject explicit `tic: true` with a simultaneous project `commands.tic` declaration. An implicit-default collision instead warns and selects TicGit off, preserving the project command.
Accepted session policy retains its recorded TicGit choice or absence without adding new defaults.
TicGit startup failure warns and starts Pi without its endpoint, token, guest client mount, or network attachment; the guest entrypoint reports unavailable with no native fallback.
Explicit `true` uses the same startup behavior. Once ready, request failures remain fail-closed without broker replacement or replay.
Other capabilities retain their existing authorization and required-service rules; actual Linux/macOS provider acceptance of TicGit remains unproven.
These capability keys select separate services, subject to their existing
host-authorization rules. Zulip requires available host credentials;
when disabled, it does not validate or mount those credentials. These keys cannot
disable required services or authorize an undeclared service through host
availability alone.

When present, `images` contains exactly `resolver` and `base`. The resolver is either
`{"kind": "bake", "file": STRING}`, `{"kind": "bake"}`, or
`{"kind": "command", "argv": NONEMPTY_STRING_ARRAY}`; the forms cannot be mixed.
An omitted Bake `file` means `.agents/sandbox/docker-bake.hcl`.
`base` is a nonempty resolver-owned image name. Each project command uses an
`image` field naming its image in the same resolver, replacing version 1's
`image-command`/`image-target` fields. Its `argv`, `workdir`, `network`, and
`mounts` retain the #link("proxy-design.typ")[proxy execution and mount policy].
The loader binds base and command image names to consumer roles, so the launcher
requests logical consumer images without knowing the repository's target names.
Shared names are resolved once within that invocation.
Project commands require an explicit repository resolver; omitting `images`
does not expose installed helper images through project-selected names.

Reject duplicate keys, unknown fields or optional capability names, wrong types,
mixed resolver forms, unsupported versions, and invalid protected paths before
any resolver runs. The loader applies the existing configuration trust and
path-protection rules; normalized output does not weaken those rules. A missing
configuration uses installed default image policy and Zulip when configured;
an explicit malformed configuration never falls back to defaults.

Version 2 is accepted for Bake-backed and project-command repositories. Installed
helpers remain separate. Version 1 remains temporarily supported through an explicit
adapter with the same defaults for new sessions. Accepted session policy retains
its recorded selections. Remove the adapter
after repository and standalone entrypoints migrate as described below.

== Select capabilities before resolving images

The launcher derives a fixed launch capability set from trusted repository
configuration and host authorization before invoking image resolvers. The set
contains required agent/provider services, built-in repository operations, and
optional services selected by defaults or explicit policy. Resolvers supply images; they cannot
select capabilities or expand container authority.

Flower R2 access, Zulip, and nested container access are separate optional
capabilities with the defaults above. Host availability is a prerequisite,
not a selection rule. Dotfiles can omit R2 access while paracress enables it.
Nested containers use their existing gateway. Selected capabilities retain
their existing host-authorization and failure rules.

Resolve only images reachable from selected consumers and their dependencies.
Omitted services create no listener, token, container, network, or cleanup work;
an image shared with a selected service may still be required. Required metadata
protection, provider credential isolation, and runtime admission cannot be
disabled as performance options.

=== Nested container engine <nested-container-engine>

*Implemented; full CI and macOS acceptance incomplete:* Sandbox infrastructure and agent build
workloads use rootless Docker. The build role is owned by
`tools/agent-docker/vm.py`; persisted Agent Podman state remains separate.

Use two separate Lima VMs on Linux and macOS. The infrastructure VM owns the
agent container, trusted proxies, and credential helpers. The build VM owns
the rootless Docker daemon exposed through `nested-containers`.
Reusing the infrastructure daemon would let an agent inspect or replace its
own sandbox and trusted services; rootless operation does not remove that authority.

Reuse the Docker VM provisioning source for engine installation and lifecycle,
with an explicit build role. The build role must disable host filesystem shares,
SSH-agent forwarding, and host credential injection. Give it a dedicated
non-sudo build account. Agent access must not include the VM administrator's
SSH identity or VM lifecycle controls. Preserve restrictions on host and private
network access while allowing public image and dependency downloads.

Keep the authenticated SSH gateway, but connect it to the build account's
Docker socket. Package a real Docker CLI in the agent image and replace the
Podman client and transport assumptions. Never mount or forward the
infrastructure daemon socket into the agent. Each role owns separate engine
state, images, volumes, and service readiness; shared provisioning code does
not imply shared daemon authority.

The Woodpecker adapter must stage the caller's repository in the build VM and
run the real CLI beside that Docker daemon, where bind sources exist.
Preserve its repository-independent path handling, exit status, cancellation,
and per-run cleanup. Replace Podman socket/service assumptions and its SELinux
relabel helper with the selected Docker backend's workspace-sharing behavior.
The existing adapter contract is described in
#link("../../agent-podman/ci-design.typ")[the local CI design].

If `nested-containers` is selected but build-service access is absent, warn
with the missing prerequisite and host setup action. Continue without that
optional service; do not select a local socket or another engine as a fallback.

Acceptance requires Linux and macOS provisioning and restart checks, successful
`docker info` from the agent, a complete Flower `bb test ci` run through the
staged Woodpecker adapter, and cancellation/cleanup checks. Verify that the
agent cannot access the infrastructure daemon, administrator credentials, host
shares, or restricted network destinations through the build VM.
The backend transition must update repository callers, wrappers, setup and
recovery documentation, and tests together. Do not silently reinterpret
persisted Podman access state as Docker state.

=== Shared-session capability authority

A shared session begins with the first sandbox for a checkout and ends when its
last execution attachment closes. The host-Pi mode uses the handoff rules above. Starting
another sandbox for that checkout is a join.
The first launch accepts repository configuration and resolves its selected images.
Session metadata retains the normalized configuration, including source absence,
verified image set, and image-bound launch parameters outside agent-writable mounts.
Accepted authority also binds the exact writable workspace set, metadata layouts, and persistent JJ request-lock mounts.
Joins verify these descriptions against live mounts and trusted startup environment; new worker mounts alone cannot add authority.

A join uses that accepted configuration and image set. It neither reloads repository
sandbox configuration nor invokes image resolvers. Configuration and source edits,
including a newly created or malformed manifest, take effect only at the next
shared session's trusted startup; they do not reject an otherwise valid join.
This is session authority, not a freshness cache across independent sessions.

Validate recorded runtime ownership, provider compatibility, image availability,
platform, protected mounts, and live shared services before attaching. Missing or
invalid session state fails the join without rebuilding, falling back to current
configuration, or disturbing existing agents. Legacy records lacking the accepted
configuration or images require active agents to exit before a new session starts.
Image-bound UID and GID must match the recorded agent image parameters.
The launcher passes `TERM` in each agent container's runtime environment, using
`xterm-256color` when unset. Terminal choice affects neither image identity nor
join compatibility.

Optional relays use the accepted repository opt-ins and current host authorization,
which may narrow authority. Their resources and tokens remain per-launch.
Agent instructions, skills, and admitted extensions may reload with `/reload`; this does not restage guest configuration or reload
sandbox configuration, images, workspace authority, or shared services.
Editing tracked configuration in writable dotfiles does not reload its staged copy.
Deploy shared-dotfiles support with rebuilt guest/proxy images and fresh sandboxes; `/reload` is insufficient.
Existing accepted sessions lacking workspace authority reject new joins without disturbing running attachments.

== One launcher interface

Each image set is supplied by a resolver, bound to its build definition or project
command and any required launch parameters. The common contract is conceptually:

```text
resolve(engine, requested) -> {name: immutable image reference}
```

The loader binds the resolver; the launcher supplies the admitted engine,
supervises execution, and verifies every returned image's availability and platform.
At the launcher boundary, requested names identify logical consumers. The bound
adapter translates them to repository resolver names, deduplicates shared names,
validates the repository result against that translated set, and maps the images
back to logical consumers. Bake targets and project image names never cross
into launcher orchestration. The resolver obtains the platform from the engine.
At each boundary the result contains exactly that boundary's requested names,
each identifying an immutable image in that engine, not a mutable tag or source
cache key. Machine-readable results and diagnostics use separate channels.

An external resolver receives one versioned JSON request on stdin:

```json
{
  "version": 1,
  "operation": "resolve",
  "engine": {"provider": "lima-docker", "platform": "linux/arm64"},
  "images": ["base", "bug-proxy"]
}
```

`operation` is `resolve`, `refresh`, or `clean`; image names are unique, sorted,
and nonempty. `refresh` updates modeled mutable upstream identities before resolving,
while `clean` rebuilds the requested closure without resolver build-cache reuse.
The resolver writes exactly one JSON value to stdout, followed by optional whitespace:

```json
{"version": 1, "images": {"base": "sha256:...", "bug-proxy": "repo@sha256:..."}}
```

The result object contains exactly `version` and `images`, and its image keys equal
the request. A zero exit with malformed, duplicate-key, trailing, or oversized
output fails resolution. Stdout is limited to 1 MiB and stderr to 8 MiB; exceeding
either limit cancels the resolver. Diagnostics belong on stderr. A nonzero exit is
a resolver failure regardless of stdout, and the launcher reports bounded stderr
without interpreting it as machine state.

The launcher passes the request on stdin and executes configured argv directly in
the repository root. It exports `CODEX_SANDBOX_RUNTIME` and, when applicable,
`CODEX_SANDBOX_DOCKER_STATE` or `CODEX_SANDBOX_LIMA_STATE`; these identify the
already admitted engine used by
`sandbox-image`. The resolver may invoke that installed tool but cannot replace the
provider, state, or platform named in the request. Every returned reference is
inspected in that same engine after the complete result shape is validated.

The launcher starts the resolver in an owned process group. Cancellation closes
stdin, sends `SIGTERM` to the group, waits up to five seconds, then sends `SIGKILL`
and waits for output pipes and the group leader. A resolver must keep engine work in
that group and finish its snapshots, locks, and temporary-resource cleanup before
exiting; detached engine work is a contract violation. Launcher cleanup retains
resolver-owned resources until this join completes.

Invoke each required resolver at the first launch of each shared session. It alone owns input selection, caching,
building or pulling, concurrent cache publication, and refresh; the launcher
does not cache around it or choose how it builds. Cache hits should be quiet.
Explicit refresh and clean rebuilding use the same request contract through the
standalone `sandbox-image refresh` and `sandbox-image clean` routes.

The loader constructs either the bundled Bake resolver or a project-command
adapter implementing this contract. Declaration-specific names stay inside it.

== Bundled Bake resolver

For a simple repository, a small directory containing its Dockerfile is sufficient:

```hcl
target "base" {
  context = ".agents/sandbox/base"
}
```

The resolver uses the engine's platform and assigns private tags and local
outputs. Repositories do not repeat platform defaults or calculate hash tags.
The bundled resolver guarantees that reused images match its local build inputs,
that builds use the bytes represented by their cache identity, and that unchanged
inputs take a quiet path without a BuildKit solve when the corresponding image
remains available. Its context restrictions and cache algorithm belong in
#link("bake-resolver.typ")[the Bake resolver note].

== Project resolver

Paracress already uses image hashes for CI registry identities and publication,
and derives inputs from tool configuration and generated prefetch files. It keeps
that machinery and its source layout. Requiring shared context directories here
would introduce a competing owner for an existing project responsibility.

The project owns cache correctness and any registry effects; an ordinary launch
request does not itself authorize publishing images. The launcher cannot prove
the project's source key is complete. Tests for omitted inputs and stale results
remain the project's responsibility.

== Dependencies stay inside resolvers

Bake resolves its target graph; paracress resolves its image graph. Composition
also stays inside resolvers: the launch orchestrator needs no generic build graph.

At shared-session creation, on every supported backend, a launcher-owned agent-image resolver calls the repository's configured resolver
(bundled Bake or project command) once with the base and all selected project
proxy targets. It verifies that image set,
then builds or reuses the final agent image and returns it with the proxy images.
The launcher binds the intended UID and GID into this resolver before
invocation. The resolver owns the agent build definition and includes those
parameters and the actual base-image identity in its cache key. It invokes the
repository resolver even when an agent image is cached, so its owner can detect
changed inputs.

Both stages use the same admitted engine and remain under launcher supervision.
The repository resolver owns freshness; the agent-image resolver owns invalidation
of the final image, including when the base changes under an unchanged project
source key. This composition returns the requested image set through the same contract;
neither a shared source layout nor a common cache-key algorithm is required.

Shared dependency work stays inside that invocation: paracress resolves its base
once for both the agent and bug-proxy consumers. The launcher does not introduce
cross-resolver memoization, a shared launch-context API, or a generic dependency
graph. Independent resolver invocations remain concurrent. A new shared session
invokes its required resolvers again; joins reuse the accepted image set.

== Shared lifecycle

Resolve and verify required images at shared-session creation; joins verify the
recorded images before starting their agent and selected per-launch relays.
Launcher-owned authentication and repository-operation helpers have a separate
definition namespace; project declarations cannot replace them.

The launcher supervises resolver process trees and coordinates progress output.
Resolvers retain responsibility for their temporary build resources until their
children stop; launcher cleanup waits for cancellation to finish. Engine failures
are errors, not cache misses.

== Ordinary resolution and explicit refresh

Ordinary resolution reuses verified local images without polling mutable upstream
tags. It may build missing images or pull a missing image pinned by immutable
digest. If a missing build dependency is specified only by a mutable tag, its
first acquisition may resolve that tag; the resolver records the immutable result
and uses it for subsequent reuse until refresh. Unavailable engine state remains
an error rather than permission to pull, rebuild, or switch engines.

Explicit refresh rechecks mutable upstream dependencies and invalidates affected
results according to the resolver's documented policy, preserving valid build
caches. Cache bypass belongs to an explicit clean-rebuild operation. Refresh
does not imply refetching untracked external state inside cached build steps;
the resolver documents that limit and when a clean rebuild is needed.
Registry publication is
a separate authorized project operation, never an implicit launch or refresh
effect. Project resolvers keep their registry identities and publication tooling.

Local source identity is a reuse policy, not proof of reproducibility or upstream
freshness. Each resolver documents which external state its refresh command
updates and reports refresh failures through that command. Refresh affects future
shared sessions; it does not change the accepted images of an active session.

== Compatibility and migration

#table(
  columns: (1.2fr, 1.8fr, 2.5fr),
  [Input or backend], [During migration], [Required final state],
  [No project configuration], [Installed base and helpers; configured Zulip; no project commands.], [Unchanged. Source absence is recorded in shared-session metadata.],
  [Version 1 `image-command`], [Adapt each command as a single-name legacy resolver; apply defaults to new sessions.], [Migrate to one version 2 command resolver and `image` bindings.],
  [Version 1 `image-target` and producer-style `bake`], [Adapt targets behind the bundled resolver on Lima-Docker only.], [Migrate to version 2 `images.resolver` and remove `.agents/sandbox/bake`.],
  [Executable `base-image`], [Retain only on providers already supporting it; reject combinations with version 2 `images`.], [Bind `images.base` through the version 2 resolver.],
  [Standalone `sandbox-image resolve` and `build`], [Retain as engine primitives for legacy callers and project resolvers.], [Add `refresh` and `clean` as resolver operations; engine primitives remain available.],
  [Podman], [Version 2 command resolver and legacy executable builders.], [Command resolver; bundled Bake is rejected before invocation.],
  [Lima-containerd], [Version 2 command resolver and legacy executable builders.], [Command resolver; bundled Bake is rejected before invocation.],
  [Lima-Docker], [Version 2 command or bundled Bake resolver; explicit legacy adapters.], [Both resolver kinds.],
)

Old and new image declarations never merge. Version 2 rejects `image-command`,
`image-target`, producer-style `bake`, and executable `base-image`; version 1 rejects
version 2 `images`, `image`, and capabilities unavailable under its migration policy.
Version 1 source manifests reject `images` even when null; enabling `flower-r2` requires version 2.
Defaults in trusted normalized shared-session snapshots are not raw source selections.
An unsupported resolver/backend pair fails during policy binding, before resolver or
relay effects. Shared-session schema 4 stores accepted normalized policy, source
presence, verified images, provider selection, image-bound parameters, and the
complete trusted-service set.
Shared-dotfiles authority requires an explicitly versioned extension binding the workspace descriptions and request-lock mounts above.
Do not reinterpret schema 4 records lacking that authority as compatible sessions.
Active legacy records reject the join without reading current configuration or disturbing their holders.
Legacy records remain parseable only for owner-validated stale recovery. Final-holder
cleanup permits the next launch to migrate from current configuration.

The #link("tic-proxy.typ")[TicGit broker] uses accepted workspace capability authority with best-effort startup and `agent-launch` lifetime.
Each launch owns a fresh broker endpoint and token; joins reuse the accepted `tic` selection, not another launch's broker.
Ordinary children and `/split` peers use their owning launch's broker until final attachment release, not one broker per turn or request.
The launcher retains a private lifetime-pipe write end that unrelated children do not inherit.
On EOF, the broker closes its listener, cancels and reaps its active native child, then exits.
No durable PID record authorizes later process adoption or killing.
The #link("trusted-service-lifecycle.typ")[lifecycle contract] owns readiness and cleanup of any provider-owned relay resources.
The capability requests no native-TicGit image; guest transport helpers, if needed, use installed helper ownership.
The TicGit contract owns fixed cwd/store selection, request normalization, repository support restrictions, and native outcome semantics.
Native host calls need no sandbox endpoint; separate brokers may use the same SQLite database without sharing endpoint ownership.

== Acceptance evidence

- Equivalent Bake and project-command configurations produce the same normalized
  policy and logical image requests; the launcher requires no declaration-kind
  branches. Invalid configuration invokes neither resolver nor consumer.
- An omitted optional service invokes no exclusive resolver and creates no resources.
- Agent and proxy consumers sharing a base resolve it once at shared-session creation
  and use the same immutable identity; the next shared session rechecks freshness.
- A resolver returns exactly its requested image names; incomplete or unexpected
  results fail before any consuming container starts.
- Cache hits avoid BuildKit solves; pruning the image triggers recovery through
  its resolver at new shared-session startup without treating engine failures as misses.
  A join missing a recorded image fails without invoking a resolver.
- Base changes invalidate the final agent image even under an unchanged project
  source key; UID, GID, platform, and engine changes cannot reuse a wrong result.
- Agents with different `TERM` values join the same shared session using the same
  image without invoking resolvers; each receives its own runtime value.
- Ordinary local reuse performs no upstream tag polling or publication; explicit
  refresh reports failure rather than quietly returning the previous image.
- Refresh preserves valid build caches; a clean rebuild explicitly bypasses them.
- Cancellation joins resolver descendants and their temporary-resource cleanup
  before launcher cleanup proceeds; required proxy readiness still precedes use.
- Shared-session joins invoke no image resolvers and reuse accepted configuration,
  images, and provider state even after repository configuration or source changes.
  Runtime/provider checks and image verification still apply; mismatched image-bound
  parameters reject only the join.
- Configuration absent at first startup remains absent for joins. Configuration
  changes are accepted only after final-holder cleanup and a new trusted startup.
- Both active and dotfiles ordinary files are writable, with metadata and policy protected through every alias.
  A third sibling remains inspection-only, including an unlisted workspace sharing an authorized JJ store.
- Relocated dotfiles and conventional-name collisions preserve the active mapping and project resource paths.
  When dotfiles is active, one authority and one mount per destination remain.
- Git-only dotfiles initializes under host coordination; malformed metadata fails without replacement.
- Joins require the exact accepted workspace and lock authority; old records cannot gain it from newly mounted workers.
- `/reload` updates per-agent instructions, skills, and admitted extensions without restaging guest configuration or changing
  shared services, images, or sandbox authority.

Evidence inspected: `bake.py`, `owned_images.py`, and the agent-image resolver;
paracress's `src/scripts/ci/image.clj` and
`.agents/sandbox/docker-bake.hcl`. These informed the ownership split;
their existing cache policies have not been verified by this adoption.
