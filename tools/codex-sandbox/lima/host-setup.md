# Provision the Lima sandbox host

This opt-in setup requires Apple Silicon macOS, Python 3, and Lima 1.2.1.
It creates `sandbox-host` with four CPUs, 4 GiB memory, and a 64 GiB disk, using
the [validated stack](stack-review.md). Select Lima explicitly after setup using
the [launch guide](launch.md).

## Set up and inspect

Run setup from a trusted checkout. It shares your home directory writable at the
same absolute path in the VM, so new repositories and configuration beneath home
need no separate share list or restart:

```sh
python3 tools/codex-sandbox/lima/host.py setup
python3 tools/codex-sandbox/lima/host.py status
python3 tools/codex-sandbox/lima/host.py check-bind --write "$HOME/src/dotfiles"
```

This trusts the VM with home access, including host configuration and control
state. Containers retain the launcher's existing narrow mounts, read-only metadata,
and hidden policy overlays; whole-home container binds are rejected.
Symlinks resolve to their actual targets: paths outside home still require a
separately configured VM share.

Lima 1.2.1 leaves spaces unescaped in generated fstab entries. Setup repairs only
the exact recorded entries, then verifies the mounted virtiofs root, device tag,
and access mode. An ordinary guest directory cannot stand in for an absent share.

Setup owns `~/.local/state/codex-sandbox-lima`, which must be private to the host
user. Its scratch directory is already covered by the home share; with external
state, only the scratch subdirectory is added as another share. `--state DIRECTORY`
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

After interrupted setup, rerun the original `setup` command.
The pending record retains the generation and source snapshot. For an interrupted
installation, setup force-stops the identity-checked, unpublished VM before
restarting it. This repairs Lima's possible host-agent PID
without a socket; ready shared VMs do not take this recovery path.
If the VM was deleted after installation began, setup refuses to create a replacement under
that identity. Retain the record for recovery and use a new state directory and
instance name. No operation deletes other Lima instances or Podman resources.

## Run the disposable gate

Fixture setup can override the home default with `--share-read DIRECTORY` and
`--share-write DIRECTORY`. Explicit shares must not overlap or expose the fixture's
control directory; these options are not part of ordinary launcher setup.

`python3 tools/codex-sandbox/tests/lima_home_share_integration.py` checks the normal
home-sharing host with non-root and root containers: the VM can read an unmounted
sentinel, containers cannot, and repository metadata remains read-only.

```sh
python3 tools/codex-sandbox/tests/lima_host_test.py
python3 tools/codex-sandbox/tests/lima_host_integration.py > /tmp/lima-host-gate.log 2>&1
```

The integration test creates its own named VM and temporary host sources. It
checks real SIGTERM recovery, interrupted readiness publication, idempotent setup,
live edits, paths with spaces, a writable checkout beneath
a read-only parent, protected metadata, hidden overlays, the network fixture,
and reboot. It also runs the [runtime contracts](runtime.md) before and after
reboot, including local base images and host SIGTERM cleanup.
It also exercises dummy boot credentials before and after reboot, then deletes
its owned VM. Actual linked-worktree sessions, production
credential migration, and the default switch remain later gates.

New hosts install the [boot credential cache](credentials.md) and relay-network helpers.
Hosts provisioned before these helpers were included require a new owned instance;
ordinary startup never installs new executable code from the checkout.
