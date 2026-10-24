= TicGit command proxy

*Status:* Selected replacement design; not implemented or accepted for production.
This contract replaces the unmodified-TicGit/SRT implementation preserved on the local `ticgit-proxy-wip` branch.
The capability remains default-off.

== Purpose and architecture

Agents and ordinary host commands must see the same tickets across linked worktrees without sharing a live SQLite database across the VM filesystem.
Keep SQLite on the host and forward approved CLI requests through a small host-side command broker.
Use a TicGit fork to fix native store selection and remove automatic setup, rather than building an OS sandbox around the general-purpose CLI.

```text
guest ti -> authenticated command broker -> installed TicGit fork -> host-local store
human ti -------------------------------> installed TicGit fork -> same store
```

Follow the request-validation and bounded-execution structure of #link("../../jj-proxy/README.md")[the JJ proxy], not its sibling-container deployment or Landlock policy.
TicGit remains a local CLI: it owns no listener, authentication, guest transport, or service lifecycle.
The broker owns command restrictions and host execution.
No SRT, Node confinement runtime, Landlock, Seatbelt backend, database replication, or host/guest ownership handoff is required.
Reuse existing transport and lifecycle components where they fit; do not introduce a generic host-execution framework solely for TicGit.

== Trust and permitted effects <tic-execution>

The agent controls request bytes and ordinary files in its accepted checkout, and may bypass the guest wrapper.
The installed broker, installed TicGit fork, dependencies, and accepted repository metadata are trusted.
Their executable sources and accepted policy must not be writable through a guest mount alias.
Initial broker support excludes repository-local configuration includes and alternate object stores.
Disable system/global configuration and inherited configuration overrides for broker invocations.
Before native repository loading, inspect local configuration without following includes; reject `include` and `includeIf` directives, even inactive ones.
Cover common-directory `config` and, when worktree configuration is enabled, both invocation-git-directory and common-directory `config.worktree`.
The invocation discovery and common-directory session open each load repository configuration; complete preflight before either open.
Ordinary `gix::discover()` already opens the repository and is not a configuration-free path locator for this preflight.
Reject any `objects/info/alternates` directory entry, including a dangling symlink, rather than following its contents.
These control files and their effective file/directory paths must remain protected against guest writes under the existing repository-metadata acceptance rules.
Loose-object lookup follows symlinks, and multi-pack-index pack-name entries can select paths outside the common directory.
Accepted metadata must not redirect those reads into guest-writable targets; protecting the index or symlink alone is insufficient.
Rejecting includes and alternates does not by itself prove that every object read stays beneath the common directory.
Do not replace this restriction with recursive include/alternate trust analysis.
The restriction applies only to broker use; ordinary host TicGit retains native repository support.
Guest requests grant ticket and writeup operations, not arbitrary host file access, repository administration, credential use, network access, or program execution.
Bad ticket edits within that authority are not an escape from the boundary.

Enforce the boundary through the fork's behavior and the broker's command-and-option policy.
There is no OS-confinement fallback or requirement to contain a compromised native process.
A bug in the admitted native path can therefore exercise the host process's permissions; acceptance depends on reviewing and testing that path.
Do not describe argument filtering as protection against arbitrary native-code vulnerabilities.

In particular, rejecting a `setup` request is insufficient if an admitted `list` can perform automatic setup.
The fork removes that implicit behavior.
Likewise, admitting `comment` is insufficient if omitted text or an editor option can launch a program.
The broker rejects every invocation that can take an interactive or external-command path.

The accepted native path may read its fixed repository context and ticket data, and may create or update the selected database and SQLite sidecars.
It receives input through stdin and may use broker-owned request-private files for ephemeral UI state.
It must not mutate code refs, Jujutsu metadata, host configuration, or working-tree files, or execute a helper selected by configuration or request data.
Verify configuration-source restrictions, object lookup, and missing-blob behavior as part of that claim; do not assume that removing the top-level setup command proves it.

== Native fork and repository context <tic-transactions>

Native TicGit continues to own CLI parsing, ticket validation, storage, schemas, metadata interpretation, rendering, and SQLite concurrency.
The broker does not open SQLite, add command transactions, repair metadata, or promise whole-command atomicity.
Independent host commands and brokers may use the store concurrently without an external writer registry or command lock.
Native contention errors, incomplete metadata, command interleaving, and partial mutations retain their native semantics.

The fork makes these changes:

- Discover the invocation repository, canonicalize its common directory, then pass that directory to `Session::open` through git-meta-lib's existing public API.
  A git-meta-lib fork is not required for this selection.
- Remove automatic setup from ordinary store opening.
  Reading or changing `.git-meta` must not cause an ordinary ticket operation to initialize a remote, fetch, or launch Git.
  Explicit host setup remains available as an administrative operation.
- Make direct SQLite readers, including history and TUI closed-time queries, use the same store-location authority as the opened metadata session.
- Make file-input options, including `-F` / `--file`, accept `-` as ordinary CLI stdin input wherever the broker admits file input.
  Read until EOF without editor fallback; native TicGit still parses the contents.
  This works for human commands too; a literal file named `-` is addressed as `./-`.
- Export the existing CLI parser for the guest client and host broker, without adding proxy policy or a native execution service.
- Make explicit metadata setup, initialization, and sync helpers use the common-repository context consistently.
  Do not initialize a worktree-local database through an unmodified `git meta` subprocess while TicGit opens the common database.
  Sync diagnostics must describe the namespace and remote actually used by the session.

Do not change the process working directory just to select the store.
Review branch and revision selection, relative input files, editor cwd, and per-worktree current-ticket/filter state retain the invocation context.
In particular, `ti review` continues to select its default branch through Git in the invocation directory.
Reviews remain available to the human but are not admitted through the agent proxy.

Opening the common directory intentionally selects the common repository's metadata-session configuration, including its author and namespace defaults.
After repository preflight and before invoking native TicGit, the owning launch captures the ordinary effective host Git settings once, including host configuration and applicable invocation-worktree configuration.
Freeze the accepted `user.name`, `user.email`, and `meta.namespace` values for that launch; later host configuration changes do not alter them.
This is local operator bootstrap, not a guest API; capture reads configuration without opening or mutating SQLite.
Native request executions still disable system configuration with broker-owned `GIT_CONFIG_NOSYSTEM=1` and user/XDG Git sources with `GIT_CONFIG_GLOBAL=/dev/null`, and clear inherited configuration overrides.
Supply the captured accepted values through a broker-created `GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n` / `GIT_CONFIG_VALUE_n` set; requests cannot supply or change them, and `GIT_AUTHOR_*` alone does not control session authorship.
`meta.namespace` selects serialized refs, not a separate SQLite database.
Keep native human interaction and explicit administrative commands outside the agent policy.
Ordinary host use requires neither the VM nor a running broker.

== Shared store

Use the native `git-meta.sqlite` location directly beneath the canonical Git common directory.
For a conventional checkout:

```text
.git/git-meta.sqlite
.git/git-meta.sqlite-wal
.git/git-meta.sqlite-shm
```

The dedicated `ticgit-store/` directory existed to support filesystem write grants and is no longer needed.
Add no database aliases, symlink preparation, or separate storage wrapper.
Resolve the common directory through the native repository interface; requests cannot select the store.
Establish that the session reopens that accepted repository, not merely that its argument is canonical.
Default `gix::open` can prefer a nested `.git` when the argument is not named `.git` or `*.git`.
Account for that behavior before accepting an unusually named common directory containing another repository; canonicalization alone does not establish its store identity.
SQLite owns database creation and sidecars, and the guest and transport relay never open them, including for readiness.

Reuse an existing common-directory database in place.
Detect legacy worktree-local databases before adopting shared storage; refuse independent stores rather than silently hiding or merging tickets.
Do not migrate during startup or build a migration subsystem for the proxy.
If existing data requires relocation, inventory those stores and define a one-time offline procedure before touching them.
Any such procedure must stop database users and preserve contents on failure.
Old worktree-local native invocations are not supported alternate writers to this shared-store arrangement.

== Broker ownership and lifecycle <tic-ownership>

Select the default-off version 2 `capabilities.tic` boolean under the #link("launcher-interface.typ")[launcher contract].
Reject a simultaneous project command named `tic`.
The capability selects an installed host command broker, not a project-selected executable or a native-TicGit container in the VM.

Use the #link("trusted-service-lifecycle.typ")[required `agent-launch` lifecycle] with one launcher-owned host broker per launch.
The owning launch and its execution attachments use that broker; separate launches have separate brokers and endpoints, even when they share ticket data.
Bind accepted authority to the workspace, canonical common directory, installed fork/build, command policy, identity, and fresh authenticated launch endpoint.
No shared-session TicGit publication, broker join, or durable host-process record is required.
Linked worktrees share ticket data, not accepted workspace authority.
A request cannot select repository, execution cwd, environment, configuration overrides, executable, or endpoint.
Use a trusted absolute executable, the accepted host workspace cwd, a cleared inherited environment, bounded request stdin, and no terminal.
Close native stdin after delivering the request bytes; commands without file input receive EOF immediately.
Give each request private HOME/XDG and `TICGIT_STATE_FILE` locations so selection and filter state cannot leak between requests or into human use.
Even `list --json` saves filters; inspection does not imply a read-only native process.
Keep transport credentials, host credential agents, and reusable upstream credentials outside the native environment.

Reuse provider transport and session authentication; reject unauthenticated access and never expose generic host execution.
The broker invokes the fixed native program directly, without a shell, and owns bounded output collection, cancellation, termination, and reaping.
The admitted native paths must not spawn external programs; test this rather than introducing another per-request descendant watchdog.
Do not carry forward Linux pidfd identity or waitid/WNOWAIT requirements merely because the archived implementation used them.
Keep a lifetime pipe's write end in the owning launcher and its read end in the broker's event loop.
Do not let unrelated children inherit the write end.
Normal launch shutdown or EOF on that pipe stops admission, closes the listener, cancels and reaps the broker's native child, and removes request-private resources.
An attachment ending does not end the broker while its owning launch remains active.
Use live child ownership for normal termination; do not persist broker PIDs, adopt a previous broker, or kill recorded host PIDs during later recovery.
If the broker itself dies, an in-flight native command may finish; report the unknown outcome rather than adding a descendant watchdog or replaying the request.
Provider-owned relay resources still use the existing lifecycle cleanup rules.

Readiness validates the installed build/policy, fixed authority, supported repository configuration, storage layout, and endpoint without opening or mutating SQLite.
The required broker must be ready before its execution attachment can use it.
An absent database is allowed; native TicGit may create it during an admitted command.
Owning-launch cleanup leaves ticket data, other launches' brokers, and independent host writers alone.
Do not replace a failed broker under attached clients or replay its requests.
The design targets Linux and macOS without platform-specific OS-confinement backends; installation, ownership, and transport still require acceptance on each platform.

== Command and option admission <tic-admission>

The broker validates every authenticated request, including direct requests that bypass the guest wrapper.
Use an installed allowlist bound to the supported fork build; an unknown command, option, or ambiguous security-relevant invocation is rejected.
Share command/alias policy between dispatch and the advertised agent interface.
Native TicGit remains the authority for domain validation and output, not a second ticket implementation in the broker.

Admit inspection through `list`, `show`, `history`, `recent`, `stats`, `writeup list`, and `writeup show`.
Admit `next` with its native selection update confined to request-private UI state.
Admit ticket mutations through `new`, `edit`, `comment`, `state`, `claim`, `close`, `tag`, `assign`, `priority`, `points`, `milestone`, `code`, `depends`, `subissue`, `meta`, and `spec`.
Admit native writeup creation, editing, promotion, closing/archiving, linking, and unlinking.
Retain native aliases only when their dispatch path is admitted; empty argv means `list`.
Reject `mine`: without an explicit assigned filter it runs `git config user.email` before listing, and it is not merely a `list` alias.
Use `list --assigned` for that query instead.

Reject setup, initialization, migration, update, import, pull, push, sync, interactive UI, agent installation, user administration, saved-view administration, checkout, and review commands.
Reject authority/configuration overrides and every editor-launching option or fallback.
In the inspected native interface, this includes the following invocation conditions:

- `new` requires a nonblank explicit title or an admitted input file; reject `--comment-edit`.
- `edit` requires an admitted input file.
- `comment` requires at least one positional body value; reject `-e` / `--edit`.
- `spec` requires explicit text, an admitted input file, or `--clear`.
- `writeup new` requires a nonblank explicit title and an explicit body or admitted file.
- `writeup edit` requires an explicit body or admitted file.
- `state` and its `status` alias require an explicit lifecycle value; do not rely on piped stdin to error before interactive selection.

Evaluate these conditions on the authoritative parsed values, not raw option spelling.
Explicit empty comment/spec/writeup-body values do not invoke an editor; do not confuse them with absent options or arguments.
Blank explicit titles can invoke an editor and require the nonblank checks above.
A missing metadata value produces a native validation error, not an editor fallback.
Audit changed admitted paths under the same no-interaction/no-external-command rule.
Do not confuse ticket mutation, which is intended, with repository or host mutation, which is not.
Preserve ordinary host help and commands; agent help must advertise only admitted commands and options.
Export the fork's existing parser as library code rather than maintaining a second argv grammar.
The guest client owns file-to-stdin normalization; the broker owns admission rules and agent help.
Do not add policy annotations or an execution mode to TicGit.
The exact parser export remains to be specified; it is not a native server interface.
Help/version do not open the store.

== File inputs and request outcomes <tic-bounds>

Reuse the #link("proxy-design.typ")[bounded framed request/response and fail-closed transport contracts].
The application request identifies `tic`, normalized argv, and input text in the existing `stdin` field.
Encode that text as UTF-8 for native stdin; reject input that cannot be represented by the framed JSON protocol without changing its contents.
The response carries version, native exit status, stdout, and stderr; no request field selects execution authority.

For `ti edit -F draft.md`, the guest reads `draft.md` relative to its invocation cwd and normalizes argv to `edit -F -`.
It sends the file contents as request stdin, not the original pathname.
For `ti edit -F -`, the guest reads caller stdin instead; `ti edit -F ./-` reads a literal guest file named `-`.
The broker validates the normalized command, then forwards exactly that argv unchanged and supplies the bounded stdin bytes.
Native TicGit parses the content; neither client nor broker interprets ticket syntax.
Guest-only input files are allowed because their contents, not their paths, cross the execution boundary.
The host never opens the supplied guest pathname, so workspace mapping and host safe-open/symlink-race machinery are unnecessary.
Do not silently substitute a host read when guest file loading fails.

Use the exported native parser to identify file operands, including attached values, short clusters, option-looking data, and `--`.
Every admitted file operand must be `-`; reject a direct authenticated request naming any other file.
Do not replace operands after admission or stage input in host files.
Reject nonempty stdin when the parsed command has no admitted file operand.
An empty input file still supplies empty stdin; leave content validation to native TicGit rather than confusing empty content with an omitted file option.
Implement native file-or-stdin reading at all five existing read sites covering six admitted command forms: ticket new/edit, spec, metadata, and writeup new/edit.
Preserve each caller's content parser: writeup-new file input is body-only, while writeup-edit file input parses the first line as title.
A title-only writeup-edit file changes the title without appending a version; `writeup edit --body` appends a version without changing title.
Do not translate `--body` into file input or reinterpret file input as body-only text.
No attachment format, file-service API, or separate execution grammar is required.

Retain the existing command-proxy bounds: request 8 MiB, response 32 MiB, stdout 4 MiB, stderr 256 KiB; 128 argv tokens, 64 KiB each, 256 KiB aggregate decoded UTF-8.
Authentication/framing/admission has an absolute 10-second deadline from connection acceptance, native execution 30 seconds from child start, and response delivery 3 seconds.
The client exchange has one absolute 45-second deadline from starting file/stdin collection or attempting the connection, whichever occurs first.
Allow 2 seconds for termination before forced termination and reaping.
Cancellation or expiry before spawning discards the request without executing it; waiting behind another request does not reset deadlines.
Encoded stdin counts toward the framed-request limit; complete request receipt and validation within the admission deadline.
Reject oversize input before spawning, and include stdin delivery within the native execution deadline.
The guest client also bounds file/stdin collection within the client exchange budget, rather than reading an unbounded input before starting its timeout.

Admission rejection returns `2`, execution timeout `124`, and transport/output/client-deadline failure `125` when deliverable.
Otherwise preserve native exit status and UTF-8 stdout/stderr.
Transport failure never falls back to local guest TicGit, another endpoint, or privileged host execution.
Never replay a request automatically once it may have been accepted.
Errors, cancellation, or lost responses may leave partial or complete mutations; inspect the result before retrying a creation or promotion.
SQLite owns transaction recovery; broker cleanup never deletes database sidecars.

== Evidence and delivery checks

The earlier library probe used TicGit `0.3.1` at `82246613185604888c08f8f28627b18679ecfbad` with git-meta-lib `0.1.10`.
It verified shared ticket visibility and serialization through existing common-directory session APIs, including a bare common repository.
It also observed the change to common-repository author and namespace defaults.
That evidence is not acceptance of the modified CLI, broker policy, or host transports.
The archived SRT implementation's tests do not establish this replacement's security boundary.

A Linux/Alpine native-effects experiment on 2026-10-24 built the pinned CLI with only automatic setup removed and common-directory session selection changed.
Across 41 bounded invocations, 23 representative explicit-input inspection, mutation, and private-state operations succeeded without child execution or network syscalls.
The unmodified control attempted setup during `list`; the modified CLI ignored the same hostile `.git-meta` and shared tickets between linked and main worktrees.
Five editor controls executed a configured helper and attempted refused loopback connections, confirming that tracing detected those effects.
The separate `mine` command also executed Git, and a raw `meta --file` operand returned an external-file canary through a workspace symlink.
These observations support the explicit noninteractive checks and guest-bytes/stdin handoff above; stdin support itself was not implemented in that experiment.

Included configuration was read even under accepted author overrides, although those overrides prevented the observed author-value reflection.
A fixture-seeded Git-reference row resolved an external alternate-object canary; ordinary ticket setters did not create such references.
These are concrete transitive repository reads, not demonstrated arbitrary host-file disclosure by guest requests.
They motivate the selected initial rejection of local includes and alternate object stores rather than support for arbitrary trusted-context graphs.
Missing blobs produced native errors without helper execution or network fetch in the sampled `show`, `list`, and `comment` paths.
Linked-worktree `history` still opened the old database location, confirming the direct-reader fix remains necessary.
The experiment did not implement parser export, broker admission, input transport, or production lifecycle, and provides no macOS acceptance.
Retained local evidence is in `target/tic-native-effects/report.json`, `native.patch`, and the per-invocation traces and outputs beside them.

A source-only admitted-path audit on 2026-10-24 followed the pinned patched CLI through native handlers, git-meta-lib, and both gix discovery/configuration and local-object lookup paths.
It performed no build, native invocation, or new runtime experiment.
Under the stated admission, environment, and protected-metadata assumptions, it found no further reachable helper, hook, filter, network, or lazy-fetch call in those inspected paths.
Ordinary setters and list appends store literal values rather than creating Git-reference rows; pre-existing reference rows perform local blob lookup and return missing-object errors without fetching.
The audit identified the explicit `state`/`status` condition, both-open preflight coverage, and effective-object-path qualifications incorporated above.
It confirmed that stdin support, parser export, and history's common-store repair remain unimplemented; repair history without changing the worktree-specific key used for UI state.
Native text/Markdown output can preserve stored terminal-control bytes; handling them at display remains an output-consumer question, not native helper execution.
History and stats also contain UTF-8 byte-boundary truncation panics; these are robustness findings, not demonstrated privilege-boundary violations.
Retained source references and coverage limits are in `target/tic-design/native-effects-static-audit.md`.
This audit does not establish safety of arbitrary native-code bugs, unexamined dependency paths, or runtime transport and lifecycle behavior.

Implementation still requires ordinary native stdin support, parser export, the direct-reader repair, bounded stdin transport, repository-support checks, and per-launch lifetime-pipe integration.
Review the resulting implementation against the source audit and repeat affected call-path review when the supported fork or dependencies change.
Resolve concrete gaps in those boundaries without reinstating an OS-sandbox requirement or moving host/guest service logic into TicGit.
Then verify the complete path with disposable host-local repositories:

- Main and linked worktrees share database and sidecar identities, including fresh creation, reopening, native contention, and concurrent human/broker writes.
- History and TUI read the shared database while review defaults, relative files, and human UI state retain invocation-worktree behavior.
  Explicit setup and sync use and report the common metadata context.
- Repositories with local includes, conditional includes, or alternate object stores reject before either native repository open.
  Cover both `config.worktree` locations, inactive include conditions, and dangling alternate-entry symlinks.
  System/global and inherited configuration cannot affect broker invocations; accepted broker-created identity/namespace overrides do apply.
  The guest cannot alter effective metadata or object paths through mount aliases, symlinks, or multi-pack-index pack-name indirections.
  Verify session repository identity for supported nonstandard common-directory layouts without opening SQLite during readiness.
  Ordinary host commands retain native repository support.
- Admitted commands never execute external helpers or access unauthorized host files, even when `.git-meta`, editor settings, and workspace symlinks change.
  Test missing/blank inputs, explicit versus absent lifecycle for `state`/`status`, option clusters, aliases, `--`, and direct authenticated requests, not just well-formed guest-client calls.
- File inputs work from relative paths, guest-only directories, and caller stdin; literal dash filenames use `./-`.
  Direct requests naming host files and requests with unexpected or oversize stdin reject before execution.
  Native stdin handles empty and nonempty content at every admitted read site without editor fallback; execution uses the admitted argv unchanged and never stages input files.
  Preserve writeup title/body distinctions between file input and `--body`, including title-only edit input.
- Startup detects independent legacy databases without modifying them and never migrates implicitly.
- Authentication, readiness, disconnects, cancellation before and after spawn, blocked stdin/output, and process exit respect their bounds.
  Launch shutdown and launcher death close the lifetime pipe and stop the broker and its native child; attachment exit does not stop an active owning launch.
  A separate launch's broker and human writers remain independent.
  Broker death is an unknown request outcome; later launches never adopt or kill recorded host PIDs and never replay requests.
- Human host use works with the VM stopped; guest failures do not reroute to it.
  Run composed acceptance separately on Linux and macOS before claiming either platform supported.

Keep this capability default-off until the fork, broker, and actual provider path pass these checks.
