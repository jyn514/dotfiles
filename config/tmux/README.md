# tmux

## Pi session restoration

tmux-resurrect saves sandboxed Pi conversations as `pi --session FILE --session-dir DIRECTORY`.
The Pi extension reports its current selected file and working directory at startup, session switches, and `/reload`.
The post-save hook checks that the reporting Pi process still belongs to that pane and that the file exists.
It records the SDK-selected conversation rather than the launch-time ID, fork source, prompt, or owner socket.
Ephemeral, not-yet-saved, and exited attachments retain their original snapshot commands and are not automatically restarted.
Native Codex and standalone Pi are outside this integration.

Restore with Ctrl+K, then Ctrl+R, as usual.
Main and `/split` panes each start a new sandbox owner and resume their saved conversation without sending an initial prompt.
This restores conversations and layout, not running tool processes or the original shared guest worker.
Existing panes are left running by resurrect's normal restore behavior.
Custom session directories and quoted file paths are preserved.

After installing this change, reload tmux with Ctrl+K, then `r`, and run `/reload` in each existing Pi pane.
Take a new resurrect save with Ctrl+K, then Ctrl+S; older snapshots do not contain the normalized resume commands.
The existing Dotbot `config/tmux/*` mapping installs `resurrect-pi.py` alongside the tmux configuration.

Run the save-hook tests with `dev/test-environment python3 tests/tmux/resurrect_pi_test.py`.
To include the installed plugin's actual save/restore scripts, set `TMUX_RESURRECT_PLUGIN`:

```sh
TMUX_RESURRECT_PLUGIN="$HOME/.config/tmux/plugins/tmux-resurrect" \
  dev/test-environment python3 tests/tmux/resurrect_pi_test.py
```

The native test uses a private HOME, a disposable tmux server, and a fixture `pi` command without model requests.
The installed Pi TUI publisher is exercised offline by `tools/codex-sandbox/tests/restart_hook_test.py`.

## Session attachment

The startup hook selects sessions by the source of their live clients.
See the [implementation plan](attachment-implementation-plan.md) for design and verification details.

All local clients share one source; each normalized SSH source IP is distinct, regardless of source port.
A session is eligible when it is detached or every attached client has a known, different source.
Detached sessions take priority, with tmux listing order preserved within each group.
The new session is excluded; if no candidate qualifies, it remains available.
Explicit session creation inside tmux, detached scripted creation, and named attachments retain their behavior.
Another client's earlier session switch does not prevent reuse for the incoming client.
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

Fish startup selects the 1Password agent only when `SSH_AUTH_SOCK` is unset or empty and the client is local.
Inside tmux, it uses the live source record for the client tmux selects for the current pane (the most recently active client when several qualify).
Remote, unknown, and detached clients retain their agent selection, and supplied socket paths are preserved.
Startup does not query agents, so a disconnected forwarding tunnel cannot block the shell while it checks agent availability.
The local agent uses `~/.1password/agent.sock` on Linux and 1Password's Group Containers socket on macOS.
Existing Fish shells can repeat the startup check with `source "$DOTFILES/lib/shell/ssh-agent.fish"`.
Run its selection regressions with `dev/test-environment python3 tests/setup/ssh_agent_test.py`.

## Clipboard environment

Terminal copies use OSC 52 with an explicit `c` clipboard selector because mosh 1.4 drops tmux's empty selector.
After reloading the configuration, detach and reattach to refresh terminal capabilities.
To check remote copying, enter `set-buffer -w hello` at the tmux command prompt, then paste locally.

If copying fails after reattaching, run `tmux info` and find `Ms` under the affected client's terminal entry.
`Ms: [missing]` means tmux cannot emit clipboard writes, even if the configuration parses successfully.
tmux 3.8 discards an `Ms` format that omits parameter 1; `%p1%.0s` consumes it without printing it before the explicit `c` selector.
The effective format should contain `52;%p1%.0sc;%p2%s`.

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

Ctrl+K, then Alt+W moves the active pane to the previous window in the current session and follows it.
Repeating the binding cycles from higher to lower window numbers, wrapping from the first to the last.
It works from split windows too.
Moving the only pane out of a window removes that empty window; with only one window, the binding leaves the layout unchanged.
Ctrl+K, then Shift+W breaks a pane into its own window.

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

To run compound tmux command text, use `source-file -` to parse standard input.
Passing the whole command as one CLI argument does not parse it as configuration:

```sh
tmux source-file - <<'TMUX'
if-shell -F '#{>:#{session_windows},1}' {
  display-message -p 'multiple windows'
} {
  display-message -p 'one window'
}
TMUX
```

Use an isolated server for probes that move panes or otherwise change session state.

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
