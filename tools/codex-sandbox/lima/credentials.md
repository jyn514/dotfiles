# Provision the GitHub boot credential

The Lima credential helper stores `codex-sandbox/github-token` in the macOS login
Keychain. First use in each VM boot requests Keychain approval; later containers
reuse a private guest tmpfs cache. Ordinary launches still use Podman until the
full-session migration gates pass.

Import the existing Podman secret once:

```sh
python3 tools/codex-sandbox/sandbox_credentials.py import-podman
```

Import captures the secret in memory and calls the native Security API. It does
not overwrite an existing Keychain item or delete the Podman rollback secret.
Neither the token nor its value appears in command arguments, logs, or host
staging files.

After [provisioning a host](host-setup.md) with boot-credential support, prepare
its cache:

```sh
python3 tools/codex-sandbox/sandbox_credentials.py prepare
```

Choose **Allow**, not **Always Allow**, in the Keychain prompt. The item has no
trusted applications; the helper rejects retrieval if an unprompted decrypt
grant was added. Remove that grant using Keychain Access before retrying. A denied
prompt or interrupted transfer blocks startup and leaves no usable partial cache.

`--state DIRECTORY`, before the operation, selects a separately provisioned host.
The helper verifies the installed guest implementation and pins cache access to
both the VM generation and kernel boot ID. Concurrent requests share one guest
lock, held through approval and atomic publication. Reboot discards the cache;
container exit and session cleanup preserve it.

To require another retrieval for future containers during the same boot:

```sh
python3 tools/codex-sandbox/sandbox_credentials.py invalidate
```

Invalidation removes the current cache file; it does not revoke tokens already
received by running containers.

The Lima launcher mounts the boot-cache file read-only. Its trusted entrypoint
uses the agent's existing container-local sudo permission to read that file,
exports `GH_TOKEN`, and executes Pi as the original non-root user. The token stays
out of persistent containerd environment metadata; reusable Codex/Zulip
credentials remain separate. There are no
per-agent credential copies or additional credential cleanup operations. This
does not grant access to the guest filesystem outside declared mounts.

The cache is outside host shares, with directory mode `0700` and file mode `0600`.
Preparation refuses guests with active swap, because tmpfs can otherwise page to disk.
Unsandboxed host processes running as the macOS user and host root can still
retrieve it through Lima access while populated. Agent containers receive neither
Lima SSH credentials nor a VM-management socket.

## Verify without production credentials

```sh
python3 tools/codex-sandbox/tests/boot_credential_test.py
python3 tools/codex-sandbox/tests/keychain_integration.py
python3 tools/codex-sandbox/tests/lima_host_integration.py
```

The macOS test creates and deletes its own keychain, verifying dummy import,
empty decrypt ACLs, denied unprompted access, and duplicate rejection. The Lima
gate uses dummy retrieval to exercise concurrent launches, read-only injection,
metadata exclusion, session reuse, denial/retry, and reboot invalidation.
