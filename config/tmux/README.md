# tmux

## Clipboard environment

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

## Moving panes between windows

Ctrl+K, then Alt+W moves the active pane to the next window in the current
session and follows it. Repeating the binding cycles through windows, wrapping
from the last to the first. It works from split windows too. Moving the only
pane out of a window removes that empty window; with only one window, the
binding leaves the layout unchanged. Ctrl+K, then Shift+W breaks a pane into
its own window.

## Keybinding troubleshooting

Check the terminal's own mappings before changing a tmux binding. In
[Kitty's configuration](../kitty/kitty.conf), Ctrl+Page Up/Down switches Kitty
tabs and Shift+Page Up/Down scrolls Kitty's history. Kitty handles those keys
before tmux sees them, even when the action has no visible effect.

After editing tmux bindings, reload with Ctrl+K, then `r`. Inspect the loaded
binding and pane state from inside the affected tmux session:

```sh
tmux list-keys -T root M-PgUp
tmux display-message -p 'alternate=#{alternate_on} mode=#{pane_in_mode}'
```

`alternate=1` means the application uses the alternate screen, typically an
editor or pager. `mode=1` means tmux is in a pane mode, such as copy mode;
it does not identify editors. Plain Page Up enters tmux history only when both
values are zero. Alt+Page Up/Down switches sessions even in the alternate screen,
but preserves tmux pane modes. See [tmux.conf](tmux.conf) for the bindings.

## Keybinding tests

Run from the repository root:

```sh
dev/test-environment python3 tests/tmux/keybindings_test.py
```

The tests load the relevant bindings into an isolated tmux server and inject keys
through an attached client. They skip if tmux or its `send-keys -K` option is
unavailable. The configured copy commands use `-CP`, which requires tmux 3.6 or
newer. On older versions, Enter/y binding equality is checked, but execution of
the copy-cleanup pipeline is skipped. A passing run with that skip does not
verify the copy pipeline; use tmux 3.6 or newer to exercise it.
