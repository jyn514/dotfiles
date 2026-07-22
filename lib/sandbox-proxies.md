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
agent. Concurrent sandboxes for one checkout attach to the same proxy set and
reuse its validated manifest snapshot. A short exclusive coordination lock
serializes discovery and creation; each launcher then holds a shared session
lock until it exits. The final holder removes the shared proxies. It rejects
malformed manifests, unsafe paths, mutable image references, and missing mount
sources before the first agent starts. If a proxy exits, each attached launcher
terminates its agent session rather than leaving a partially available sandbox
running.

Jujutsu atomically links temporary objects between `.jj` and `.git`, so putting
those directories on separate bind mounts fails with `EXDEV`. Its proxy uses
one writable bind to preserve filesystem identity. For a linked Git worktree,
that bind starts at the nearest common ancestor of the worktree, its `gitdir`,
and its common Git directory. A fail-closed Landlock policy permits reads only
from the selected worktree, its resolved metadata, and trusted runtime files;
it permits writes only beneath the resolved Git metadata, `.jj`, its private
configuration directory, and its socket directory. Ordinary working-copy files
remain immutable to the proxy, and sibling repositories under a common mount
are unreadable. The agent receives no direct writable metadata mount.

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
