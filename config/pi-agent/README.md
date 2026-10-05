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
