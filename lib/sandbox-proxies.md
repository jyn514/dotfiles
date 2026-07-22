# Sandbox command proxies

`codex-sandbox` always adds its trusted `jj` proxy using the image builder from
the dotfiles checkout that contains the launcher. A sandboxed repository may
also provide `.agents/sandbox/proxy-commands.json` for additional proxies. The
version 1 manifest format is documented in `designs/sandbox-proxies.typ`.
Repositories that need no additional proxy may omit the file or provide an
empty manifest:

```json
{"version": 1, "commands": {}}
```

Each `image-command` runs once, from the trusted startup checkout, and must
print one immutable `sha256:` image ID. A proxy image must:

- start the fixed server named by `argv`;
- bind `/run/sandbox-proxy/socket` only after initialization succeeds; and
- include the fixed byte-forwarding client at
  `/trusted/bin/sandbox-proxy-forward` for host-side routing.

Repository-local commands cannot replace the trusted `jj` command. The
launcher resolves its own real path before passing the absolute trusted image
builder path into the immutable session manifest.

The launcher mounts the repository read-only in each proxy, applies only the
manifest's declared overrides, and mounts each socket volume read-only in the
agent. It rejects malformed manifests, unsafe paths, mutable image references,
and missing mount sources before the agent starts. The validated manifest is
snapshotted once per session, so later checkout edits cannot change the running
policy. If a proxy exits, the launcher terminates and cleans up the agent
session rather than leaving a partially available sandbox running.

Jujutsu atomically links temporary objects between `.jj` and `.git`, so putting
those directories on separate bind mounts fails with `EXDEV`. Its proxy uses
one writable repository bind to preserve filesystem identity, while its
fail-closed Landlock policy grants write operations only beneath `.git`, `.jj`,
its private configuration directory, and its socket directory. Ordinary
working-copy files remain immutable to the proxy. The agent receives no direct
metadata mount.

The same policy permits execution only beneath `/trusted/bin`, providing the
working-tree `noexec` property on both Docker and Podman without unsafe syscall
bindings or a hard-coded kernel ABI.

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
