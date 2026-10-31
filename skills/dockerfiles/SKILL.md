---
name: dockerfiles
description: Create, edit, or review Dockerfiles and their Docker Bake build definitions. Use for container image packaging, multi-stage layouts, build performance, cache invalidation, runtime contents, and build or runtime file ownership. Not for generic application profiling, orchestration, or host Docker setup without an image-build change.
---

# Dockerfiles

Build the required runtime with the fewest necessary transformations and copies.
Preserve supported platforms, runtime behavior, and the caller's permissions.
A review request authorizes findings, not edits; building an image does not authorize publishing or deploying it.

## Trace the build and its consumers

Read the affected Dockerfiles, ignore files, Bake definitions, build wrappers, and runtime entrypoint.
When scope is omitted, follow the requested image's actual caller and selected target rather than auditing every image.
Identify the builder and exporter, target architecture, base-image identity, runtime user, and required mounted paths.
Distinguish the client machine, Docker daemon host, build container, and runtime container; the daemon may live in a VM.
Check repository-generated contexts and image cache keys too.
A wrapper that discovers inputs only through COPY instructions can miss a file after it moves to a bind mount.

Trace a source or dependency change through dependency installation, compilation, packaging, layer export, and startup.
For each expensive step, ask which inputs must invalidate it and which runtime consumer needs its output.
Use installed CLI help and current [Dockerfile semantics](https://docs.docker.com/reference/dockerfile/) when a feature or version changes the choice.

## Remove work before caching it

Follow artifacts across stage boundaries and count materialized copies, including copies inside RUN instructions.
For example, assembling a runtime tree in a build stage and then copying that tree into the final stage writes it twice.
When the packaging command can run in the final base, mount the build output read-only with RUN --mount=type=bind,from=build.
Write selected files directly to their final paths.
Keep generated output outside the mount; mount contents and writes to writable bind mounts do not become image-layer output.
Retain a separate packaging stage when it needs build-only tools or a different execution environment.
Installing those tools into the runtime can cost more than the copy it removes.

Use stages for distinct toolchains, dependency sets, and independently reusable outputs.
Keep independent tool downloads and builds on separate dependency paths so changing one version does not rebuild unrelated tools.
Share common stages when targets need the same inputs and outputs.
Do not serialize independent work into one large RUN merely to reduce instruction count.
Deleting a large tree in a later layer leaves its bytes in earlier layers; keep temporary files in mounts or create and remove them in the same RUN.

## Make invalidation match the input graph

Copy dependency manifests and lockfiles before frequently changing source files.
Include workspace manifests and configuration needed by the package manager.
Use the locked install mode and the package manager's production dependency or publication metadata rather than maintaining a second dependency list.
Limit build contexts with the appropriate .dockerignore or the repository's context owner, preserving required generated inputs and assets.
Put version arguments in the stage that consumes them and runtime-only ownership or labels after expensive work where possible.
Check inherited ARG and ENV values when a seemingly unrelated change rebuilds a stage.

Use cache mounts for repeated package downloads or compiler work that cannot be removed.
Treat cache contents as disposable: a cold build must remain correct, and architecture or toolchain changes must not reuse incompatible state.
Use sharing=locked when the package manager requires exclusive access.
COPY --link can preserve a copied layer across changes to its destination's parent layers.
It still copies files on a cache miss and cannot follow destination symlinks.
Choose it for demonstrated invalidation, not as a zero-copy promise.
Keep base pinning and refresh policy explicit; a mutable tag changing between trials can replace the toolchain and invalidate a comparison.
See [cache optimization](https://docs.docker.com/build/cache/optimize/) and [invalidation rules](https://docs.docker.com/build/cache/invalidation/).

## Build multiple targets with Docker Bake

Use docker buildx bake for multi-target builds, including related images and runtime variants.
Extend the existing Bake owner, whether it uses HCL, JSON, or Compose; do not introduce a second source of build arguments, tags, or contexts.
Define groups for the requested outputs and share common configuration through target inheritance.
Connect dependent targets with named contexts such as contexts = { base = "target:base" } so the consumer uses the producer's build result directly.
Avoid building, tagging, loading, and resolving an intermediate image solely to pass it to another build.
An internal Dockerfile stage alone does not require a separate Bake target.

Inspect the resolved definition with docker buildx bake --print before executing changed target wiring.
Check selected targets, platforms, arguments, context paths, dependency edges, and output destinations.
Choose cache-only output for build checks, engine-local output for container probes, and registry output only when publication is authorized.
Do not assume a docker-container or remote builder automatically loads its result into the runtime daemon.
If Bake is unavailable, report the missing prerequisite instead of substituting a loop of independent builds.
See [Bake target contexts and outputs](https://docs.docker.com/build/bake/reference/).

## Keep the runtime sufficient and small

Identify required executables, production dependencies, dynamic libraries, package metadata, and runtime assets before pruning.
Keep source or debugging tools when the requested product needs them; minimality does not override that requirement.
Use authoritative package file lists and preserve workspace symlinks and executable links.
Avoid retaining duplicate assets beside both a standalone binary and an SDK when both consumers can share one tree.
Keep compilers, development dependencies, package caches, and build credentials out of runtime layers unless a runtime requirement calls for them.

Check CPU architecture and libc compatibility for every executable and native module crossing stages.
A binary built on Debian does not become musl-compatible because it is copied into Alpine.
Choose a compatible runtime or the matching artifact rather than assuming a compatibility shim is sufficient.
Before choosing scratch or a smaller base, account for shared libraries, CA certificates, DNS and user lookup, and timezone data.
Include any invoked shell or helper program.
Verify actual application operations; --version alone does not exercise native modules, dynamic assets, or subprocesses.

For cross-platform builds, distinguish the platform running build tools from the artifact's target platform.
Use BUILDPLATFORM and TARGETPLATFORM deliberately when the toolchain supports cross-compilation.
Compare native cross-compilation with emulation for expensive build steps, preserving target-specific dependency selection and runtime checks.

## Resolve permissions at the correct boundary

Inspect the effective UID, GID, supplementary groups, namespace mapping, and mount ownership in the environment that fails.
Container root, guest root, the daemon account, and the client account can have different authority.
Rootless Docker and userns-remap map IDs differently; matching the client UID in USER does not by itself establish bind-mount access.
Use the actual daemon host or guest when checking mounted paths; a successful client-side ls does not prove the daemon can read them.

Set image-file ownership with COPY --chown or during artifact creation when that avoids a recursive ownership pass.
Image-file ownership does not change the ownership of a runtime bind mount that covers the path.
Keep immutable runtime files readable and executable by the runtime user and create only the required writable directories.
Account for HOME, temporary directories, caches, entrypoint execution, and mounted files under the final identity.
Test required reads and writes on disposable mounts with the intended identity and namespace mode.
Do not use recursive chown of a real checkout, chmod 777, privileged mode, or a host permission change as a speculative repair.
Establish why the actual mapping requires the change and whether existing authorization covers it before proceeding.

Use build secret or SSH mounts for credentials; ARG, ENV, and a copied credential deleted later can expose them in image layers or metadata.
Secret mounts do not prevent the build command from copying secrets into its output or cache, so inspect what that command persists.
See [UID/GID mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/) and [build secrets](https://docs.docker.com/build/building/secrets/).

## Verify the changed contract

Use the repository's isolated test environment and owned disposable contexts, images, and mounts.
Inspect resolved Bake configuration and use native build checks supported by the installed Buildx version.
Build the affected targets and exercise the packaged application under its final user, paths, platform, and libc.
Check retained assets and imports, executable and workspace links, excluded build tools, and required mounted reads or writes according to what changed.
When changing cache wiring, check one relevant invalidation and one reuse case with disposable inputs.
Do not touch the authoritative checkout to trigger a rebuild.
Do not prune shared caches or change shared image tags to manufacture a cold test.

For a performance claim, use performance-investigation to compare the changed phase and the requested build.
Keep source, base digests, toolchains, exporter, and cache state equivalent.
Include context transfer, materialization, layer export, and loading when they are part of the caller's command.
Account for overlapping stages and repeat when variance could change the conclusion.
A removed copy establishes less copying; it does not establish a particular speedup.

Finish with the changed build path, preserved runtime requirements, executed checks, and any untested target or permission environment.
Distinguish successful syntax checks, successful builds, runtime verification, and measured performance.
