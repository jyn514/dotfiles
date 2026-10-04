# Backup

`bin/backup` is the restic entrypoint. `setup backup` installs daily backups using
systemd on Linux or a system LaunchDaemon on macOS. Both upload as the dedicated
`restic` account to the repository configured in `restic.env`.

The old setup installed a current-user cron job, but the backup command requires
the `restic` user. The installer now verifies the native schedule and removes
only the exact old noon cron entry for this checkout.

## Install

Install restic and system Python (`/usr/bin/python3`) first. macOS needs Apple's
Command Line Tools for system Python. Linux needs systemd; other Linux schedulers
are not supported. Docker is needed only on hosts running Mica.

From the dotfiles checkout:

```sh
./setup backup
```

The installer prints the shell-quoted sudo command to stderr before elevation.
It creates the `restic` service account if absent and requires
`~/.local/config/restic.env` to be owned by restic with no group or other
permissions. It checks the file's metadata and readability without reading its
contents. Supply existing repository credentials yourself; installation never
initializes a repository or copies OAuth credentials.

To select installed binaries or a credential file explicitly:

```sh
python3 tools/backup/install.py --owner jyn --restic /usr/bin/restic --credentials /path/to/restic.env
```

Mica is included automatically when `~/.local/share/mica-agent/agent` exists.
Use `--no-mica` on a Documents-only host, or `--mica` to require her state.
Mica capture expects the `sandbox-host-docker` Lima socket and `mica-mica-1`
container. Installation records the Docker engine identity and checks the
`/state` bind mount; a changed engine or mount requires reinstalling.

Preview this host's configuration without sudo or scheduler changes:

```sh
python3 tools/backup/install.py --render /tmp/backup-review
```

Install again after editing the implementation. Scheduled jobs use root-owned
copies, not the mutable checkout. The installer refuses updates while a job is
running. Configuration is `/etc/dotfiles-backup.json`; staging and recovery state
are in `/var/lib/dotfiles-backup`.

## Schedule and status

Linux runs at noon local time, with `Persistent=true` to catch missed runs.

```sh
systemctl list-timers --all dotfiles-backup.timer
systemctl status dotfiles-backup.service
journalctl -u dotfiles-backup.service
sudo systemctl start dotfiles-backup.service
```

macOS runs at noon local time and when the daemon loads, including boot. launchd
coalesces runs missed during sleep into a run at wake. Its load-time run also
covers powering the machine off across noon. The daemon runs independently of
login and writes `/var/log/dotfiles-backup.log`.

```sh
sudo launchctl print system/com.jyn.backup
sudo launchctl kickstart system/com.jyn.backup
```

Do not use `kickstart -k`: it kills an active backup. Schedulers serialize their
job, and a file lock also prevents overlap with manual commands.

## What is backed up

Documents uploads the live `~/Documents` tree with tag `documents-backup` and the
historical `notes/` exclusion. As before, restic must be able to read the files;
an unreadable file makes the job fail rather than count as success.

Mica uses tag `mica-state` in the same repository. The job stops only her container
with a 60 second shutdown grace, copies the complete host directory behind
`/state`, restarts her, then uploads the copy as restic. Forced shutdown is
rejected. Notes are included. Symlinks are copied as links, without importing
their targets. Neither the model proxy nor the shared Docker VM is stopped.

Mica's working state remains owned by jyn. The staged copy is private to root and
restic, outside her writable mounts. A failed upload leaves the complete copy at
`/var/lib/dotfiles-backup/mica-state`; the next successful capture replaces it.
This does not back up the agent checkout, ignored archives outside `/state`,
proxy authentication, or the private runtime environment.

Both snapshots preserve the existing single-root restore layout. Each daily
backup is attempted even if the other fails. Retention remains manual: run
`backup prune` for Documents or set `BACKUP_TAG=mica-state` when pruning Mica.
The existing retention policy keeps 7 daily, 5 weekly, 12 monthly, and 3 yearly
snapshots. `backup check-subset` checks 5% of repository data; other restic
commands pass through, including `backup check` and `backup snapshots`.

## Verify the first backup and recover interruptions

An active schedule does not establish a successful backup. Run the job manually,
then verify a restored Mica snapshot against the staged copy:

```sh
# Linux
sudo systemctl start dotfiles-backup.service
sudo /usr/bin/python3 -I /usr/local/lib/dotfiles-backup/job.py verify-mica
# macOS: wait for the load-time backup to finish first
sudo /usr/bin/python3 -I /Library/dotfiles-backup/job.py verify-mica
```

Verification restores this host's latest `mica-state` snapshot, compares file contents,
directory names, and symlink targets, and removes the restored copy on success.
It does not compare changing live state. On failure it retains the restore under
`/var/lib/dotfiles-backup/restore-check` for inspection.

Before stopping Mica, capture writes a restart marker containing her exact
container ID. Normal errors and signals restart her in cleanup. systemd also
runs recovery when the service exits. After SIGKILL or power loss on macOS,
recovery happens on the next job; to recover immediately, run the installed
`job.py recover` as root using the platform path above. A recovery failure keeps
the marker and fails the job. A container already stopped before capture stays
stopped. Restart verification checks container liveness, not UI readiness.

## Tests

```sh
python3 -m unittest discover -s tools/backup/tests -v
python3 tests/setup/idempotence_test.py
shellcheck tools/backup/backup.sh
```

Tests use disposable restic repositories to verify restore layout and notes,
and a disposable Docker fixture for capture, failure, and restart behavior.
Linux units are checked with `systemd-analyze verify` when available; that check
needs a host environment where systemd can create its lookup sockets. macOS
plist structure is tested here; loading it needs a macOS host.
