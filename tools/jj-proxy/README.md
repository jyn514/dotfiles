# JJ proxy operator guide

## Purpose

`jj-proxy` lets an untrusted agent use approved Jujutsu operations while repository metadata remains read-only in the agent container. A sibling proxy owns the writable metadata mount, validates requests, and runs a pinned `jj` with a scrubbed environment.

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

The sandbox launcher must validate all metadata indirections, create the private socket volume, mount the repository and metadata as specified by the design, set `JJ_PROXY_REPO`, `JJ_PROXY_GIT_DIR`, `JJ_PROXY_COMMON_DIR`, and `JJ_PROXY_JJ_REPO`, and wait for readiness before starting the agent. A manually started proxy without those mounts is not protected.

The agent-side `jj` wrapper needs `SANDBOX_PROXY_DIR`; `JJ_PROXY_REPO` defaults to `/src/work`. `JJ_USER` and `JJ_EMAIL` may set a validated identity.

## Common commands

Once the launcher has installed the wrapper, use ordinary commands:

```sh
jj status
jj diff
jj log
jj commit -m 'Describe the change'
jj rebase -r @ -d main
jj undo
jj git fetch --remote origin
```

The allowlist also covers common history, bookmark, file, and workspace operations.

## Safety and recovery

- Never mount the outer Docker/Podman daemon socket or write-capable protected-remote credentials into the agent container.
- Keep `.git` and `.jj` read-only there; all `jj` commands, including `status` and `diff`, must use the proxy.
- The proxy rejects shell execution, config/repository overrides, external tools, `git push`, `git init`, and unapproved fetch remotes. It can still perform logically destructive but recoverable allowed history edits.
- Socket or proxy failure is fail-closed: the client exits `125` and never falls back to local `jj`.
- A command timeout returns `124`; policy/request failures normally return `2`. Inspect stderr, correct the request, and retry.
- Recover history edits with `jj undo` or an explicit `jj op restore <operation>`. If the proxy was interrupted during a metadata write, stop the agent, inspect/recover the repository from a trusted environment, then restart the whole proxy session.

## Tests

From the repository root:

```sh
cargo test --locked --manifest-path tools/jj-proxy/Cargo.toml
python3 -m unittest discover -s tools/jj-proxy/tests -p '*_test.py'
docker build -f tools/jj-proxy/Dockerfile -t jj-proxy .
```

The Rust suite covers command and Landlock execution policy plus protocol behavior. Python tests cover the client framing and the trusted split editor. The image build also runs release Rust tests and verifies the pinned production build.

## Design and reference

For the security model, mount topology, protocol, and rationale, read the [design](./design.typ).
The implementation in [`src/policy.rs`](./src/policy.rs) is the current authority for accepted top-level commands and blocked options.
See the [tools overview](../README.md).
