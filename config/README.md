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

## Pi

See [Pi configuration](pi-agent/README.md) for installation, machine-local state,
and the [extension bundle](pi-agent/pi-extensions/README.md) for extension usage.
