# Pi configuration

This directory mirrors `~/.pi/agent/`. Setup links individual files with a
recursive Dotbot glob, leaving sessions, credentials, installed packages, and
other machine-local files in the home directory. The `pi-codex-subagents/agents/`
directory is linked as a whole and excluded from the file glob to avoid linking
its contents twice. `breq.md` is a source symlink to the shared instructions in
`config/agents/`.

Run `./setup dotfiles` from the repository root on the host to update an
installation. Conflicting regular files move to `~/.local/config/`; setup does
not back up or replace the whole agent directory. Adding a configuration file
needs no new manifest entry.

See the [extension bundle](pi-extensions/README.md) for loading, reloading,
compaction, side conversations, and asynchronous questions. Follow the
[development guide](../../dev/README.md#testing-and-probes) before running tests
or probes.

## Installation and update routes

Pi has separate installation and update paths. Choose the owner for the component
being changed; a test dependency update does not update the running application.

| Component | Owner | How an update reaches it |
| --- | --- | --- |
| Host Pi executable | [Installer](../../libexec/setup/install_pi.py) | `mise run pi-install` rebuilds and installs the fork. See the [sandbox installation guide](../../tools/codex-sandbox/README.md#purpose). |
| Guest tool worker | [Sandbox operator guide](../../tools/codex-sandbox/README.md#purpose) | Fresh sandboxes use the installed host Pi commit; existing workers require the documented restart. |
| Libraries used by dotfiles tests | [Manifest](../../package.json) and [lockfile](../../package-lock.json) | Update the manifest and lockfile, then install locked dependencies through the [testing guide](../../dev/README.md#testing-and-probes). |
| Dotfiles' local extensions | [Extension bundle](pi-extensions/README.md) | Setup links new files; `/reload` loads code changes in Pi. |
| Separately packaged extensions | [Package references](settings.json) | Settings select sources; `pi update --extensions` updates host package checkouts. Reload Pi afterwards. |

For package-update options, use the installed Pi's `pi update --help`.
The sandbox [runtime documentation](../../tools/codex-sandbox/README.md#prerequisites-and-setup)
explains how packaged extensions affect the guest image cache.
