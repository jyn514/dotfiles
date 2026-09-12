# Launch an opt-in Lima sandbox

Lima-Docker is the default; this guide selects the alternative nerdctl backend.
Lima shares your home with the VM; containers keep
the launcher's narrow mounts, protected metadata, and isolated credentials.

## Prepare the host

Run once from dotfiles:

```sh
python3 tools/codex-sandbox/lima/host.py setup
python3 tools/codex-sandbox/sandbox_credentials.py import-podman
```

Setup automatically shares `$HOME` writable with the VM. Adding repositories or
configuration beneath home needs no VM share update or restart; nothing mounts
home wholesale into an agent container. Existing narrow test VMs remain separate.
See [host setup](host-setup.md) for lifecycle and recovery.

[Keychain](credentials.md) requests **Allow** once per VM boot; do not choose
**Always Allow**. Later launches reuse the guest tmpfs cache.

## Select the runtime

From a repository whose image builders use `sandbox-image`:

```sh
CODEX_SANDBOX_RUNTIME=lima codex-sandbox --help
CODEX_SANDBOX_RUNTIME=lima codex-sandbox
```

Interactive image builds show BuildKit's live terminal progress. Redirected output
uses plain progress logs.

Background runtime helpers do not read terminal input. If upgrading from the
version where Lima keystrokes stalled, exit existing sandbox sessions and relaunch
to replace their monitors; no VM restart is needed.

Each Lima session uses one SSH channel for its guest-side proxy monitor, plus
the agent attachment. The monitor reaps its local container waits on exit;
loss of supervision terminates the agent. Relaunch existing sessions to use it.

Each launch fully verifies the VM once and shares that result with its host-side
image and proxy helpers. Later checks validate VM identity and service activation
IDs; a VM reboot or containerd/BuildKit restart requires full verification again.
Successful launch checks are silent; failures still report their diagnostics.
Policy files and mounts are assumed unchanged within a launch; edits without a
service restart are checked at the next launch. The result is never saved to disk.
Mount preflight checks all sources in one guest request, preserving each source's
type, read/write access, and file-content checks.

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

The integration fixture needs dotfiles readable and an existing writable
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

This nerdctl path remains opt-in. External-repository migration,
configured integration smoke tests, full interruption/recovery validation, and
rollback remain cutover gates.
