# Route container-local repositories to native JJ

## Objective and scope

Route ordinary `jj` commands to native JJ for independent container-local repositories, and to the existing proxy for host-backed repositories. A repository initialized under `/tmp/replay` must support commits and `bb agent-split` with the sandbox proxy mounted; a `/tmp` workspace whose `.jj/repo` points into the host checkout is not independent.

Routing is not authorization: read-only metadata mounts and server-side proxy policy remain the security boundary. Out of scope: conversation replay, repository copying, per-child guest cwd, new mounts, and expanded proxy permissions.

## Current behavior and preservation requirements

- `libexec/agent-wrappers/jj` resolves identity and the proxy socket, then always invokes `jj-proxy-client` when proxy configuration exists. Its native branch preserves author attribution and plain noninteractive diffs, but assumes the first argument is the command and omits repository selectors from author-update/reset calls.
- `tools/jj-proxy/client` encodes cwd relative to the selected repository or as an inspection path under `/src`; the server independently validates selectors and allows mutation only in its selected workspace. The sibling proxy cannot represent a guest-only cwd.
- `tools/agent-split/src/scripts/agent-split.clj` selects structured proxy splits from socket presence and suppresses operation capture/recovery whenever the proxy exists, even for a native repository.
- `tools/codex-sandbox/image/Dockerfile` installs native JJ outside PATH as `JJ_REAL=/opt/agent-tools/libexec/jj`; public aliases still use wrappers. `owned_images.py` derives image inputs from Dockerfile copies.

Preserve relevant history: `qkouryrw` keeps wrapper selection through alternate executable resolvers; `umkxxnkx` adds read-only cross-repository inspection; `ttsyloln` permits bounded selectors without mutation access to other workspaces; `lptomtzo` reads Pi identity dynamically. Agent-split's `zmluvytw` establishes one initial snapshot and revision-only later reads.

Observed October 4, 2026: the agent root filesystem is overlay; `/src` and this checkout are host-backed virtiofs; selected `.jj`/`.git` overlays are read-only. Native JJ works in disposable `/tmp`. Even `--version` from a protected repository may initialize secure config, so never use native JJ to discover a repository.

## Decision ledger

- **Decided:** preserve identity stamping, public wrapper aliases, native executable selection, proxy admission/policy, and **no native retry after proxy failure**.
- **Decided:** classify the effective repository and backing metadata—not cwd prefixes, write permission, or socket presence. Share one narrow, read-only router between the existing JJ wrapper and agent-split; add no generic mount registry or configurable backend framework.
- **Decided:** use the proxy when the target working tree or mutable metadata matches the launcher's existing host-backed repository/source views or protected metadata mounts; use native JJ otherwise. Independent repositories on the container rootfs, private tmpfs, and guest-created volumes all qualify. Unknown mount provenance alone is not an admission failure: native JJ remains subject to the same protective mounts as every other guest process.
- **Decided:** preserve configured bootstrap aliases, including `init` and `clone` from `config/jj.toml`. Read their array expansions as inert data from the same installed global configuration used by native JJ; do not maintain a second alias map or execute aliases/configuration probes to select a route.

## Boundaries and invariants

The shell wrapper owns identity selection and native invocation; a small standard-library Python helper under `tools/jj-proxy/` owns invocation selection, filesystem resolution, and classification. Its checked JSON result carries `backend` (`native` or `proxy`), the physical `workspace` (null before creation or without a workspace), the bootstrap destination when applicable, and the expanded command prefix needed by hooks. Agent-split queries this same helper with its ordinary `split` invocation and actual cwd; it does not infer the backend from socket presence. Separate machine output from diagnostics and check success before consuming it. Use no `eval`, generated shell, persistent cache, or third-party dependency.

Original argv and actual cwd define command semantics; canonical paths, inert alias expansions, and mount evidence are routing data. Preserve the original argv array for execution and never silently change cwd: `-R` must not alter relative file operands. Helper parsing selects the backend and native hooks; protected calls retain existing server parsing and policy. The helper reads configuration data, metadata, and kernel mount information only; it creates no repositories and runs no JJ/Git configuration probes. Races or routing mistakes cannot grant host write authority, so protective mounts and server validation remain mandatory.

Run each command through exactly one backend. Native tools/configuration stay inside the guest with existing permissions and credentials. Do not select host executables, modify attachment configuration, or grant daemon access.

## Design and implementation steps

### 1. Add target-aware wrapper dispatch

Principal files: `libexec/agent-wrappers/jj`, a narrow helper under `tools/jj-proxy/`, `tests/agent-wrappers/jj_wrapper_test.py`, helper tests under `tools/jj-proxy/tests/`, and `tools/codex-sandbox/image/Dockerfile`.

Parse `-R PATH`, `-RPATH`, `--repository PATH`, and `--repository=PATH`; honor `--` and option values, so message/configuration contents are not mistaken for selectors. Detect the command after global options and supported array-alias expansion. Validate recognized selectors before metadata hooks, but leave ordinary command validation to JJ and protected command admission to the server. Do not introduce a second command allowlist.

Resolve symlinks and the nearest selected `.jj` workspace. Follow `.jj/repo` directories or linked-workspace pointers, JJ Git backend `store/git_target`, and Git gitfile/`commondir` references; resolve relative references against their owning file/directory. A `/tmp` workspace pointing into protected host metadata routes to the proxy, not native JJ, even though that workspace may be unavailable in the proxy namespace.

Recognize host backing against existing launcher-selected repository/source views and protected metadata identities. Inspect the effective mount where needed, including nested/stacked mounts and mountinfo path escaping; a private tmpfs or guest volume mounted beneath a host-view pathname is not itself host backing. Do not classify every non-rootfs mount as host-backed or require proof of private ownership before invoking native JJ. Unknown storage layouts and broken references remain JJ errors unless a known host-backed path determines the proxy route; skip native hooks when their target cannot be resolved.

For bootstrap commands, inspect the destination and any explicitly shared Git backing, not the enclosing cwd repository. Resolve nonexistent destinations from existing ancestors without creating them, and match installed JJ default-destination behavior for explicit and omitted destinations. A read-only clone source alone does not make destination metadata host-backed.

`jj init /tmp/replay` and `jj clone SOURCE /tmp/replay` from a protected checkout must select the same native route as their configured `git init`/`git clone` expansions. The current agent image does not install `config/jj.toml`; include the authoritative native global configuration through the normal image/installation path so JJ and the router consume the same alias definitions. Read supported array aliases without executing them, preserve original argv, and let native JJ handle opaque aliases and normal configuration errors. Test that changing the authoritative bootstrap alias updates both consumers without editing the router. Do not relax proxy alias policy.

After classification, use only the existing native branch or proxy client. Preserve stripped-environment socket discovery and non-sandbox behavior; ordinary host use must not depend on Linux proc files or the sandbox helper. Bind native pre/post author hooks to the selected workspace: fix command detection with leading selectors and plain-diff selection. Bootstrap hooks target the created destination, never the enclosing repository. Hooks must respect explicit no-working-copy/historical-operation modes and skip nonexistent repositories for help/version. Preserve best-effort attribution and the primary command's exit status.

Before ordinary JJ parsing, recognize the existing private invocation `jj --agent-split PATCH MESSAGE REVISION`. Require exactly these four arguments; treat patch, message, and revision as opaque operands, not options. Query the workspace route without feeding the private operands through the ordinary parser. On a proxy route, resolve/export the same agent identity as ordinary commands and forward the original four arguments to `jj-proxy-client`; the client retains patch reading and serialization. On a native route, reject this proxy-only operation with an actionable diagnostic before metadata hooks, socket access, or native JJ invocation. Local agent-split uses ordinary `jj split`, not this operation.

Do not change proxy protocol, serialization, authorization, or cwd constraints. If guest-only cwd cannot be represented in the proxy namespace, report this and advise running from the mounted workspace; do not relocate invocation or grant arbitrary proxy cwd. Mixed local-workspace/host-store layouts are not automatically admitted. Package the helper and native global configuration in the agent image, verify their authoritative sources affect image cache identity, and keep all public JJ aliases routed through the wrapper.

### 2. Use the same route throughout agent-split

Principal file: `tools/agent-split/src/scripts/agent-split.clj` and existing unit/integration suites.

In `run-split!` and `current-operation-id`, consume the helper's checked backend/workspace result, not proxy presence. Local splits retain native editor/configuration invocation through `jj`. Protected splits call `jj --agent-split PATCH MESSAGE REVISION` through the wrapper branch defined above, not the proxy client directly, so runtime identity is resolved before serialization. Never send that private operation to native JJ or add arbitrary external tools to proxy policy. Keep shell/native and structured proxy implementations separate, under the same routing authority.

Native splits retain operation capture and automatic recovery even with a mounted proxy. Preserve one initial snapshot, revision-only verification, failure statuses, and helper-directory cleanup. Failed proxy splits never become native splits or recovery attempts. Restore operations only in the split repository; if recovery also fails, preserve the original verification failure.

### 3. Update documentation and integration checks with each behavior

Update `tools/jj-proxy/README.md` and `design.typ`: clarify that proxy-only commands, absolute native invocation, and failure behavior concern protected host metadata; document independent local repositories across rootfs/tmpfs/guest volumes, shared-host-store exclusions, configured bootstrap aliases, the private split branch, and unsupported cross-namespace cwd. Update `tools/agent-split/README.md` for native recovery with a proxy present. Coordinate sandbox README changes with its existing author-owned edits; do not overwrite them.

Exercise a real built agent image with existing runtime/container integration facilities. Production dispatch needs no new service or container lifecycle.

## Execution and failure lifecycle

Resolve identity and read-only route before hooks or proxy-socket access. Native commands retain terminal streams and signal behavior; interruption must not leave helper processes. Proxy timeout, disconnect, output-limit, process-group cleanup, and exit-status behavior remain unchanged.

Routing failures leave repository state untouched and emit one actionable stderr diagnostic. Proxy policy/socket failures retain existing results; never retry natively. Native JJ may leave ordinary partial effects on failure—do not restore them automatically. Preserve its failure status if attribution cleanup fails. Agent-split, not the router, owns recovery and artifact cleanup.

Recompute each invocation without global cwd changes or shared cache. Add no global lock for independent repositories; existing JJ locking and proxy serialization remain authoritative.

## Verification and logical commits

1. **Route container-local repositories to native JJ.** Commit wrapper dispatch, helper, image/configuration packaging, the private proxy-only branch, JJ docs, and tests together. Cover local commits on rootfs, private tmpfs, and guest volumes with active proxy; unchanged protected proxy calls; metadata indirections; nested/stacked mounts; literal and aliased bootstrap commands from a protected cwd; alias-authority changes; selectors/`--`; opaque private-split operands and exact arity; private-split rejection on native routes without hooks/socket/native execution; target-scoped attribution; quiet/plain diffs; non-sandbox use; stripped environments; and proxy rejection/disconnection with zero native invocations. Verify native hooks leave unselected workspaces unchanged and private proxy calls use the active Pi identity without pre-exported identity variables.
2. **Preserve local agent-split with sandbox proxy.** Commit routing integration, recovery tests, and agent-split docs together. Exercise a local split and injected post-split verification/recovery failure with proxy environment/socket present; check trees, operation state, status, cleanup, and attribution. Protected split behavior remains unchanged except that it now obtains runtime identity through the wrapper.

Before completion, run existing wrapper/client Python suites, new routing tests, `tools/agent-split/tests/run.clj` with the repository harness's installed native JJ, image-input tests, applicable sandbox integration tests, then `dev/test`. In a disposable real container demonstrate local native and protected proxy mutations, native direct-write denial against protected metadata, host inspection-only access, public aliases, and no native fallback after proxy failure. Unit fixtures cannot prove actual mount protection.

Baseline before implementation: `python3 tests/agent-wrappers/jj_wrapper_test.py` passed 6 tests; `python3 tools/jj-proxy/tests/jj_proxy_client_test.py` passed 3.

## Implementation evidence — October 4, 2026

Implementation is present; real-container acceptance is still pending. Replay and unrelated working-copy changes remain outside this implementation.

| Area and required behavior | Evidence and result |
| --- | --- |
| Effective backing: JJ/Git indirections, nested/stacked mounts, rootfs, private tmpfs, guest volumes; no ownership-proof requirement | `jj_route_test.py`: 30 tests pass. Real native probes use owned `/tmp` repositories; tmpfs/volume mount cases remain fixture evidence. Unused workspace `.git` and non-Git locators do not select the proxy. |
| Selectors, raw cwd/operands, bootstrap aliases/default destinations, target-scoped attribution, no-working-copy/historical modes | Wrapper and dispatch tests pass, including real native commits/bootstrap and author/committer checks. Boolean editor/short-option regressions preserve selectors and hook suppression. |
| One checked router result, stripped-environment discovery, no native fallback | Failed publication, multiple JSON objects, relative paths, missing helpers, proxy rejection, disconnect, and guest-only shared-store cwd tests pass; no backend runs after routing failure and no native calls follow proxy failure. |
| Private split: exact arity, opaque operands, native rejection, active identity | Dispatch tests pass. An actual client request reaches an owned Unix-socket receiver with the Pi runtime identity; the receiver is a protocol fixture, not the protected production proxy. |
| Native split/recovery with proxy present; preserve failure, operation, tree, attribution, and cleanup | Agent-split: 48 tests, 293 assertions pass. Real native split regressions cover discovery/verification launch failures and failed recovery launches. Protected routing tests establish zero native recovery attempts. |
| Packaging and documentation | Image-input tests establish router/configuration cache invalidation. Shell syntax/ShellCheck, `diff-check`, and JJ design Typst compilation pass. |
| Existing broader checks | Focused Python: 61 tests, 87 subtests pass. Rust integration targets: 5 tests pass. `dev/test` repeats the same 20 unrelated failures (1378 pass); the unchanged Rust inspection test hits protected-cwd secure-config failure or release-JJ rejection of its pinned-fork `workspace add --no-colocate` syntax. |
| Built image and enforced boundary: native/protected mutations, direct-write denial, inspection, public aliases, failure behavior | **Unverified:** no reachable container engine. Native/fixture/protocol checks do not establish the launched image's mount enforcement or real protected proxy mutation. |
