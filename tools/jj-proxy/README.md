# JJ proxy operator guide

## Purpose

`jj-proxy` lets an untrusted agent use approved Jujutsu operations while repository metadata is read-only in the agent container. A sibling proxy owns the writable metadata mount, validates requests, and runs a pinned `jj` with a scrubbed environment.

## Prerequisites and setup

- Linux with Landlock support (required; other platforms fail closed)
- Docker or Podman for the production image
- Rust/Cargo for local development
- A Jujutsu repository with colocated or otherwise correctly resolved Git and JJ metadata

Build from the repository root:

```sh
cargo build --locked --manifest-path tools/jj-proxy/Cargo.toml
.agents/sandbox/jj-proxy-image
```

The image owner reads JJ release URLs and SHA-256 checksums from `config/mise.lock`, also used by host mise.
The proxy downloads the locked musl binary for amd64 or arm64 and verifies it before extraction.
The guest image copies that binary from the resolved proxy image instead of downloading a separate release.
Standalone Docker or Podman builds must supply the `JJ_AMD64_URL`, `JJ_AMD64_SHA256`, `JJ_ARM64_URL`, and `JJ_ARM64_SHA256` build arguments from that lock.
Refresh the JJ lock with `mise lock aqua:jj-vcs/jj --bump --platform linux-x64,linux-arm64,macos-arm64` from `config/`.
Release acquisition is independent of proxy source compilation; JJ updates also preserve the guest's unrelated tool-download layers.

Sandbox startup uses `.agents/sandbox/jj-proxy-image`, which reuses a tag keyed
by the Dockerfile's copied inputs and `config/mise.lock`. Local Cargo artifacts and test output do not
change that key. Keep the builder's input list aligned with Dockerfile `COPY`
instructions when adding image sources.

The sandbox launcher must validate all metadata indirections, create the private socket volume, mount the repository and metadata as specified by the design, set `JJ_PROXY_REPO`, `JJ_PROXY_GIT_DIR`, `JJ_PROXY_COMMON_DIR`, and `JJ_PROXY_JJ_REPO`, and wait for readiness before starting the agent. A manually started proxy without those mounts is not protected.

The agent-side `jj` wrapper discovers the mounted proxy socket if `SANDBOX_PROXY_DIR` is absent; `JJ_PROXY_REPO` defaults to `/src/work`. `JJ_USER` and `JJ_EMAIL` may set a validated identity.
For another host-backed Jujutsu repository under `/src`, the wrapper sends inspection requests.
These use `--ignore-working-copy` and a separate read-only Landlock policy;
commands that change repository state are rejected. Inspection of linked workspaces
requires their metadata to be visible in the proxy container.
For a repository with a Jujutsu secure-config ID, the trusted proxy prepares a
private config-cache entry before inspection. It never initializes or rewrites
the inspected repository's `.jj` metadata; the inspection child can only read
that cache.
Use `jj -R /src/flower/paracress status` to inspect another repository without
changing directories. Relative `-R` paths resolve from the invoking directory;
`--repository` is equivalent. A selector outside `/src` is refused, and mutation
access is granted only to the selected workspace.

## Independent container-local repositories

Ordinary `jj` uses native JJ for independent guest repositories, including `/tmp`, private tmpfs, and guest-created volumes, even with the proxy mounted. The read-only router resolves repository selectors, symlinks, linked JJ stores, and Git indirections against effective mounts. A `/tmp` workspace sharing a host store still needs the proxy; its guest-only cwd is not admitted by the server. Run protected commands from the mounted workspace instead. The wrapper never changes cwd or retries a failed proxy command natively.

Bootstrap routing follows the destination rather than the invoking repository:

```sh
jj init /tmp/replay
jj -R /tmp/replay commit -m 'Record local work'
```

The image installs `config/jj.toml` as native global configuration. The router reads its array aliases as data, so `init` and `clone` use the same definitions as native JJ. Native tools and credentials remain guest-only; this configuration is not the trusted proxy's `jj.toml`.

The JJ wrapper requires Python, including standalone host copies.
`JJ_ROUTE_HELPER` identifies the packaged read-only router.
The wrapper imports its `route()` and `check_result()` functions in-process; it owns identity and execution.
Agent-split uses the unchanged internal CLI, `python3 route.py -- <jj-arguments>`, from the actual invoking cwd.
Successful stdout is one JSON object with `backend`, `workspace`, `destination`, expanded `command` prefix, and `hooks`.
Paths are physical absolute paths or null.
Nonzero CLI status invalidates all output; diagnostics use stderr.
These internal interfaces deploy with both consumers.
Routing and identity are recomputed for each invocation, without a shared cache.

The existing private `jj --agent-split PATCH MESSAGE REVISION` operation is proxy-only. The wrapper checks its four opaque arguments before ordinary parsing, selects the workspace backend, resolves runtime identity, and forwards to the unchanged client. A native route rejects this operation before hooks or socket access; local agent-split uses ordinary `jj split`.

The trusted split editor recounts hand-edited hunk lengths during both dry-run
and application, matching agent-split's preflight. Stale context still fails.
Editor changes require rebuilding the proxy image and starting a new sandbox;
they do not update an already-running proxy.

## Common commands

Once the launcher has installed the wrapper, use ordinary commands:

```sh
jj status
jj diff
jj log
jj op log
jj commit -m 'Describe the change'
jj rebase -r @ -d main
jj undo
jj git fetch --remote upstream
```

Fetch accepts any existing configured remote, including repeated `--remote` options and `--all-remotes`.
Without a remote option, Jujutsu uses its normal defaults, including the repository's `git.fetch` setting.
Remote add/set-url operations, request-supplied configuration overrides, and push remain blocked.

Common history, bookmark, file, and workspace operations are also allowed.
Inspection also permits `evolog`, `bookmark list`, `tag list`, `op diff`, `sparse list`, `root`, `version`, and `workspace root`.
Both `jj version` and `jj --version` are allowed through the proxy.
Configuration diagnostics permit `config get`, `config list`, and `config path`.
For `op diff`, use `--from` and `--to`; the policy blocks `--operation`.

## Safety and recovery

- Never mount the outer Docker/Podman daemon socket or write-capable protected-remote credentials into the agent container.
- Keep host-backed `.git` and `.jj` read-only there; commands targeting that metadata, including `status` and `diff`, use the proxy. The wrapper is a convenience dispatcher, not an authorization boundary. Absolute native invocation retains the same guest permissions and cannot write protected metadata.
- The proxy rejects shell execution, config/repository overrides, external tools, `git push`, `git init`, and remote configuration changes. The read-only [`jj.toml`](./jj.toml) is the single authority for trusted editor, formatter, and signing settings; proxy command construction does not override it. It can still perform logically destructive but recoverable allowed history edits.
- For a proxy route, socket failure returns `125` and never falls back to native JJ. A local route does not connect to the proxy.
- A command timeout returns `124`; policy/request failures normally return `2`. Inspect stderr, correct the request, and retry.
- Use `jj undo` through the proxy to recover an allowed history edit.
  The proxy rejects `jj op restore`; run it only from a trusted environment outside the agent sandbox.
  If the proxy was interrupted during a metadata write, stop the agent, inspect/recover the repository from that trusted environment, then restart the whole proxy session.

## Tests

From the repository root:

```sh
dev/test-environment pytest -q -p no:cacheprovider tests/native/test_native_jj_proxy.py tools/jj-proxy/tests
.agents/sandbox/jj-proxy-image
```

The native pytest adapter runs Cargo and passes the test environment's selected real JJ binary as `JJ_PROXY_TEST_JJ`.
Set `DOTFILES_TEST_JJ_REAL` to select a specific binary.
Direct Cargo runs can report success while skipping real-JJ integration tests if no binary is found.

The Rust suite covers command and Landlock execution policy plus protocol behavior. Python tests cover routing, client framing, and the trusted split editor. Wrapper tests also cover local dispatch with a mounted proxy, target-scoped attribution, and private split identity. The image build also runs release Rust tests, including secure-config preparation against its pinned Jujutsu binary. These checks do not establish acceptance in a real container.

## Design and reference

For the security model, mount topology, protocol, and rationale, read the [design](./design.typ).
The checked-in [`policy.toml`](./policy.toml) defines command permissions, blocked privilege-crossing options, and author hooks. The image packages it at `/trusted/policy.toml`; the server loads and validates it once before opening the readiness socket. Policy edits require rebuilding the proxy image, but do not require recompiling the binary.
The library's `Policy::load` takes a trusted caller-selected path; request arguments and environment variables cannot override the production path. Tests load the checked-in file through `CARGO_MANIFEST_DIR` and need no host `/trusted` directory.

### Policy format

`[inspect]` allows inspection commands. Mutation mode also allows every inspection rule; `[mutate]` adds mutation-only permissions.

```toml
[inspect]
status = true
file = { subcmds = ["annotate", "list", "search", "show"] }
git = { subcmds = ["root"] }
"git remote" = { subcmds = ["list"] }

[mutate]
commit = { updates_author = true }
file = true
git = { subcmds = ["fetch"] }
```

Each key is a nonempty command prefix, split on whitespace into whole argv tokens.
`true` and `{}` are equivalent: both permit that prefix, including all its subcommands.
`false` is rejected; omit a command to deny it.
`subcmds` appends each listed token to the key's prefix; trailing options and operands remain allowed.
The list must be nonempty and each entry must be one nonempty token.
For example, `"git remote" = { subcmds = ["list"] }` is equivalent to `"git remote list" = true`.
Both allow `git remote list --help`, but neither allows `git remote add` or `git remote listing`.
`updates_author` defaults to `false` and applies to every path in the rule.
Mutation entries take precedence over inherited inspection entries; within each section, the longest matching prefix selects the rule's metadata.
Unknown fields are rejected; there are no `prefix`, `kind`, or `approved_remote` fields.

`[global]` defines `forbidden_options` and `forbidden_prefixes` lists. The evaluator checks options after the matched command path: exact option names are compared before `=`, while forbidden prefixes match the option name. Ordinary option and operand validation remains with the pinned Jujutsu binary.
Both inspection and mutation requests reject caller-supplied `--ignore-working-copy` and operation selectors in every argument position.
Forbidden selectors include `--at-operation` and `--at-op`, including attached values.
The trusted inspection executor adds its own `--ignore-working-copy` only after request validation.
Rebuild the proxy image and recreate the server to apply policy changes; an already-running server retains its startup policy.

The evaluator passes fetch arguments unchanged to Jujutsu, which resolves configured remote names and default selections.
There is no proxy remote-name allowlist or URL/transport validation.
Remote URLs remain host-controlled because requests cannot change remote configuration.
See the [tools overview](../README.md).
