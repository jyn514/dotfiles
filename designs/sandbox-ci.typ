#set document(title: "Running local CI through the sandbox Podman machine")
#set page(paper: "us-letter", margin: 1in)
#set text(font: "New Computer Modern", size: 11pt)
#set par(justify: true)

= Running local CI through the sandbox Podman machine

*Status:* Design only.

= Overview

Flower's `bb test ci` prepares a standalone repository and passes it to `woodpecker-cli exec` with `--repo-path`.
The Codex sandbox can reach a rootless Podman service in a separate machine, but that service cannot bind-mount sandbox-only paths.
The repository must therefore be available inside the Podman machine before Woodpecker starts its job containers.

The dotfiles-owned sandbox integration will provide a generic `woodpecker-cli` adapter which stages the requested repository beside the remote Podman service and runs the real Woodpecker CLI there.
Flower keeps ownership of repository preparation, pipeline selection, images, cache policy, and all arguments to Woodpecker.

This design covers local `woodpecker-cli exec` through the Podman machine exposed to a Codex sandbox.
It neither changes `bb test ci` nor defines Flower's CI pipeline.

= Motivation

Agents need to run the same `bb test ci` entry point that developers and CI use.
Hand-selected commands or jobs run directly in the Podman machine would bypass the real containerized pipeline and weaken confidence in it.
Changing Flower's task to accommodate one sandbox topology would also put environment-specific transport concerns in the project.

The remote Podman connection handles ordinary container commands, but the daemon resolves bind-mount sources in its own machine while `bb test ci` creates its candidate repository in the sandbox.
VM-local dependency caches do not solve this path-namespace mismatch: Woodpecker needs the complete repository beside the daemon.

An experimental Flower-aware wrapper proved that staging can bridge the mismatch, but coupled the dotfiles wrapper to Flower's `target/ci-build` convention and cache layout.
The proposed adapter retains repository staging while deriving everything from Woodpecker's generic `--repo-path` interface, so generic sandbox infrastructure does not own one project's CI details.

= Responsibility boundary

The adapter understands Woodpecker's command-line contract, not Flower's repository layout: it knows nothing about `target/ci-build`, Babashka tasks, Flower pipeline filenames, or how a candidate repository was produced.

The caller owns:

- creating the repository passed through `--repo-path`
- choosing the pipeline and all Woodpecker options
- defining job images, services, environment, and cache mounts
- deciding which files belong in the candidate repository

The dotfiles Podman integration owns:

- access to the Podman machine and its rootless `agentbuilder` account
- transferring an arbitrary `--repo-path` repository into the machine
- running the real Woodpecker CLI beside the remote Podman service
- rewriting paths whose meaning changes at the machine boundary
- preserving command exit status and signal behavior
- garbage-collecting staged repositories
- preparing staged directories for safe sharing between Woodpecker job containers

The adapter belongs under `libexec/agent-podman`, rather than the general agent-wrapper layer, because remote path staging and daemon placement are properties of the Podman-machine integration.

= Command behavior

For an invocation shaped like:

```sh
woodpecker-cli exec --repo-path=PATH [OPTIONS] PIPELINE
```

the adapter:

1. Parses the `exec` command and its `--repo-path` argument without assuming a particular path value.
2. Resolves the supplied repository path in the sandbox.
3. Creates an opaque per-run staging directory beneath a fixed root owned by `agentbuilder` in the Podman machine.
4. Transfers the complete repository into that directory.
5. Transfers the positional pipeline file separately when it is outside the supplied repository, as Flower's generated local and targeted pipelines are.
6. Relabels only the staged repository for shared container access through Podman's `:z` bind-mount semantics.
7. Replaces `--repo-path` and the pipeline argument with their staged paths.
8. Runs the real Woodpecker CLI under a remote supervisor in the Podman machine with all other arguments unchanged.
9. Returns the real command's exit status and removes the exact per-run staging directory after Woodpecker has stopped.

The initial adapter requires local execution with one `--repo-path` directory and one positional pipeline file.
`--local=false`, forms of `woodpecker-cli` other than `exec`, and unsupported or ambiguous path combinations fail before starting CI with an explanation.

= Repository staging

The staged directory contains the complete repository supplied by `--repo-path`; Woodpecker's job containers bind-mount it from the daemon host.

The initial implementation transfers the repository directly into a unique per-run directory rather than maintaining an incremental seed.
Avoiding shared mutable state simplifies concurrency and cleanup, and repository transfer should be small relative to CI images and dependencies.
Incremental staging may be added later if measurements justify the additional synchronization and snapshot machinery.

The remote side creates each run directory beneath a fixed mode-0700 staging root, using an opaque identifier unrelated to the caller-supplied repository name.
No invocation can update another's active directory.
The caller must keep the supplied repository stable during transfer; a future generic point-in-time snapshot mechanism may remove that requirement.

The pipeline file is staged according to its location.
When it is inside the supplied repository, the adapter preserves its repository-relative location in staging.
When it is outside the repository, the adapter copies that one file into the per-run directory and rewrites the positional argument to its staged path.
The adapter does not inspect the pipeline for additional local paths or synchronize paths referenced by its contents.

Interrupted and failed commands may leave staging directories behind.
The integration should remove completed run directories and periodically reap abandoned ones by owner and age; cleanup must never recursively target a broad or caller-supplied path.

= Caches

The adapter does not infer cache paths or preserve files from a completed staging directory.
Flower keeps dependency caches such as `target/ci-cache` inside its local Woodpecker workspace rather than in persistent volumes, so they disappear with the staging directory.

Persistent VM-local caches require an explicit caller-owned mechanism, such as named volumes passed through Woodpecker's ordinary backend-volume interface.
Adding that policy belongs to Flower or to a future generic adapter interface; it must not make the adapter recognize Flower-specific paths.

= Podman-machine execution

The real Woodpecker CLI runs as the unprivileged `agentbuilder` user inside the dedicated Podman machine, beside the rootless Podman socket where bind-mount paths are meaningful to the daemon.
The Codex sandbox reaches that account with the existing restricted credentials and does not gain root access to the Podman machine.

Woodpecker mounts the same repository workspace into separate job containers.
Rootless Podman's SELinux MCS separation otherwise prevents one job container from using content written by another even when Unix permissions allow access.
Woodpecker's Docker backend sends bind strings which could carry a `:z` option, but `woodpecker-cli exec` currently generates its `--repo-path` bind without one and exposes no option to change that generated bind.

After transfer and before Woodpecker starts, a short-lived Podman helper container binds the run directory with `:z`, labeling it as shared container content.
Woodpecker's later unadorned binds use that label, so job containers can share the workspace while SELinux process separation remains enabled.
The helper uses a pinned image already present in the machine and performs no repository operation beyond causing Podman to relabel the bind source.
Relabeling must follow every transfer or later incremental update which may introduce files with their original label.

The adapter must never relabel the staging root, an arbitrary caller-supplied remote path, or a system directory.
Per-run directories remain distinct, but their shared `container_file_t` label is not a security boundary between concurrent runs owned by `agentbuilder`.
The sandbox already has arbitrary command and Podman authority as that user, so the design treats SELinux confinement as defense in depth for ordinary job containers and never disables labels globally or per container.

= Resource configuration

The Podman machine must have enough memory and CPUs for the pipeline's intended concurrency.
The current four-GiB default is insufficient for Flower's concurrent JVM, coverage, fixture, lint, and tool jobs and can cause exit status 137 in otherwise independent lanes.

Resource sizing belongs to `agent-podman` configuration.
The adapter must not serialize or rewrite the Flower pipeline merely to fit an undersized machine.
For machine providers which cannot resize an existing VM, setup should make recreation explicit while preserving or deliberately discarding separately managed caches.

= Failure semantics and observability

The adapter should distinguish failures from:

- local repository validation
- remote staging-directory creation
- repository transfer
- SELinux relabeling
- remote command startup
- Woodpecker pipeline execution
- cleanup

Once Woodpecker starts, its output should stream directly and its exit status should remain authoritative.
Report cleanup failures without replacing a nonzero pipeline status; after a successful pipeline, cleanup may warn and leave the directory for the reaper.

A remote supervisor starts Woodpecker as its child, records the child process group beneath the run directory, and traps hangup, interrupt, and termination signals.
On interruption, the local adapter asks it to terminate the run; it signals the Woodpecker process group and waits for a bounded interval so Woodpecker can stop its containers.
The supervisor removes the staging directory only after it confirms that Woodpecker has exited.
If termination cannot be confirmed, it leaves the directory for the age-based reaper rather than deleting a workspace which running containers may still bind-mount.

Diagnostic output should show the local repository path, the opaque remote run identifier, and the remote Woodpecker exit status.
It must not print private key material or connection secrets.

= Acceptance criteria

- Flower's unchanged `bb test ci` can execute its generated candidate repository through the Podman machine
- Flower's generated pipeline may be staged independently when it is outside the candidate repository
- the adapter contains no Flower-specific paths, task names, or pipeline knowledge
- the remote daemon sees the exact repository supplied through `--repo-path`
- concurrent invocations cannot alter each other's running repository snapshots
- separate Woodpecker job containers can read and write the staged workspace with SELinux enforcing
- only the exact per-run staging directory receives the shared container label
- container label separation remains enabled globally and for every Woodpecker job container
- Woodpecker output, exit status, and termination remain visible to the caller
- abandoned staging data is bounded by safe cleanup

= Non-goals

- teaching the generic agent-wrapper layer about Flower's `target/ci-build` convention
- changing how Flower constructs its CI candidate or pipeline
- supporting `woodpecker-cli exec --local=false` or remote-repository execution
- supporting Woodpecker commands other than `exec`
- preserving Flower's workspace-local dependency caches between remote runs
- incrementally synchronizing repositories before measurements justify the complexity
- synchronizing arbitrary host paths referenced by pipeline internals
- sharing caches between unrelated Podman machines
- making the Podman machine a general-purpose multi-tenant execution host
