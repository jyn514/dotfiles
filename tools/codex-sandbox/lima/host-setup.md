# Provision the Lima sandbox host

This opt-in setup requires Apple Silicon macOS, Python 3, and Lima 1.2.1.
It creates `sandbox-host` with four CPUs, 4 GiB memory, and a 64 GiB disk, using
the [validated stack](stack-review.md). It does not enable Lima in the launcher.

## Set up and inspect

Run setup from a trusted checkout. Pass each existing source directory explicitly;
the guest sees it at the same absolute path. For example:

```sh
python3 tools/codex-sandbox/lima/host.py setup \
  --share-write "$HOME/src" \
  --share-write "$HOME/.pi" \
  --share-read "$HOME/.codex"
python3 tools/codex-sandbox/lima/host.py status
python3 tools/codex-sandbox/lima/host.py check-bind --write "$HOME/src/dotfiles"
```

Add separate roots for external worktrees or metadata, dedicated authentication,
and optional integrations when they are needed. Parent and child shares cannot
overlap. Symlinks resolve to their actual host targets; a target outside the
configured roots is rejected. Read-only shares cannot supply writable binds.
These VM shares do not grant container access: the launcher must still construct
its read-only metadata and hidden policy overlays.

Lima 1.2.1 leaves spaces unescaped in generated fstab entries. Setup repairs only
the exact recorded entries, then verifies the mounted virtiofs root, device tag,
and access mode. An ordinary guest directory cannot stand in for an absent share.

Setup owns `~/.local/state/codex-sandbox-lima`, which must be private to the host
user. Only its `scratch` subdirectory is shared. Keep the control directory and
its installed-source snapshot outside all project shares. `--state DIRECTORY`
before the subcommand selects a separate control directory; setup's
`--instance sandbox-host-SUFFIX` selects a separate owned VM.

Setup snapshots provisioning sources, records ownership before creation, installs
the public-only CNI policy, and publishes readiness after verification. Repeating
the same setup preserves the VM generation. A changed share set, replacement VM,
altered configuration, or changed installed policy is rejected. Setup does not
adopt an existing instance without its ownership record.

## Start and recover

```sh
python3 tools/codex-sandbox/lima/host.py start
python3 tools/codex-sandbox/lima/host.py stop
```

`start` verifies installed state without executing provisioning from the current
checkout. `stop` is an explicit operator action; session cleanup must not stop
this shared VM. A stopped VM's `status` reports configuration identity but cannot
check guest state until it starts.

After interrupted setup, rerun the original `setup` command with the same shares.
The pending record retains the generation and source snapshot. If the VM was
deleted after installation began, setup refuses to create a replacement under
that identity. Retain the record for recovery and use a new state directory and
instance name. No operation deletes other Lima instances or Podman resources.

## Run the disposable gate

```sh
python3 tools/codex-sandbox/tests/lima_host_test.py
python3 tools/codex-sandbox/tests/lima_host_integration.py > /tmp/lima-host-gate.log 2>&1
```

The integration test creates its own named VM and temporary host sources. It
checks real SIGTERM recovery, interrupted readiness publication, idempotent setup,
live edits, paths with spaces, a writable checkout beneath
a read-only parent, protected metadata, hidden overlays, the network fixture,
and reboot. It deletes its owned VM on exit. Credential migration, actual
linked-worktree sessions, runtime selection, and the default switch remain later
gates.
