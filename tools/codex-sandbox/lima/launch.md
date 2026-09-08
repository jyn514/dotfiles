# Launch an opt-in Lima sandbox

Podman remains the default. Lima uses the same repository mounts, command proxies,
host editor, and optional Agent Podman worker, with outer images built in its
own containerd store. The global `docker` command and worker engine are unchanged.

## Prepare the host

Follow [host setup](host-setup.md) from a trusted checkout. Share the repository,
resolved skills directory, persistent Pi directories, and external repository
metadata writable; share the dotfiles tool checkout and Codex configuration
read-only unless they are also the working repository. The launcher checks guest
visibility before building images or creating session resources.

For configured integrations, also share the dedicated Codex authentication
directory writable and the Agent Podman access directory read-only. Shares are
directories: if your Zulip credential is directly in your home directory, place
its regular mode-0600 file in a dedicated shared directory and set
`CODEX_SANDBOX_ZULIPRC` to that file. The default remains `~/.zuliprc`; symlinked
credentials are rejected. Do not share the whole home merely to expose one file.

New hosts install the relay creator as trusted VM code. Older hosts lacking this
helper need a new owned instance; launch does not upgrade installed policy from
the current checkout.

Import the existing GitHub secret following [Keychain provisioning](credentials.md).
The first credential use after each VM boot requires approval; subsequent launches
reuse the private guest tmpfs cache. Denied approval blocks startup.

## Select the runtime

From a repository whose image builders use `sandbox-image`:

```sh
CODEX_SANDBOX_RUNTIME=lima codex-sandbox --help
CODEX_SANDBOX_RUNTIME=lima codex-sandbox
```

For a separate test host, also set `CODEX_SANDBOX_LIMA_STATE` to its host-state
directory. That selection reaches the launcher, shared proxies, and image
builders. Missing or incompatible state is an error; there is no engine fallback.
The dotfiles builders are migrated; external repository builders must be migrated
before their Lima launch. See the [image helper contract](runtime.md#image-helper).

Shared services retain their recorded engine and VM identity. End the repository's
active sessions before changing engines, then run:

```sh
python3 tools/codex-sandbox/sandbox-proxies.py reset --repo "$PWD"
CODEX_SANDBOX_RUNTIME=podman codex-sandbox
```

Reset uses the recorded owner even when the current default differs. Failed
cleanup retains recovery metadata and reports its path; do not delete that record
or redirect it to a replacement VM. Normal session exit never stops the shared VM
or invalidates its boot credential.

## Exercise an owned host

The integration fixture needs dotfiles shared read-only and an existing writable
test directory. It creates a disposable home/repository, supplies only a dummy
GitHub credential, checks the non-root entrypoint and protected mounts, and runs
two real PTY launches. It exercises host and agent Jujutsu routing, router SIGTERM,
authenticated host editing, and a Codex sidecar with dummy credentials and no
upstream requests, then resets shared proxies. The caller owns VM teardown.

```sh
python3 tools/codex-sandbox/tests/lima_launcher_integration.py \
  --state /path/to/test-host-state --work /path/to/shared-test-directory
```

The fixture labels its deliberate relay-collision traceback and cleanup warnings
as `EXPECTED FAILURE`, explains nerdctl's existing-volume warnings, and announces
the two expected Pi help screens. A successful run ends with `PASS: all Lima
launcher checks and cleanup completed; dummy boot credential invalidated.` and
exit status zero; an earlier passing check does not establish overall success.

This opt-in path precedes the macOS default switch. External-repository migration,
configured integration smoke tests, full interruption/recovery validation, and
rollback remain cutover gates.
