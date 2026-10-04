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
docker build -f tools/jj-proxy/Dockerfile -t jj-proxy .
```

Sandbox startup uses `.agents/sandbox/jj-proxy-image`, which reuses a tag keyed
by the Dockerfile's copied inputs. Local Cargo artifacts and test output do not
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

`JJ_ROUTE_HELPER` identifies the packaged read-only router. Its internal CLI is `python3 route.py -- <jj-arguments>` from the actual invoking cwd; successful stdout is one JSON object with `backend`, `workspace`, `destination`, expanded `command` prefix, and `hooks`. Paths are physical absolute paths or null. Nonzero status invalidates all output; diagnostics use stderr. The wrapper owns identity and execution, while agent-split consumes the same backend/workspace result for recovery. This internal interface deploys with both consumers.

The existing private `jj --agent-split PATCH MESSAGE REVISION` operation is proxy-only. The wrapper checks its four opaque arguments before ordinary parsing, selects the workspace backend, resolves runtime identity, and forwards to the unchanged client. A native route rejects this operation before hooks or socket access; local agent-split uses ordinary `jj split`.

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
jj git fetch --remote origin
```

Common history, bookmark, file, and workspace operations are also allowed.

## Safety and recovery

- Never mount the outer Docker/Podman daemon socket or write-capable protected-remote credentials into the agent container.
- Keep host-backed `.git` and `.jj` read-only there; commands targeting that metadata, including `status` and `diff`, use the proxy. The wrapper is a convenience dispatcher, not an authorization boundary. Absolute native invocation retains the same guest permissions and cannot write protected metadata.
- The proxy rejects shell execution, config/repository overrides, external tools, `git push`, `git init`, and unapproved fetch remotes. The read-only [`jj.toml`](./jj.toml) is the single authority for trusted editor, formatter, and signing settings; proxy command construction does not override it. It can still perform logically destructive but recoverable allowed history edits.
- For a proxy route, socket failure returns `125` and never falls back to native JJ. A local route does not connect to the proxy.
- A command timeout returns `124`; policy/request failures normally return `2`. Inspect stderr, correct the request, and retry.
- Recover history edits with `jj undo` or an explicit `jj op restore <operation>`. If the proxy was interrupted during a metadata write, stop the agent, inspect/recover the repository from a trusted environment, then restart the whole proxy session.

## Tests

From the repository root:

```sh
cargo test --locked --manifest-path tools/jj-proxy/Cargo.toml
python3 -m unittest discover -s tools/jj-proxy/tests -p '*_test.py'
docker build -f tools/jj-proxy/Dockerfile -t jj-proxy .
```

The Rust suite covers command and Landlock execution policy plus protocol behavior. Python tests cover routing, client framing, and the trusted split editor. Wrapper tests also cover local dispatch with a mounted proxy, target-scoped attribution, and private split identity. The image build also runs release Rust tests, including secure-config preparation against its pinned Jujutsu binary. These checks do not establish acceptance in a real container.

## Design and reference

For the security model, mount topology, protocol, and rationale, read the [design](./design.typ).
The checked-in [`policy.toml`](./policy.toml) is the policy source; [`src/policy.rs`](./src/policy.rs) embeds and evaluates it. It is authoritative for recognized command paths, blocked privilege-crossing options, execution mode, author hooks, and fetch-remote expansion. This policy is not a complete per-command grammar: ordinary option and operand validation remains with the pinned Jujutsu binary. The executor consumes the evaluator’s decision rather than repeating command-policy checks.
See the [tools overview](../README.md).
