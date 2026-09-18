= Sandbox launcher: execution and image ownership

*Status:* Capability declarations, gating, bounded project-command transport,
captured Bake inputs, explicit refresh and clean rebuild, and schema 4
accepted-authority joins are implemented. Version 1 declaration adapters and
pre-schema-4 recovery remain for migration; active legacy sessions cannot join.
Host Pi with guest tool execution is the launcher default; set
`CODEX_SANDBOX_HOST_PI=0` for the retained guest-Pi path. The host path has
not passed every acceptance check below.
This is the canonical execution-attachment, capability-selection, and image-resolution contract for
#link("proxy-design.typ")[the sandbox launcher specification]. It supersedes
the implemented image-command/image-target split, not the proxy trust or
transport contracts. Adopted from the maintainers-ai-guide sketch of 2026-09-12.

Keep ordinary launches quiet and avoid BuildKit solves when images are reusable.
Simple repositories should declare builds without cache code; projects with an
existing image lifecycle retain ownership of it.

== Host Pi and guest execution <host-pi-execution>

The parent Pi and its Pi subagents run on the host. Pi owns conversation
persistence, model requests, and UI; the launcher owns execution attachments,
and the tool backend executes arbitrary model-selected filesystem and process
operations inside the guest. Other Pi extensions retain their host authority;
launcher-owned bounded operations follow the
#link("proxy-design.typ")[extension authority contract].

An execution attachment binds one Pi launch and its children to one guest worker
and directory. The launcher selects the repository and guest mount; repository
tool arguments use guest paths. Host-discovered shared skills are also mounted
at their host absolute path so guest tools can read the paths Pi advertises.
A saved conversation's cwd is historical context, not a request to mount that
directory. Cross-directory resume forks into a new session ID under the selected
launch directory.

The host backend sends structured tool calls to a persistent guest worker and
returns progress, text, images, errors, and completion to Pi. Through this
attachment, it reuses Pi's guest tool implementations for normal built-in and
`!` calls; backend absence or guest failure returns an error. A failed extension
reload may restore Pi's local fallback. This path is not a malicious-code
security boundary.
Cancellation requirements belong to
#link("process-ownership.typ")[process ownership].

=== Directory changes and attachment lifetime

`/cd` is a Pi command handled from human input. It validates an existing
Jujutsu workspace before stopping the current session.

`/cd` is a session handoff, including changes within the same repository:

+ Check the destination path without creating resources. An invalid path leaves
  the current session usable.
+ Abort and settle the current turn, then shut down Pi and its child manager.
  Close the old guest attachment before starting the destination.
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

Only one attachment is owned by this handoff at a time. Destination startup or
session creation failure runs ordinary failed-start cleanup. Preserve the saved
conversation; retain recovery records only for resources whose cleanup failed.
Report failure without claiming rollback or automatically resuming the old session.
The launcher owns the attachment until guest cleanup finishes; shared-session
locks and per-launch services follow that existing cleanup path.

=== Subagents without a second lifecycle implementation

Keep the subagent extension's host process manager, RPC pipes, transcripts, and
overlay sockets. The child wrapper adds the same guest-tool extension and inherits
the attachment; the guest process does not receive host Pi credentials.

Use the existing `PI_SUBAGENT_PI_BIN` entrypoint override. The wrapper launches
host Pi with the guest-tool extension; it does not own a second guest Pi process.

=== Execution migration and acceptance

Operational acceptance checks are:

- Built-in read, write, edit, shell, and human `!` calls use the guest during
  normal operation and after a successful `/reload`.
- A child Pi process inherits the guest attachment; worker loss interrupts its
  owner, and disconnect cancels outstanding guest work.
- `/cd` validates first, then closes the old guest before starting a new session
  in the destination; invalid paths leave the old session usable.
- Cross-directory resume forks the conversation under a fresh session ID.
- Host Pi uses its existing credentials directly; they are not mounted into
  the guest. A failed extension reload may restore host-local execution.

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
    "host-editor": true,
    "nested-containers": true,
    "flower-r2": false,
    "agent-room": false
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
For example, disabling the two default services needs no image declaration:

```json
{"version": 2, "capabilities": {"host-editor": false, "zulip": false}}
```

Capability values are booleans. `host-editor` and `zulip` default on;
explicit `false` disables either. `nested-containers`, `flower-r2`, and `agent-room` default off.
These five keys select separate services, subject to their existing
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
configuration uses installed default image policy, host editing, and Zulip when configured;
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

Flower R2 access, host editing, Zulip, nested container access, and agent-room are separate optional
capabilities with the defaults above. Host availability is a prerequisite,
not a selection rule. Dotfiles can omit R2 access while paracress enables it.
Host editing, nested containers, and agent-room may share their existing gateway when any
is selected; none selected means no gateway. Selected capabilities retain
their existing host-authorization and failure rules.

Resolve only images reachable from selected consumers and their dependencies.
Omitted services create no listener, token, container, network, or cleanup work;
an image shared with a selected service may still be required. Required metadata
protection, provider credential isolation, and runtime admission cannot be
disabled as performance options.

A shared session begins with the first sandbox for a checkout and ends when its
last execution attachment closes. In the implemented guest-Pi mode this follows
agent exit; the selected host-Pi mode uses the handoff rules above. Starting
another sandbox for that checkout is a join.
The first launch accepts repository configuration and resolves its selected images.
Session metadata retains the normalized configuration, including source absence,
verified image set, and image-bound launch parameters outside agent-writable mounts.

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
Agent instructions, skills, and extensions may reload with `/reload`; this does
not reload sandbox configuration, images, or shared services.

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

At shared-session creation, a launcher-owned agent-image resolver calls the repository's configured resolver
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
  [No project configuration], [Installed base and helpers; host editing and configured Zulip; no project commands.], [Unchanged. Source absence is recorded in shared-session metadata.],
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
An unsupported resolver/backend pair fails during policy binding, before resolver or
relay effects. Shared-session schema 4 stores accepted normalized policy, source
presence, verified images, provider selection, image-bound parameters, and the
complete trusted-service set. Joins accept only schema 4; active legacy records
reject the join without reading current configuration or disturbing their holders.
Legacy records remain parseable only for owner-validated stale recovery. Final-holder
cleanup permits the next launch to migrate from current configuration.

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
- `/reload` updates per-agent instructions, skills, and extensions without changing
  shared services or sandbox authority.

Evidence inspected: `bake.py`, `owned_images.py`, and the agent-image resolver;
paracress's `src/scripts/ci/image.clj` and
`.agents/sandbox/docker-bake.hcl`. These informed the ownership split;
their existing cache policies have not been verified by this adoption.
