# Tools reference

Find existing commands by task before writing a helper or assembling a workflow by hand.
This index covers tracked `bin/` entrypoints, including aliases and platform-specific launchers, and `tools/` subsystems.
Links lead to the executable source or the subsystem's operational documentation; command names alone do not imply that a helper supports `--help`.
Keep this index current when adding, renaming, or removing a helper.

- [Launch and manage agents](#agent-infrastructure)
- [Move history and manage repositories or packages](#repository-and-package-commands)
- [Build, test, and inspect code](#build-test-and-inspect-code)
- [Control the desktop, clipboard, and shell](#desktop-and-shell-commands)
- [Connect to remote machines and manage files](#remote-machines-and-files)
- [Convert content and work with devices](#content-and-device-tools)

## Agent infrastructure

### Launchers

- [`pi`](../bin/pi) launches host Pi with sandboxed tools through `codex-sandbox`; ordinary interactive startup can start the sandbox runtime.
- [`codex`](../bin/codex) launches Codex with shared instructions, generated permissions, and the dotfiles profile; interactive startup repairs the session index.
- [`claude`](../bin/claude) launches Claude Code with expanded shared instructions and generated permission settings; it writes generated settings and can remove the legacy settings symlink.

### Permissions and configuration

- [`analyze-agent-permissions`](../bin/analyze-agent-permissions) analyzes Claude permission usage; implementation and policy live in [agent-permissions](agent-permissions/).
- [`agent-permissions`](agent-permissions/) defines agent command policy, renders Codex rules or Claude settings, and audits Claude command history against generated Bash permissions. Policy changes alter agent authority.
- [`codex-config`](codex-config/) moves Codex-generated project trust, model-availability, and hook-state tables from the tracked dotfiles profile into the untracked user config before launch and after exit.

### Sessions and coordination

- [`codex-archive-old`](codex-archive-old/) implements `codex-archive-old [--days N] [--apply]`, listing or archiving stale interactive Codex sessions through the app-server protocol.
- [`codex-import`](codex-import/README.md) repairs missing sessions in Codex's local index; completed repairs can remain after a failure, while transcripts stay unchanged.
- [`pi-codex-goal`](pi-codex-goal/README.md) provides persistent Pi goals and continuation; goal state is stored in session custom entries.
- [`pi-codex-subagents`](pi-codex-subagents/README.md) spawns and manages child Pi sessions, including durable pause; children can execute their configured tools.
- [`pi-session-search`](../bin/pi-session-search) searches and reads local Pi and Codex transcripts without resuming sessions; see the [CLI reference](pi-session-search/docs/cli-interface.md).
- [`pi-link`](pi-link/README.md) provides live-session messaging with message IDs and reply references; new sessions connect automatically.

### Sandbox runtimes and proxies

- [`agent-docker`](agent-docker/) manages the separate rootless Docker build VM on Linux and macOS. See the [setup and recovery guide](agent-docker/README.md).
- [`codex-sandbox`](codex-sandbox/) runs host Pi with a guest tool worker and trusted Git/Jujutsu proxies, optional Zulip authenticated egress, and nested Docker or R2 relays. Model providers and authentication stay native to host Pi; no Codex model broker is started. See the [operator guide](codex-sandbox/README.md); before changing security boundaries, read the [proxy design](codex-sandbox/spec/proxy-design.typ).
- [`sandbox-image`](../bin/sandbox-image) resolves, builds, refreshes, or rebuilds sandbox images; it can pull images and start the configured runtime. See [image development](codex-sandbox/development.md).
- [`sandbox-proxy-route`](../bin/sandbox-proxy-route) dispatches configured sandbox proxy requests; use the [sandbox proxy contract](codex-sandbox/spec/proxy-design.typ) before changing routing.
- [`jj-proxy`](jj-proxy/) exposes restricted Jujutsu operations to untrusted containers without writable repository metadata. Start with the [operator guide](jj-proxy/README.md); the [design](jj-proxy/design.typ) covers its policy and threat model.
- [`pi-npm`](pi-npm/) pins npm dependencies installed in the sandboxed Pi image with `npm ci --ignore-scripts`. It has no user command.
- [`zulip-proxy`](zulip-proxy/) provides bounded, read-only Zulip transcript and topic access through `bin/zulip`. It requires `~/.zuliprc`; exported private-channel content remains sensitive. See the [operator guide](zulip-proxy/README.md).

## Repository and package commands

### Move and repair history

Use the [Jujutsu workflow](../skills/jj-workflow/SKILL.md) to preserve authored work when integrating history changes.
These specialized Git helpers can change Git history or metadata directly.

| Task | Helper and important effects |
| --- | --- |
| Import commits between repositories, optionally selecting and relocating a directory | [`transplant-commits`](transplant-commits/README.md) writes target Git history/index; commit IDs change and merge commits are omitted. |
| Correct commits attributed to jyn instead of their agent committer | [`rewrite-commits`](../bin/rewrite-commits) previews matches; `--apply` rewrites author/committer metadata and synchronizes Git/JJ. |
| Promote a coauthor trailer to the primary author | [`coauthored-by-author`](../bin/coauthored-by-author) previews matches; `--apply` rewrites selected refs and removes the matching trailer unless `--keep-trailer` is supplied. |
| Filter repository history | [`git-filter-repo`](../bin/git-filter-repo) invokes the vendored history rewriter; apply operations rewrite commit IDs and can change refs. |
| Add Git colocation to an existing JJ workspace | [`jj-backfill-colocation`](../bin/jj-backfill-colocation) recreates the workspace, restores its files and sparse selection, and retains a recovery backup; changes workspace registration. |

- [`agent-split`](agent-split/) performs deterministic, patch-level `jj split` operations with `bb agent-split`. It rewrites history; start with the [operator guide](agent-split/README.md), then consult the [design and safety contract](agent-split/design.typ).
- [`git-autosquash`](git-autosquash/) implements `git-autosquash [--rebase] [BASE] [ARGS...]`, selecting an upstream base before an interactive revise or rebase.

### Browse and clone repositories

| Task | Helper and important effects |
| --- | --- |
| Show repository or directory status | [`show-status`](../bin/show-status) shows time-bounded JJ/Git status or lists a non-repository directory; requires a nonempty argument to run. |

- [`fork-github`](fork-github/) implements `fork-github REPOSITORY [DIRECTORY]`, cloning a GitHub repository and configuring upstream and personal remotes.
- [`gh-comments`](gh-comments/) implements `gh-comments <<REPOSITORY ISSUE>|URL>`, exporting a GitHub issue and its comments without publishing partial output.
- [`remote-git-url`](remote-git-url/) implements `remote-git-url FILE LINE-START [LINE-END]`, producing a GitHub or GitLab source link and opening it when a graphical display exists.

### Repository backups

| Task | Helper and important effects |
| --- | --- |
| Back up a repository under the historical command name | [`git-save`](../bin/git-save) uses the same bundle/archive implementation as [`git-backup`](git-backup/); writes a backup, not a commit. |

- [`git-backup`](git-backup/) implements `git-backup URL-OR-PATH DESTINATION`, creating a Git bundle and compressed checkout. It requires Git and tar with xz support and never overwrites its destination.

### Packages and repository checks

- [`package-inspection`](package-inspection/) implements `what-belongs`, `what-runs`, `what-package`, `pip-upgrade-all`, and `purge-removed`. The last two mutate installed packages and prompt without `--yes`.
- [`package-plan`](package-plan/) validates and applies cross-platform package policy through `dev/package-plan validate|show|matrix|explain|apply`. `apply` may elevate privileges and change repositories or packages. See the [operator guide](package-plan/README.md).
- [`git-hooks`](git-hooks/) implements the tracked pre-commit and pre-push hooks. They may block operations after inspecting staged files or relevant Rust pushes, but do not rewrite source files.
- [`shell-boundaries`](shell-boundaries/) runs from `dev/test` and rejects new unsafe shell substitutions, filename pipelines, and persistent writes. `baseline.json` records existing debt.

## Build, test, and inspect code

### Builds and tests

| Task | Helper and important effects |
| --- | --- |
| Watch Rust builds from the workspace root | [`b`](../bin/b) resolves Cargo workspace metadata and launches Bacon there. |
| Generate private Rust API documentation | [`cargo-doc-dev`](../bin/cargo-doc-dev) runs Cargo doc without dependencies and writes documentation output. |
| Run a project's Gradle | [`gradle`](../bin/gradle) prefers `./gradlew`, falling back to `/usr/bin/gradle`; executes the requested build tasks. |
| Run Clojure tests from the repository root | [`kaocha`](../bin/kaocha) runs `clojure -M:test` at the Git root. |

### REPLs

| Task | Helper and important effects |
| --- | --- |
| Start a Clojure REPL | [`clj`](../bin/clj) starts Rebel Readline with the development alias when available. |
| Start Julia | [`jl`](../bin/jl) passes arguments to `julia`. |
| Start a Perl debugger REPL | [`pl`](../bin/pl) enables strict mode and warnings. |

### Profiling and memory checks

| Task | Helper and important effects |
| --- | --- |
| Profile a program's calls | [`callgraph`](../bin/callgraph) executes it under Valgrind and writes callgrind, DOT, and PNG files; installs `gprof2dot` with pip if absent. |
| Compare call graphs | [`callgraph-cmp`](../bin/callgraph-cmp) compares unique DOT edges through Graphviz and diff using temporary files. |
| Check a program for memory leaks | [`leak-check`](../bin/leak-check) executes it under Valgrind memcheck. |

### Documentation and development servers

| Task | Helper and important effects |
| --- | --- |
| Find a Typst package version for a compiler | [`supports-typst-version`](../bin/supports-typst-version) queries Typst Universe and caches its package index locally. |
| Run the Lapwing learning sites locally | [`lapwing-start`](../bin/lapwing-start) starts mdBook and npm development servers from the configured personal checkout. |

## Desktop and shell commands

### Clipboard and selections

| Task | Helper and important effects |
| --- | --- |
| Copy a terminal selection without Fish prompts | [`copy-terminal-selection`](../bin/copy-terminal-selection) strips prompt text and writes a tmux buffer and clipboard. |
| Paste the primary selection into a graphical application | [`paste-primary`](../bin/paste-primary) temporarily swaps the clipboard, injects a paste key, then restores it. |
| Decode a QR code from a clipboard image | [`decode-qr`](../bin/decode-qr) uses zbarimg, writes the result to the terminal, and replaces the primary selection. |

- [`copy` and `paste`](copy/README.md) read and write graphical clipboards; copying replaces the selected clipboard contents.
- [`picker-actions`](picker-actions/) implements `picker-action copy|edit|open|search` for explicit or NUL-delimited selections. Actions may write the clipboard, inject tmux keys, launch an editor, or open a URL.

### Editors and opening files

| Task | Helper and important effects |
| --- | --- |
| Restore a local Neovim session | [`nvim`](../bin/nvim) loads `Session.vim` or `.session.vim` when started without arguments; otherwise forwards arguments. |
| Launch Helix through desktop/editor integration | [`hx-hax`](../bin/hx-hax) uses the [open dispatcher](open/README.md). |
| Launch an editor through desktop/editor integration | [`editor-hax`](../bin/editor-hax) uses the same [open dispatcher](open/README.md). |
| Open a Linux path in Windows Firefox | [`firefox.sh`](../bin/firefox.sh) converts the path with `wslpath` and launches the configured executable. |

- [`open`](open/) implements the basename-sensitive `open`, `hx-hax`, and `editor-hax` commands for desktop dispatch and editor integration, including managed [macOS file associations](open/macos-file-associations.md).
- [`man-page`](man-page/) implements `open-man-page [SECTION] PAGE`, trying OpenBSD and Ubuntu web manpages before native fallback. Web results require network access and a graphical opener.

### Shell startup and terminal tools

| Task | Helper and important effects |
| --- | --- |
| Print terminal colors and control sequences | [`ansi`](../bin/ansi) invokes the vendored ANSI generator. |
| Find directory completion candidates | [`complete-fzf-dir`](../bin/complete-fzf-dir) lists fd directories and zoxide history. |
| Generate Fish startup hooks | [`generate-fish-startup-cache`](../bin/generate-fish-startup-cache) writes generated shell code to stdout; the [shell cache](shell-cache/) owns persistent publication. |
| Show PATH entries in order | [`show_path`](../bin/show_path) prints PATH components without sorting. |
| Launch tmux with connection attribution | [`tmux`](../bin/tmux) records attachment provenance while forwarding native tmux arguments. |
| Start Zsh from Windows | [`zsh.bat`](../bin/zsh.bat) launches it through the Windows Bash/WSL entrypoint. |

- [`cargo-aliases`](cargo-aliases/) implements `generate-cargo-fish-abbr [cargo-command]`, converting `cargo --list` aliases to Fish abbreviations on standard output.
- [`prompt`](prompt/) implements `prompt-command` and `jj-info`, rendering shell and Claude prompts from host, path, Git, and Jujutsu state. Repository queries are read-only and time-bounded.
- [`shell-cache`](shell-cache/) implements `refresh-fish-cache`, transactionally refreshing generated Fish source when dependencies change while preserving the old cache on producer failure.
- [`shell-data`](shell-data/) validates the shared abbreviation file for shell loaders. Run `python3 tools/shell-data/main.py [FILE]`; it preserves expansions without interpreting shell syntax.
- [`watch`](watch/) implements buffered `watch [-n INTERVAL] [-x SHELL] COMMAND...`, running commands in a PTY and replacing the terminal after each complete frame.

### Desktop settings and devices

| Task | Helper and important effects |
| --- | --- |
| Change volume or media playback | [`audio`](../bin/audio) controls ALSA/cmus and sends desktop notifications unless `--quiet` is supplied. |
| Run a command on the user's D-Bus session | [`dbus-run-user`](../bin/dbus-run-user) supplies user runtime/bus environment variables; the command retains its own effects. |
| List desktop application launchers | [`desktop-files`](../bin/desktop-files) searches XDG application directories for `.desktop` files. |
| Launch KeePassXC from a desktop menu | [`keepassxc.desktop`](../bin/keepassxc.desktop) declares the launcher and KeePass database MIME type. |
| Run the window-session manager | [`lwsm`](../bin/lwsm) uses npm exec, which can download and execute `linux-window-session-manager`. |
| Show the active Wi-Fi network | [`ssid`](../bin/ssid) reads NetworkManager's active SSID. |
| Toggle GNOME notification banners | [`toggle-dnd`](../bin/toggle-dnd) changes and verifies the desktop notification setting. |

- [`macos-preferences`](macos-preferences/) checks, previews, and applies the semantic macOS preference policy in `lib/macos-preferences.json`. `apply` writes only differing keys and refuses to proceed while an affected application is running.
- [`plover-reconnect`](plover-reconnect/) automatically reconnects a configured Plover steno device after USB disconnection and reconnection. See the [operator README](plover-reconnect/README.md).
- [`take-a-break`](take-a-break/) displays a modal Zenity reminder and uses `wmctrl`, when available, to keep it above other windows.

## Remote machines and files

### Remote connections

| Task | Helper and important effects |
| --- | --- |
| Connect with SSH and diagnose an unavailable agent | [`ssh`](../bin/ssh) runs native SSH, then checks the configured authentication agent after connection failure. |
| Open synchronized SSH panes | [`tmux-cssh`](../bin/tmux-cssh) creates synchronized tmux sessions/windows; typed commands reach multiple remote machines. |
| Start mosh from Windows | [`mosh.bat`](../bin/mosh.bat) sources the profile and launches mosh through Bash/WSL. |
| Log in to an OverTheWire Bandit level | [`bandit`](../bin/bandit) reads the last credential in local `bandit.txt` and starts an SSH connection using sshpass. |

- [`mosh-agent`](mosh-agent/) keeps an autossh agent tunnel open alongside mosh, using a fixed remote socket for existing tmux shells.

### Transfers and backups

| Task | Helper and important effects |
| --- | --- |
| Synchronize the legacy notes vault with Google Drive | [`backup-notes.sh`](../bin/backup-notes.sh) runs rclone bisync; can modify both copies and resolves conflicts in favor of newer files. |

- [`backup`](backup/) backs up Documents and consistent Mica state to restic, using systemd timers on Linux and a LaunchDaemon on macOS.

### Local files and disk usage

| Task | Helper and important effects |
| --- | --- |
| Merge directory contents | [`merge`](../bin/merge) copies without overwriting destination entries and offers source removal only after a successful collision-free copy. |
| Replace literal text recursively | [`replace`](../bin/replace) rewrites every regular file below the current directory in place, including hidden and ignored files. |
| Inspect disk usage | `gdu -npx -- PATH` prints immediate files and directories in descending size without crossing filesystems; `gdu -x -- PATH` opens the interactive browser, which includes deletion actions. |

The local `usage` helper is retired; use gdu directly.
[Package setup](package-plan/README.md) already installs gdu on supported targets except Chimera, where the package policy skips it as unavailable.
Homebrew installs `gdu-go`; macOS local setup provides the `gdu` alias.

### User accounts

| Task | Helper and important effects |
| --- | --- |
| Create a user with an SSH key | [`makeuser`](../bin/makeuser) requires root, prompts, and creates the account and authorized key. |

## Content and device tools

### Data and transcript conversion

| Task | Helper and important effects |
| --- | --- |
| Convert EDN to JSON | [`edn-to-json`](../bin/edn-to-json) reads stdin or named files and prints JSON using Babashka. |
| Decode a printed character-code list | [`pretty.py`](../bin/pretty.py) parses a Python literal from stdin and prints the corresponding characters. |
| Convert timesheet intervals to decimal hours | [`hours`](../bin/hours) reads newline-separated cells from stdin and prints hours. |
| Format a copied GroupMe conversation | [`groupme2transcript`](../bin/groupme2transcript) reads stdin or `--input FILE` and writes a transcript to stdout. |

- [`clean-discord`](clean-discord/README.md) converts copied Discord text to IRC-style transcripts; in-place mode replaces the input file.

### Search and web archives

| Task | Helper and important effects |
| --- | --- |
| Search the web | [`ducker`](../bin/ducker), also [`ddg`](../bin/ddg), launches the installed Python search client. |
| Search YouTube playlists | [`youtube_search`](../bin/youtube_search) sends a site-restricted query to ddg. |

- [`archive-webpage`](archive-webpage/) implements `archive-webpage DIRECTORY URL [TITLE]`, saving a rendered page and JSON metadata through PhantomJS.
- [`search-bsky-likes`](search-bsky-likes/) finds media posts by `theotherhappyplace.bsky.social` liked by `jyn.dev`, then opens a temporary local gallery. See the [operator README](search-bsky-likes/README.md).

### Agent session exports and imports

- [`extract-chat`](extract-chat/README.md) exports local agent conversations to Markdown or HTML; exports may expose private text and replace existing output files.
- [`codex-to-pi`](codex-to-pi/README.md) converts a Codex conversation or share URL to Pi JSONL; writes a session file without resuming it.
- [`pi-to-codex`](pi-to-codex/README.md) creates a resumable Codex thread from a Pi session through unstable Codex interfaces; the source stays unchanged.
- [`extract-chat-share`](extract-chat-share/README.md) extracts shared ChatGPT/Claude conversations; URL inputs access the network and Claude uses Safari automation.

### Document previews and PDFs

| Task | Helper and important effects |
| --- | --- |
| Preview a Graphviz graph | [`view_dot`](../bin/view_dot) writes a sibling `.preview.svg` and opens it; replaces only its own marked previews. |
| Preview Markdown | [`view_markdown`](../bin/view_markdown) writes a sibling `.preview.html` and opens it; replaces only its own marked previews. |

- [`pdf-optimize`](pdf-optimize/) implements `pdf-optimize INPUT [OUTPUT]`, using Ghostscript without image downsampling. It requires `gs`, `file`, and `du` and never overwrites its destination.

### Images and device firmware

| Task | Helper and important effects |
| --- | --- |
| Download custom Discord emoji images | [`emojis`](../bin/emojis) reads markup through PowerShell and writes PNGs in the current directory; existing names can be overwritten. |

- [`lapwing-prototype`](lapwing-prototype/) is a compact, heap-free Lapwing stenography translator prototype for Moonlander/QMK. Start with its [README](lapwing-prototype/README.md), then the [firmware specification](lapwing-prototype/SPEC.md); it is not hardware-verified.
- [`moonlander`](moonlander/) implements `sync-moonlander` and `flash-moonlander` for ZSA Oryx synchronization and QMK compilation or flashing. These can change remote state, a QMK checkout, or hardware; `COMPILE_ONLY=1` avoids flashing. See the [operator guide](moonlander/README.md).
