# Provision the GitHub boot credential

On Linux, the Lima credential helper reads the dedicated read-only token from
`op://Private/agent sandbox token/token` with the 1Password CLI.
On macOS, it reads `codex-sandbox/github-token` from the login Keychain.
Every sandbox launch retrieves the current credential and atomically stages it
in a request-unique private guest tmpfs file before starting the container.
The staged file is transport, not a reusable credential cache.
The import command remains only as a macOS migration path for an existing Podman secret.

Import the existing Podman secret once:

```sh
python3 tools/codex-sandbox/sandbox_credentials.py import-podman
```

Import captures the secret in memory and calls the native Security API. It does
not overwrite an existing Keychain item or delete the source Podman secret.
Neither the token nor its value appears in command arguments, logs, or host
staging files.

After [provisioning a host](host-setup.md) with boot-credential support, test
credential retrieval and staging:

```sh
python3 tools/codex-sandbox/sandbox_credentials.py prepare
```

On macOS, a missing GitHub Keychain item skips the optional credential.
On Linux, the `op` CLI, its desktop integration, and the named token item are required;
retrieval failure is fatal and never falls back to host `gh`, `GH_TOKEN`, or `GITHUB_TOKEN` credentials.

Choose **Allow**, not **Always Allow**, in the Keychain prompt. The item has no
trusted applications; the helper rejects retrieval if an unprompted decrypt
grant was added. Remove that grant using Keychain Access before retrying. A denied
prompt or interrupted transfer blocks startup and leaves no usable partial cache.

`--state DIRECTORY`, before the operation, selects a separately provisioned host.
The helper verifies the installed guest implementation and pins staging access to
both the VM generation and kernel boot ID. Concurrent requests share one guest
lock, held through approval and atomic publication. Each request still retrieves
the credential independently; a staged value is never accepted as launch input.

Each request uses one SSH exchange. A host-owned Python entrypoint discovers
the current boot inside the guest and invokes the installed helper, which still
validates that boot and the generation before accessing the cache. The host
accepts only the returned credential path in that generation's staging namespace;
the launcher rejects an installed helper whose protocol hash does not match.
Deploying a changed helper requires the explicitly approved, session-disrupting
Lima-Docker upgrade described in [Docker setup](docker.md).

To remove the currently staged value without launching another sandbox:

```sh
python3 tools/codex-sandbox/sandbox_credentials.py invalidate
```

Invalidation removes the staged file; it does not revoke tokens already
received by running containers.

The Lima launcher mounts the staged file read-only. Its trusted entrypoint
uses the agent's existing container-local sudo permission to read that file,
exports `GH_TOKEN`, and executes Pi as the original non-root user. The token stays
out of persistent containerd environment metadata; reusable Codex/Zulip
credentials remain separate. There are no
per-agent credential copies or additional credential cleanup operations. This
does not grant access to the guest filesystem outside declared mounts.

The staging area is outside host shares, with directory mode `0700` and file mode `0600`.
Preparation refuses guests with active swap, because tmpfs can otherwise page to disk.
Unsandboxed processes running as the host user and host root can still retrieve
it through Lima access while populated. Agent containers receive neither
Lima SSH credentials nor a VM-management socket.

## Verify without production credentials

```sh
python3 tools/codex-sandbox/tests/boot_credential_test.py
python3 tools/codex-sandbox/tests/keychain_integration.py
python3 tools/codex-sandbox/tests/lima_host_integration.py
```

The macOS test creates and deletes its own keychain, verifying dummy import,
empty decrypt ACLs, denied unprompted access, and duplicate rejection. The Lima
integration test uses dummy retrieval to exercise per-launch staging, read-only
injection, metadata exclusion, denial/retry, and reboot invalidation.
