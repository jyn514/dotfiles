# Always-writable dotfiles: implementation plan

## Objective

Every sandboxed Pi session can edit the launcher's dotfiles checkout and commit its own changes there without leaving its active project.
For example, when dotfiles maps to `/src/dotfiles`, an agent in `/src/other-project` edits a shared skill and runs:

```sh
jj -R /src/dotfiles commit 'root:skills/example' -m 'Improve example guidance'
```

The `root:` fileset selects paths relative to dotfiles, not the invoking project's cwd.
The active project remains the session's working directory and policy owner.

This document preserves the pre-implementation plan. Subsequent implementation evidence and its limits are recorded in [Implementation evidence](#implementation-evidence).

## Pre-implementation behavior

- `codex-sandbox` derives `DOTFILES` from its own source location and mounts only the active repository writable.
  `agent_repository_mounts()` protects Git/JJ metadata, including linked-worktree backing paths.
- `stage_skills()` independently mounts the resolved `~/.agents/skills` source writable at `/home/codex/.agents/skills`.
  `install.conf.json` normally links that directory to this checkout's `skills/`.
- `source_view.py` supplies read-only sibling browsing and scaffolds missing mountpoints without changing host source directories.
- `sandbox-proxies.py` starts one trusted JJ service for each active repository session.
  Its mounts, startup environment, and accepted-session records describe one writable repository.
- `tools/jj-proxy/client` and the Rust client's `main.rs` distinguish relative mutation cwd from absolute inspection cwd.
  `select_repository()` permits mutation only in the selected workspace; `execution_policy.rs` grants Landlock writes to that workspace and its metadata.
- `tools/jj-proxy/route.py` decides native versus proxy execution from backing mounts.
  `libexec/agent-wrappers/jj` supplies invocation-scoped identity and never retries proxy failures natively.

## Decision ledger

| Status | Decision |
| --- | --- |
| Decided | Expose the whole dotfiles working tree, not only skills, while retaining metadata and sandbox-policy protections. |
| Decided | Filesystem access does not authorize unrelated edits or committing another contributor's changes. |
| Decided for implementation | Extend the existing JJ service to accept the active workspace and dotfiles as its exact writable workspace set. Avoid another service/socket/lifecycle solely for dotfiles. |
| Decided for implementation | Preserve the active workspace's guest path. Derive dotfiles' path from the existing source mapping where possible; allocate an unused `/src` destination otherwise. `/src/dotfiles` is conventional, not mandatory. |
| Decided for implementation | Derive dotfiles from the launcher's `DOTFILES`, not cwd, a request field, or a sibling's policy. Resolve the installed skills source independently; do not retarget an intentionally different installation. |
| Decided for implementation | Reuse trusted Git-to-JJ initialization for dotfiles when JJ metadata is absent; do not require manual initialization before starting Pi. |
| Decided for implementation | Serialize mutation requests across proxies sharing a JJ backing repository, including author hooks. Independent repositories remain concurrent. |
| Decided compatibility | Launcher, clients, router, and proxy image deploy together; their internal request format can change together. Existing persisted sessions must not be reused as if they already carry the new authority. |

## Boundaries and invariants

The trusted launcher owns an immutable launch description for each authorized workspace: host root, guest root, Git directory/common directory, and JJ workspace/repository metadata.
Derive guest mounts, proxy mounts, authorization, resource-path projection, and accepted-session identity from those descriptions.
Do not add a user-configurable multi-repository facility.

The guest can write ordinary files in the active workspace and dotfiles, but cannot directly write `.git`, `.jj`, their external backing paths, or `.agents/sandbox` through any exposed alias.
The JJ service can perform its existing approved operations in either authorized workspace.
Other siblings remain inspection-only; container-local repositories remain native.
Authorization compares the resolved workspace root, not a string prefix or membership in a shared JJ store.
An unlisted linked workspace does not become writable because it shares metadata with dotfiles.

The active project's accepted policy remains authoritative for that session.
Adding dotfiles does not enable dotfiles' optional proxies, credentials, networking, or services in another project.
Staged configuration stays staged; editing its tracked source does not reload running Pi or change accepted session authority.
The launcher currently loads host-executed extensions from dotfiles, so writable dotfiles does not satisfy proxy-design's host-code source isolation requirement.
jyn explicitly approved proceeding with writable dotfiles while documenting this existing gap; host-extension deployment redesign is outside this change.

Agents share host files and JJ history, not isolated branches or transactional file ownership.
Keep the existing ownership instructions and add no automatic commits or lock spanning independent repositories.
Native JJ concurrency handling does not make the proxy's author-update/command/reset sequence atomic.
All proxies targeting the same JJ backing repository must serialize complete mutation requests, not only individual JJ subprocesses.
A cross-repository commit must not snapshot or reattribute the invoking workspace.
Linked workspaces retain JJ's shared-history semantics; do not promise history isolation between them.

## Implementation steps

### 1. Describe and mount both workspaces

In `tools/codex-sandbox/codex-sandbox`, factor repository discovery/initialization from read-only layout validation.
Retain the active repository's existing initialization behavior.
For a Git-only dotfiles checkout, reuse trusted `jj git init --colocate` with an explicit host target, without changing the launcher's cwd.
Serialize dotfiles initialization using the existing launcher coordination facility and recheck missing metadata after acquiring it.
Finish and release that coordination before acquiring the active session's lifetime/publication locks, including when dotfiles is the active workspace.
Never replace malformed existing metadata as if it were absent.
Validate both resulting layouts before starting services or containers; report failures against the affected checkout.

Extend `agent_repository_mounts()` and `source_view.py` to assemble the complete source view once, then apply the distinct writable worktrees and protected overlays.
Preserve ordinary, linked Git worktree, and linked JJ metadata handling.
When the active root is dotfiles, reuse its guest mapping and authority instead of mounting it twice.
Otherwise prefer dotfiles' existing source-tree mapping; if it is outside that tree, allocate a destination unused by the active workspace, visible source entries, metadata aliases, and other mounts.
Record the chosen path once in launch authority and derive all consumers from it.
A collision with the conventional `/src/dotfiles` name must not reject an otherwise valid checkout layout or hide an unrelated source tree.
Deduplicate identical mounts and reject any incompatible destinations remaining after allocation, before container creation.
Protect dotfiles' `.agents/sandbox` even when another repository owns the active policy.

Update `preflight_lima()` so both worktrees and all required metadata sources have the correct host/VM access.
Update `host_pi_resource_paths()` so host dotfiles paths project to the same guest checkout, including when it is outside the host source tree.
Keep `/home/codex/.agents/skills` live; verify the normal installed link and the chosen dotfiles guest path's `skills/` expose the same files.

Principal tests under `tools/codex-sandbox/tests/`: `codex_sandbox_test.py`, `source_view_test.py`, `repository_mounts_test.py`, and `repository_mounts_integration.py`.

### 2. Authorize both workspaces through the existing JJ service

In `sandbox-proxies.py`, carry the validated workspace descriptions through startup, accepted-session publication/join, cached reuse, live-resource validation, and agent argument construction.
Bind the exact writable workspace set and metadata layouts into accepted authority; guest request fields cannot add roots.
Only the trusted JJ service receives writable dotfiles metadata.
Other command proxies retain their existing project-scoped mounts.

In `tools/jj-proxy/src/main.rs` and `execution_policy.rs`, load and validate that launch authority before readiness.
Prepare secure JJ configuration for both authorized workspaces and grant Landlock the corresponding worktree and metadata access.
Keep inspection children read-only, including when inspecting an authorized workspace explicitly in read-only mode.

Separate cwd addressing from write permission in the internal request protocol.
Use a checked absolute guest cwd for both workspace roles, preserve `-R` resolution relative to the invoking cwd, and let the server select permissions from trusted workspace authority.
Update both `tools/jj-proxy/client` and the Rust client together and version the changed protocol.
Resolve/open cwd using the server's checked filesystem traversal, not an unchecked path supplied to `chdir`.

Pass the resolved target workspace explicitly to author prehooks and author reset.
Run the requested command with its checked invocation cwd and resolved repository selector, preserving native fileset interpretation.
Do not fix hook targeting by changing the requested command's cwd to the target root.
Private agent-split uses the workspace resolved from its invocation cwd.
Document root-relative filesets for scoped commits from another project, and test invocation-relative filesets against native JJ.

#### Cross-proxy mutation ownership

Create persistent launcher-owned request-lock files and mount the relevant files into each trusted JJ service, not the guest.
Derive lock identity from the canonical host JJ backing repository, so separate project sessions and linked workspaces sharing a store acquire the same lock.
Use the existing file-locking approach; process-local mutexes and the active project's session lock do not coordinate different proxy services.
Retain lock-file identity across service cleanup and restart; never unlink or replace a lock file while another service can use it.
Include the lock mounts in accepted authority, live-resource validation, VM bind preflight, and Landlock access.

Acquire the target repository's lock before any mutating JJ action, including author prehooks, and release it after the command and applicable author reset finish.
Cover all mutation-mode requests: another request's `new`, `edit`, or commit must not run between a prehook and its command.
Secure-config preparation at proxy startup uses the same repository lock.
Hold at most one repository request lock at a time; never hold it for a session's lifetime or while waiting for another repository's lock.
Read-only inspection needs no mutation lock.

Bound lock acquisition and the protected sequence by one request deadline within the client's response timeout.
On lock-wait timeout or cancellation, return without running a prehook or command.
On command failure or timeout, stop and reap its process group before releasing the lock; preserve the existing conditional author-reset behavior.
Closing the owning descriptor releases the lock after normal exit or process death.
This coordinates trusted proxy requests, not arbitrary host commands or concurrent source-file edits.

Retain policy restrictions, request/output limits, and no native fallback.
Change `route.py` only where two worktree mounts or aliases require it; keep it routing evidence, not authorization.

Principal tests: `tools/jj-proxy/src/main.rs`, `tools/jj-proxy/tests/{execution_policy.rs,jj_proxy_client_test.py,jj_route_test.py}`, `tests/agent-wrappers/{jj_dispatch_test.py,jj_wrapper_test.py}`, and `tools/codex-sandbox/tests/{sandbox_proxies_test.py,proxy_session_test.py}`.

### 3. Document and prove the complete path

Update `tools/codex-sandbox/README.md`, `config/agents/sandbox-AGENTS.md`, and `tools/jj-proxy/README.md` with writable dotfiles, scoped commits, unchanged staged configuration, and deployment requirements.
Document automatic Git-to-JJ initialization and the authoritative guest path rather than promising that dotfiles always appears at `/src/dotfiles`.
Update the existing mount, accepted-authority, and JJ permission contracts in `tools/codex-sandbox/spec/{launcher-interface.typ,proxy-design.typ}` and `tools/jj-proxy/design.typ`.
Follow the repository's Typst skill when editing those specifications.

Extend the existing disposable container integration suites to exercise the launcher-produced mounts and trusted proxy with two real fixture repositories.
Do not test commits against the authoritative checkout or real user skills.

## Execution and failure lifecycle

- Setup initializes missing JJ metadata in a valid Git-only dotfiles checkout, then validates both layouts and mount destinations before starting runtime resources.
  Malformed existing metadata or initialization failure stops startup with a checkout-specific diagnostic; retry revalidates any partial initialization.
- Readiness requires both workspace authorities and secure configuration to be usable.
  Publish accepted session state only through the existing lifecycle after readiness succeeds.
- Joining/reusing a session verifies its exact accepted workspace authority and live mounts/environment.
  An old or mismatched session cannot gain authority from a new worker's mounts alone.
  Preserve running sessions; report that a fresh compatible session is required when joining cannot satisfy the contract.
- Use the existing resource registry, readiness deadlines, and cleanup ownership for startup failure, cancellation, normal shutdown, and stale-session recovery.
  There is no second service to stop and no new replay mechanism.
- A timeout or disconnect can leave an operation applied without its response being received.
  Do not replay it automatically; inspect the target repository before deciding whether to retry.
- Deploy with rebuilt guest/proxy images and fresh sessions; `/reload` cannot replace mounts or the proxy's startup authority.

## Acceptance and verification

| Case | Required observation |
| --- | --- |
| Active project differs from dotfiles | Ordinary files in both worktrees are writable; a third sibling remains read-only. |
| Shared skills use the normal installed link | Editing the skills alias changes `skills/` in the mapped checkout; a root-relative, path-scoped commit contains that edit and excludes unrelated fixture edits. |
| cwd in project; absolute or relative `-R` selects dotfiles | A `root:` fileset commits the selected dotfiles path; project operation/working-copy author state is unchanged. |
| Cross-repository filesets | Native and proxy commands agree on invocation-relative paths and errors; `root:` selects target-relative paths without changing cwd. |
| cwd in dotfiles; selector chooses project | Same target-scoped behavior in the other direction. |
| Private agent-split runs in dotfiles | Split and attribution affect dotfiles only. |
| Active workspace equals dotfiles | One workspace authority and one mount per destination; ordinary commands still work. |
| Alternate host dotfiles location | Guest resource projection, writable mount, and proxy authority all identify the launcher checkout, not a hard-coded host sibling. |
| Conventional dotfiles guest path is occupied by another project | The active mapping and visible source entries remain intact; dotfiles receives a nonconflicting mapping and commits work through it. |
| Relocated dotfiles is itself the active workspace | Reuse the active guest mapping and one authority without requiring `/src/dotfiles`. |
| Git-only dotfiles; repeat and concurrent startup | Trusted initialization succeeds without manual setup; subsequent launches preserve metadata and simultaneous launchers recheck under coordination. |
| Read-only `validate-cd` | Validate only existing destination metadata; do not inspect or initialize dotfiles, create locks, or publish temporary authority. |
| Malformed metadata or interrupted initialization | Startup fails without replacement; retry validates the retained state and reports any repair required. |
| Linked metadata or source aliases | Real Git/JJ discovery works; direct guest writes to metadata/policy fail through every exposed alias. |
| Unlisted sibling or linked workspace | Inspection works where metadata is visible; mutation is rejected even if it shares an authorized store. |
| Temporary container-local repository | Native initialization and commits still work without proxy access. |
| Forged root, escaping cwd/selector, or conflicting mount | Rejected without writing either workspace. |
| Old/mismatched accepted session or proxy failure | No privilege widening, native fallback, or replay; owned startup resources are cleaned up. |
| Distinct proxy services and model identities share dotfiles | Pause A after its author prehook; B cannot enter a mutating JJ action until A's command/reset completes. Both commits retain their invoking identities and unrelated fixture edits. |
| Waiting request, service termination, and restart | A waiter times out or cancels without mutation; process termination releases ownership, and restarted services use the same lock identity. |
| Independent JJ backing repositories | Mutation in one proceeds while another holds its request lock; no cross-repository atomicity is promised. |

Use table-driven behavioral cases for these finite decisions, not source-text assertions or a new property-testing dependency.
Include a relocated dotfiles fixture to prove consumers derive paths from launch authority.
Use actual containers for mount enforcement and shared locking on each supported runtime, and real JJ for commit contents, attribution, and concurrent operations.
The concurrency test must use two distinct proxy services, not two requests serialized by one server's accept loop.
Also race a non-hook mutation against A's paused prehook to prove the lock covers all mutation-mode requests.
Mocked command construction or a host-only lock test does not establish cross-container locking.

Run focused suites through `dev/test-environment` or `dev/pytest`, then the existing top-level discovery route.
The native JJ suite is `tests/native/test_native_jj_proxy.py`; Python proxy tests live under `tools/jj-proxy/tests`.
Extend `tools/codex-sandbox/tests/repository_mounts_integration.py` and `image_runtime_integration.py --jj-only` rather than adding a parallel test launcher.
Record unavailable runtimes, Landlock, binaries, and skipped cases as verification limits.

## Logical commits and readiness

Prefer one coherent behavior commit, **Allow sandboxed agents to commit shared dotfiles changes**, containing mounts, proxy authority/protocol, tests, and canonical documentation.
A mount-only intermediate commit would expose write access while still refusing the operation this change exists to support.
Split a preparatory layout extraction only if it is independently useful and preserves current behavior under existing tests.
Do not commit the plan or unrelated working-copy changes without a separate request.

The working copy has changed revisions since this plan was first written.
Recheck status and hunk ownership before implementation; do not resolve or include unrelated changes incidentally.
Plan review used disposable real-JJ probes: `A prehook → B prehook → A commit` recorded B as author and A as committer; invocation-relative `skills/example` failed from another repository while `root:skills/example` succeeded.
These probes justify the lock and fileset requirements but do not verify the planned implementation.
Planning and review did not change implementation files.
The subsequent user request authorizes implementation; evidence and outstanding runtime checks belong below.

## Implementation evidence

The implementation adds one workspace-description owner, uses it for guest/proxy mounts and accepted authority, and upgrades both clients and the trusted server to protocol 2.
It serializes full mutation sequences by backing-store identity, checks disconnected lock waiters before mutation, and bounds startup preparation consistently with the manager's readiness wait.
Read-only directory validation remains separate from startup initialization.

- Local-only: focused launcher, workspace, client/router, wrapper, and proxy authority/cleanup tests passed; the Rust suite passed 47 tests with real JJ and Landlock cases.
- Local-only fixture corrections: native JJ checks cover ordinary/absolute-linked fixture creation, attribution selectors, and scoped diff paths.
  Fixture generation and JJ discovery now use the consuming image, not host JJ; native Git discovery reads an exported disposable snapshot.
- Host-verified, reported by jyn on October 18, 2026: the final `image_runtime_integration.py --jj-only` run works.
  Both ordinary metadata and linked absolute-pointer bind aliases report PASS for two roots, cross-proxy attribution/locking, scoped filesets, sibling inspection, and guest protection.
  These results use the final image-owned fixture setup and establish the container boundary, not merely native-only or mocked behavior.
- This session's Docker relay remains unavailable; the final container evidence comes from jyn's host run.
- The complete sandbox test discovery route also reaches existing cleanup tests that contact Docker; its result remains incomplete while that relay is unavailable.

No authoritative user checkout, shared service, or existing session is used as a mutation fixture.
No live sandbox restarts were performed for this change.
