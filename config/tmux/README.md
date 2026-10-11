# tmux

## Session attachment

The startup hook selects sessions by the source of their live clients.
See the [implementation plan](attachment-implementation-plan.md) for design and verification details.

All local clients share one source; each normalized SSH source IP is distinct, regardless of source port.
A session is eligible when it is detached or every attached client has a known, different source.
Detached sessions take priority, with tmux listing order preserved within each group.
The new session is excluded; if no candidate qualifies, it remains available.
Explicit session creation inside tmux, detached scripted creation, and named attachments retain their behavior.
Sources identify the connection seen by the server, so NAT or jump hosts can make machines share an IP.

Tailscale names are optional display labels; IP addresses define identity and remain the fallback label.
The approved capture path is `bin/tmux`, which records source identity before starting the real tmux with the same arguments.
It preserves the environment, terminal streams, and process group, forwards signals, and returns tmux's exit status.
Its private source record stays locked while the client process runs and is removed when the launcher exits.
An unlocked record left by a killed launcher is unknown and ignored.
One process-held lock per server serializes selection and switching; Tailscale lookup runs after release.

Direct binary invocations, clients started outside the launcher, and malformed SSH data have unknown sources.
An unknown incoming source can reuse only detached sessions; an unknown attached source disqualifies its session.
Unknown clients can still attach explicitly to any session.

Read attachment decisions with `journalctl -t tmux-session` on Linux.
Each selection logs the incoming client, PID, source IP (or `local`/`unknown`), and new session ID.
Rejected sessions name clients with the same or unknown source; unknown incoming sources explain their detached-only restriction.
If no session qualifies, the log states that the new session is kept.
These diagnostics use the selection snapshot and are emitted after the server lock is released.

Reload with `tmux source-file ~/.config/tmux/tmux.conf` and ensure `command -v tmux` resolves to this repository's `bin/tmux`.
If the shell cached another executable, clear its command cache or open a new shell.
Detach and reattach existing clients through the launcher to establish their source identities.
The launcher and locks use POSIX interfaces, but runtime verification currently covers Linux only.
Run the attachment regressions with `dev/test-environment python3 tests/tmux/attach_session_test.py`.

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

Use `tmux list-commands` to check command syntax supported by the installed
version. tmux does not support `-h`; local man pages may be unavailable.

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
