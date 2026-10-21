= TicGit command proxy

*Status:* Selected draft; not implemented.
Agents use a restricted host-native endpoint owned by their workspace session.
Ordinary host `ti` runs unmodified native TicGit through a runtime-independent storage wrapper.
Agents use Anthropic Sandbox Runtime with a dedicated writable store directory.
The storage arrangement below is the only application-behavior adaptation; otherwise accept native behavior.
Writeups remain in scope; saved views and reviews are deferred from agent access.
This design does not replace Flower's `bug` bridge, migrate tickets, or authorize implementation.

== Native behavior <tic-transactions>

Native TicGit owns parsing, validation, storage, schema creation/migration, metadata loading, rendering, and concurrency.
Accept its initialization effects, incomplete metadata results, contention errors, command interleaving, and partial mutations.
The proxy does not open SQLite, inspect schema markers, check hydration or referenced blobs, repair data, or add command transactions.
Add no external command locks, writer registry, persistent store service, or native TicGit patches.
Separate endpoints and host commands may execute concurrently; an endpoint may use a sequential request loop without store-wide serialization.
Power-loss durability and host resource containment are not required.

Runtime verification used unmodified Linux `v0.3.1`, source tag `82246613185604888c08f8f28627b18679ecfbad`,
with `git-meta-lib` `0.1.10`.
It runs in linked worktrees but uses worktree-local databases while sharing metadata refs.
Successful syncs in disposable linked-worktree tests left the databases separate and replaced the remote ticket snapshot
with one worktree's ticket set; an independent clone imported from the same remote successfully.
These observations justify sharing the database, not a native storage or synchronization reimplementation.

Disposable Linux probes verified relative and absolute database symlinks with this release, including native creation through a dangling link.
Live native file descriptors and inode identities confirmed shared database, WAL, and SHM files.
A canonical-database writer lock blocked a linked caller while an unaliased worktree could still write.
Concurrent native writes and repeated syncs retained the same ticket IDs in an independent clone.
This verifies the native mechanism, not a future wrapper or confinement; other supported host platforms still require verification.

Install one supported unmodified native build for the host wrapper and executor, with a matching installed agent policy.
Bind compatibility to build provenance, not version text alone: inspected revision `d0bda85fa593e5d4488dd13af1216b0d2766d6dc`
also reports `0.3.1` but differs from the release.
Requests never install or upgrade tools.
Replacing the accepted native build or executor requires new sessions through the existing lifecycle owner.
Host initialization, sync/import, updates, and recovery remain ordinary native operations through the same storage wrapper,
not a coordinated store-administration service.

== Shared store directory

The shared database is `ticgit-store/git-meta.sqlite` beneath the canonical host Git common directory.
The dedicated directory also contains SQLite's sidecars.
Granting this dedicated directory permits native SQLite creation and removal without granting writes to other Git metadata.
Resolve canonical absolute Git-directory and common-directory paths through Git before host invocation or agent endpoint startup.
Prepare a database symlink in both the common directory and the current checkout's Git directory, deduplicating identical locations.
Each link points directly to the database inside the dedicated directory, never through the other alias.
For conventional metadata locations:

```text
.git/git-meta.sqlite                 -> ticgit-store/git-meta.sqlite
.git/worktrees/NAME/git-meta.sqlite  -> ../../ticgit-store/git-meta.sqlite
```

Do not infer metadata locations from this example or look up the main checkout's root.
SQLite resolves each database alias and uses the dedicated directory's sidecars; create no sidecar symlinks.
The directory must exist before confinement starts; the database may be absent and native TicGit creates it through the link.

The trusted host wrapper and adapter startup prepare the directory and aliases; native request children cannot create or retarget aliases.
Preparation never replaces an existing path; concurrent preparation may accept the same valid directory and links.
Accept an existing link only if its direct target is the selected database, resolving relative targets against the link's parent.
Validate all selected paths before preparation; reject wrong occupants and SQLite sidecars beside either alias without modifying existing data.
An existing database at a native alias location requires an explicit migration outside startup, with no active database users.
Do not silently hide, migrate, merge, or delete tickets; no inventory of unrelated worktrees is required.
At preparation, validate the directory, aliases, their parents, and the expected database target against the accepted storage layout.
Only these exact database links are symlink exceptions; reject a symlinked store directory or canonical database at preparation.
Confinement protects surrounding Git metadata and alias directory entries, not the store directory's inode identity.
Replacement of the store directory need not be prevented; it contains only files native TicGit may already modify.
The directory and aliases persist after session cleanup; SQLite alone owns sidecar lifecycle during native operation.
Direct native calls that bypass preparation without the accepted layout are outside the shared-store contract.

The host wrapper leaves cwd and argv unchanged in every checkout, including nested directories.
Relative file inputs, branch defaults, editor cwd, and repository-local installation destinations retain native caller context.
The agent executor fixes cwd to the accepted host workspace root, including for linked worktrees; requests cannot change it.
Verify repository discovery selects the accepted common-directory store, including when the database does not yet exist.
The host wrapper does not inspect arguments and retains human authority, native interaction, and native session state
without the agent allowlist, sandbox metadata, credentials, endpoint, or container runtime.

== Endpoint ownership <tic-ownership>

Select the proposed default-off version 2 boolean `capabilities.tic` under the #link("launcher-interface.typ")[launcher contract].
It selects an installed host capability, not a project `commands.tic` command or native-TicGit image.
Reject a simultaneous project command named `tic`; host availability alone cannot enable the capability.

Use the #link("trusted-service-lifecycle.typ")[existing shared-session lifecycle] with a host-native command-proxy adapter.
Session identity remains canonical workspace root plus Git common directory.
Worktrees may share the database without sharing accepted policy or endpoint ownership.
The adapter fixes repository/store identity, execution cwd, native build, command and file-path policy, configuration, and confinement.
The accepted-session representation must version host process ownership, authenticated endpoint identity, and implementation provenance;
container identities do not represent host process authority.

Use existing runtime-provider transport and host-relay authentication to expose only the accepted endpoint to the guest.
A relay has neither database-write access nor authority to execute native commands.
Transport owns connection authentication with a session capability credential and accepted peer/reachability restrictions.
Keep that credential outside application argv and native environment; no unauthenticated host listener is permitted.

The supervisor owns publication, readiness, joining, cancellation, descendant cleanup, and abandoned-session recovery.
Readiness checks the fixed authority, protected paths, confinement, and endpoint; it does not inspect database contents or run a mutating native probe.
Use existing protected-metadata validation with only the database-link exceptions defined under Shared store directory.
An absent database is not a readiness error: native TicGit may create it under the same confinement as later commands.
Final-holder cleanup stops only this session's endpoint, transport resources, and native descendants, never ticket data or unrelated writers.
A failed published endpoint stays unavailable until normal cleanup; do not restart it beneath attached agents.
No cross-workspace endpoint registry or separate store lifecycle is required.

== Host execution boundary <tic-execution>

All SQLite connections and sidecar access stay on the host's local supported filesystem.
Neither the guest nor relay opens SQLite, including for readiness; cross-VM shared-filesystem WAL access is unsupported.
Requests cannot select repository, cwd, environment, configuration, executable, or endpoint.
Use a trusted absolute executable path, closed stdin, no terminal, a cleared inherited environment, and private HOME/XDG paths.
Give each request an initially absent `TICGIT_STATE_FILE` and discard it after descendant cleanup.
This keeps native current-ticket and filter state separate from other requests and the human.
Use a trusted failing `GIT_EDITOR` for native noninteractive editor failures; caller text never becomes shell code.

Provide a private configuration overlay with only accepted authorship, repository format, and `meta.namespace`.
Exclude includes, remotes, hooks, signing commands, filters, credential helpers, human HOME, and credential agents.
Authorship is the accepted workspace identity; `meta.namespace` selects serialized refs, not a separate SQLite store.
Leave repository-format support and diagnostics to native TicGit.

Use Anthropic Sandbox Runtime (`@anthropic-ai/sandbox-runtime`) through its supported public API for host confinement.
Select its Linux bubblewrap and macOS Seatbelt backends; lock a reviewed runtime version and dependencies when packaging the executor.
The host wrapper does not import or require this runtime.
Permit writes to the selected dedicated store directory and request-private directories, not the surrounding Git directory.
Deny writes to code refs, `.jj`, host configuration, and working-tree files.
Protect alias directory entries through their parents without denying writes through the links to the selected database.
Do not put database aliases in SRT's `denyWrite`: on Linux the denial follows the link and makes the database target read-only.
Account for runtime-added default write paths; the configured write allowlist alone does not establish this boundary.
Explicitly deny default writable locations outside the accepted directories and account for platform-required device access.
Deny network/credential access and arbitrary host-file reads, including through caller-selected file arguments.
Launch only the fixed native entrypoint; subprocesses inherit filesystem and network confinement.
No executable allowlist is required: permitted effects, not subprocess names, define the boundary.
Native `open_store()` may attempt automatic setup even when the `setup` command is excluded.
The execution checkout is mutable: confinement must prevent unsafe setup effects even if `.git-meta` appears or changes after startup.
Do not use a `.git-meta`-absence check as a substitute for confinement.
Missing or ineffective confinement rejects capability startup; there is no unsandboxed retry.

Review of runtime `0.0.81` found Linux policy generation skips nonexistent individually allowed write paths.
An existing dedicated directory avoids depending on grants for future database or sidecar names.
Generated-policy checks and the native symlink probe do not establish confinement acceptance.
Verify the composed layout, default-path restrictions, and SQLite creation/recreation on real Linux and macOS hosts before shipping.
The host-native adapter, runtime integration, and supported-platform enforcement remain unimplemented.

== Command admission <tic-admission>

The host executor enforces the installed policy on every authenticated request, even when the guest wrapper is bypassed.
Admit these native families and their native aliases (`ls`, `dep`, `status`):

- Inspection: `list`, `show`, `history`, `recent`, `stats`, `next`, `writeup list`, and `writeup show`.
- Mutation: `new`, `edit`, `comment`, `state`, `claim`, `close`, `tag`, `assign`, `priority`, `points`, `milestone`,
  `code`, `depends`, `subissue`, `meta`, `spec`, and other native `writeup` subcommands.

Empty argv means native `list`.
Reject `init`, `setup`, `update`, `pull`, `push`, `sync`, `import`, `tui`, `agent`, `checkout`, `users`, `mine`, `views`, and `review`.
Reject authority overrides and file operands outside the accepted shared-workspace mapping.
Let native TicGit handle `list NAME` and `new --checkout` using request-private state.
Saved-view lookup retains native missing-view errors; checkout selection does not persist across requests.
Help/version use the generated restricted interface below without opening the store.
All other validation, target resolution, option conflicts, errors, writeup formats, and output remain native.
Admit `tag --writeup` without reproducing writeup resolution.

=== File-option inspection

Use a bounded handwritten scanner for `-F` / `--file` in `new`, `edit`, `meta`, `spec`, `writeup new`, and `writeup edit`.
Preserve native CLI syntax; add no upload option or file placeholder.
Recognize separate operands, attached values (`--file=PATH`, `-FPATH`, and `-F=PATH`), and short-option clusters.
Keep token positions and value spans so only the file operand changes; stop option recognition at `--`.
Use a small reviewed table of short-option value arities for these commands, not a full CLI grammar.
For example, `-cFfile.md` contains a file option, whereas `-tFunny` contains a title and must remain unchanged.
Option-looking text inside another option's attached value remains data.
If file inspection is ambiguous for the supported build, reject rather than guessing.
Leave native validation, option conflicts, repeated-option errors, and file-content parsing to TicGit.

Share one scanner and arity table between guest path translation and authoritative host checks.
Review them against the supported native build and compare with native parsing in compatibility tests.
Do not generate runtime option/positional metadata, scrape help, or copy native validators.
Command admission remains an installed command/alias policy; other arguments need no full-CLI parser.

=== Restricted help

Generate packaged help at build time from the supported native Clap definitions and the installed admission policy.
Use those authorities for command/alias admission and help; maintain no separate CLI catalog.
The bounded file-option scanner is maintained separately and checked against native parsing, not generated from Clap.
Generate help for every admitted command, even when its arguments need no runtime inspection.
Filter rejected commands, aliases, options, and operands from both displayed usage and detailed help.
Replace the native hardcoded help template and its embedded examples in the generated view; filtering the Clap tree alone is insufficient.
A companion build target may compile private native CLI modules; this help-generation source-layout dependency requires review on upgrades.
Do not scrape native help or change the installed native executable.
Add fixed explanations of file-path translation, shared-workspace visibility, request-private state, and noninteractive editor failures.
Use the generated command definitions for native syntax and descriptions, not independently maintained wrapper descriptions.

Guest and authenticated direct-endpoint help use the same packaged artifacts for top-level and subcommand help, including native help aliases.
Help/version never open the store or invoke native application dispatch.
Bind artifacts to native-build and admission-policy provenance.
Failed generation prevents package publication; missing or mismatched artifacts reject agent startup.
Changes to native definitions or admission policy regenerate help rather than retaining stale output.
Ordinary host help remains native and needs no generated artifacts.
Other native output remains unchanged, including Markdown suggestions that may recommend rejected commands such as `checkout`.

== File paths and outcomes <tic-bounds>

Reuse the #link("proxy-design.typ")[generic framed JSON protocol, validation, and fail-closed transport rules].
After transport authentication, the request has exactly these application fields:

```json
{"version":1,"command":"tic","argv":["new","-F","/accepted/host/workspace/draft.md","--markdown"],"stdin":""}
```

Require `command` to equal `tic` and `stdin` to be empty; reject NULs in arguments.
The response has exactly `version`, `exit`, `stdout`, and `stderr`.
The guest resolves each file operand against its own cwd and maps it through the accepted guest-to-host shared-workspace mapping.
Send the corresponding absolute host path; this preserves caller-relative file selection without changing the executor's workspace-root cwd.
Resolve symlinks when mapping guest paths; reject guest-only files and paths outside the accepted mapping with a clear error.
Do not add stdin semantics: `-F -` names a literal file called `-` in the guest caller's directory, mapped like any other file.
Neither wrapper reads or transports file contents, stages payload files, or rewrites unrelated arguments.
The confined native child opens the mapped file directly and retains native file-content parsing and errors.
For `writeup new`, the file is the body and `--title` remains separate; `writeup edit --file` uses native title/description parsing.

The host rescans every authenticated request, including requests that bypass the guest client.
Require recognized file operands to be absolute paths within the accepted host shared workspace, never arbitrary host paths.
Confinement enforces actual read authority, including symlink redirection; path translation is not a substitute for read restrictions.
Mapping paths requires no caller-selected execution cwd or environment.
File changes between translation and native reading retain ordinary native behavior; no content snapshot or file-identity guarantee is added.

Keep the existing command-proxy categories of bounds, with these TicGit values:

- Frames: request 8 MiB, response 32 MiB; stdout 4 MiB; stderr 256 KiB.
  No file payload is transported; file size and contents remain native concerns.
- Arguments: 128 tokens, 64 KiB each, 256 KiB aggregate decoded UTF-8.
- Authentication/framing/admission: 10 seconds; native execution including SQLite waits: 30 seconds.
- Response delivery: one absolute 3-second deadline; client exchange including waiting/cleanup: 45 seconds.
- Child termination grace: 2 seconds before forced termination and reaping.

Enforce input bounds while reading and before spawning; server checks remain authoritative.
An unread or partially read response cannot extend its delivery deadline.
Preserve native exit status and UTF-8 stdout/stderr; invalid UTF-8 or oversized output is an output failure.
Admission rejection returns `2`; transport/output/client-deadline failure returns `125`; execution timeout returns `124`, when deliverable.
Guest transport failure never falls back to local native execution or another route.
Native host execution is independent, not recovery for a guest failure.

Never replay automatically once request bytes may have been accepted.
Native errors, timeouts, cancellation, or lost output may leave partial or complete mutations; do not infer command rollback.
On cancellation, terminate and reap all request-owned native descendants without stopping unrelated writers.
Preserve the database and sidecars; native SQLite owns its transaction recovery.
A client that loses the response may need to inspect the result before deciding whether to retry `new` or promotion.

== Acceptance evidence

Verify the wrapper and security boundary with disposable host-local repositories and the supported unmodified CLI:

- Compare representative host, guest, and direct-endpoint results with native execution in the corresponding context.
  Test admission and transport behavior, not a stronger replacement for native ticket correctness, schema handling, or atomicity.
  Missing/uninitialized/incompatible or incompletely loaded stores retain native initialization effects, omissions, and errors.
- Verify unchanged host cwd/argv in ordinary and linked checkouts, including nested directories and native branch/editor context.
  Host calls do not inspect arguments; identically named caller/main files have different contents and missing caller files have no fallback.
  Test directory and alias preparation in ordinary and linked checkouts with nonstandard metadata locations,
  relative/absolute links, dangling targets, and concurrent creators.
  Wrong occupants, databases at either alias location, and sidecars beside aliases fail without replacement or migration.
  Preparation rejects a symlinked store directory or canonical database; no main-checkout lookup is required.
  Inspect native open-file identities for shared database/WAL/SHM access and verify shared writer locking on each supported host platform.
  Exercise concurrent native commands, repeated sync, independent-clone import, reopening, and persistent directories/aliases after cleanup.
  Under the selected runtime, initialize through dangling aliases, remove/recreate sidecars, and run concurrent unconfined host writers.
- Exercise all six guest file-option sites with absolute and caller-relative inputs, attached values, clusters, spaces, symlinks, and `..`.
  Cover nested guest cwd, linked workspaces, differing guest/host roots, missing files, and guest-only paths without host mappings.
  Guest and host `-F -` both retain literal-file semantics; nonempty request stdin is rejected.
  Verify only file operand spans change and native code/review metadata remains unchanged.
- Compare the bounded scanner with native Clap without dispatch, including `--`, option-looking data, short-option value arities,
  `--file=PATH`, `-FPATH`, `-F=PATH`, and clusters such as `-cFfile.md` versus `-tFunny`.
  Exercise malformed and repeated file options without replacing native validation.
  Review native upgrades against this compatibility suite; no runtime grammar-metadata generation is required.
- Verify generated top-level/subcommand help and native help aliases through both guest and authenticated direct-endpoint paths.
  Rejected commands, aliases, options, operands, and native hardcoded examples do not appear as available operations.
  Cover file-path mapping and its visibility limits, explicit ticket IDs with request-private state, and noninteractive editor failures.
  Native-definition and admission-policy changes update help through regeneration; generation failure cannot publish or reuse stale artifacts.
  Help/version leave an absent database absent; ordinary host help works without the generated package.
- Bypass the guest client with authenticated raw requests; reject forbidden commands, unmapped host paths, nonempty stdin,
  malformed frames, and invalid credentials/peers.
  Verify actual reads through redirected file paths remain confined; native-required read access does not expose human secrets.
  Valid inputs at each limit are accepted; inputs above it are rejected before spawning.
  Native file parsing, errors, and output remain native after path translation.
- Prove host filesystem, configuration, subprocess, and offline confinement on each supported platform.
  Include malicious includes/editors, `.git-meta` creation/replacement after startup, aliases, and attempted reads/writes outside permitted paths.
  Verify runtime defaults do not add writable host locations outside the accepted directories and required devices.
  Missing or ineffective confinement rejects startup; guest transports receive no writable metadata, human credentials, or daemon access.
- Run host calls and endpoints from different worktrees concurrently against one host-local database without external command locks.
  Host calls work without a runtime or endpoint; request-private state never becomes another request's or the human's state.
  `list NAME` retains native missing-view errors; `new --checkout` cannot select a ticket for the next request.
  The `views` and `checkout` command families remain rejected.
  Shared database identity does not merge workspace policies, endpoints, or process ownership.
- Verify the existing lifecycle's host-native publication, join, cancellation, and final-holder cleanup with surviving native descendants.
  Stop only the owning session's processes; retain ticket data and other workspaces/host writers.
  Disconnect before execution, between writes, and during output; a non-reading peer cannot extend response deadlines.
  Failures never replay requests or promise whole-command rollback.
