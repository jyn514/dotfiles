# tmux clipboard environment

The [configuration](tmux.conf) refreshes `WAYLAND_DISPLAY` when creating or
attaching to a session. Attaching without that variable, such as over SSH,
preserves the previous value. This uses tmux's `update-environment` wildcard
support (tmux 3.2 or newer): `WAYLAND_DISPLA[Y]` matches exactly
`WAYLAND_DISPLAY`, while an absent match marks the pattern itself for removal.
`DISPLAY` remains excluded from refresh to preserve the existing SSH behavior.

After changing the configuration, reload it with
`tmux source-file ~/.config/tmux/tmux.conf`, then detach and reattach from a
terminal in the current desktop session. New panes receive the refreshed value.
Existing shells keep their environment. In Fish, update the current shell after
reattaching:

```fish
set -l display (tmux show-environment WAYLAND_DISPLAY)
and set -gx WAYLAND_DISPLAY (string replace -- 'WAYLAND_DISPLAY=' '' $display)
```
