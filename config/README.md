# Configuration

[`install.conf.json`](../install.conf.json) maps these sources to installed paths.
Run `./setup dotfiles` from the repository root on the host after a layout change
to refresh old symlinks. Conflicting regular files move to `~/.local/config/`.

## Grouped sources

Files use their installed names under `LaunchAgents/`, `applications/`, `nvim/`,
`tmux/`, `zsh/`, and `kitty/`. Dotbot globs link individual files rather than
replacing these directories, leaving local plugins, generated desktop entries,
and unmanaged configuration in place.

Zsh uses an explicit dotfile glob; Neovim uses a recursive file glob. Add files
matching the group's glob without adding manifest entries. The tmux script
sources are symlinks to their implementations in `libexec/tmux/` and `bin/`;
edit those implementations, not copies.

## Agent instructions

The always-loaded [shared instructions](agents/shared-agents.md) link coding tasks
to [Change with evidence](../skills/references/change-with-evidence.md), a plain
reference under the existing `~/.agents/skills` directory link. The sandbox's
live skills mount exposes it to existing workers without a new mount or restart.
Reload the harness's instructions after changing the route. The reference is not
an `@` include or registered skill, so its rules stay out of the startup prompt.

## Pi

See [Pi configuration](pi-agent/README.md) for installation, machine-local state,
and the [extension bundle](pi-agent/pi-extensions/README.md) for extension usage.

## Persistent tmux on Linux

On machines with systemd and tmux installed at `/usr/bin/tmux`, install the
configuration links with `./setup dotfiles`, then run:

```sh
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable tmux.service
```

Lingering starts the user manager at boot and keeps it running after logout.
The [tmux service](systemd/user/tmux.service) starts an empty server under
`default.target`, independent of the graphical session. Run `tmux` to create a
session or `tmux attach` to reconnect. Closing the last session leaves the server
running. Sessions survive desktop logout, but not reboot.

If no tmux server is running, start it now with
`systemctl --user start tmux.service`. Otherwise, leave existing sessions running
and let the service start on the next boot; starting the service cannot adopt an
existing server. Stopping or restarting the service kills its sessions.
