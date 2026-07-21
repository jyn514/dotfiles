# Sandbox command proxies

`codex-sandbox` reads `.agents/sandbox/proxy-commands.json` before starting any
container. The version 1 manifest format is documented in
`designs/sandbox-proxies.typ`. Repositories that do not need an additional
proxy still provide an empty manifest:

```json
{"version": 1, "commands": {}}
```

Each `image-command` runs once, from the trusted startup checkout, and must
print one immutable `sha256:` image ID. A proxy image must:

- start the fixed server named by `argv`;
- bind `/run/sandbox-proxy/socket` only after initialization succeeds; and
- include the fixed byte-forwarding client at
  `/trusted/bin/sandbox-proxy-forward` for host-side routing.

The launcher mounts the repository read-only in each proxy, applies only the
manifest's declared overrides, and mounts each socket volume read-only in the
agent. It rejects malformed manifests, unsafe paths, mutable image references,
and missing mount sources before the agent starts. The validated manifest is
snapshotted once per session, so later checkout edits cannot change the running
policy. If a proxy exits, the launcher terminates and cleans up the agent
session rather than leaving a partially available sandbox running.

The Jujutsu manifest grants the proxy read-write access only to `.git` and
`.jj`. Its repository mount remains read-only, so proxy commands can update
Jujutsu and colocated Git metadata but cannot modify ordinary working-copy
files. The agent receives no direct metadata mount.

The Jujutsu proxy additionally installs a fail-closed Landlock policy before
binding its socket. The policy permits execution only beneath `/trusted/bin`,
providing the working-tree `noexec` property on both Docker and Podman without
unsafe syscall bindings or a hard-coded kernel ABI.

## Host routing

A command-specific host shim constructs its framed request, then invokes the
generic router with the repository, manifest key, and local trusted entrypoint:

```sh
sandbox-proxy-route \
  --repo "$repository" \
  --command example \
  -- local-example-bridge
```

The request and response remain on standard input and output. If no sandbox
owns the repository lock, the router runs the local entrypoint. During a
sandbox session it validates the published container identity and executes only
the image's fixed byte-forwarding client. Proxy failures never fall back to the
local entrypoint.
