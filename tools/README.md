# Tools reference

Every tracked `tools/` subsystem is indexed here. Follow linked READMEs and designs for operational or security detail.

## Agent infrastructure

- [`agent-permissions`](agent-permissions/) defines agent command policy and renders Codex rules or Claude settings: `render.clj codex POLICY` or `render.clj claude POLICY BASE-SETTINGS`. Policy changes alter agent authority.
- [`agent-podman`](agent-podman/) manages a disposable, network-restricted Podman Machine for macOS agent workloads. See the [operator README](agent-podman/README.md) and [CI design](agent-podman/ci-design.typ).
- [`agent-split`](agent-split/) performs deterministic, patch-level `jj split` operations with `bb agent-split`. It rewrites history; start with the [operator guide](agent-split/README.md), then consult the [design and safety contract](agent-split/design.typ).
- [`codex-sandbox`](codex-sandbox/) launches Pi or Codex in an isolated container with trusted Git, Jujutsu, authentication, editor, and optional Zulip or Podman bridges. Its internal [`auth-proxy`](codex-sandbox/auth-proxy/) keeps reusable Codex OAuth credentials outside agent containers. See the [operator guide](codex-sandbox/README.md); before changing security boundaries, read the [proxy design](codex-sandbox/proxy-design.typ).
- [`jj-proxy`](jj-proxy/) exposes restricted Jujutsu operations to untrusted containers without writable repository metadata. Start with the [operator guide](jj-proxy/README.md); the [design](jj-proxy/design.typ) covers its policy and threat model.
- [`pi-npm`](pi-npm/) pins npm dependencies installed in the sandboxed Pi image with `npm ci --ignore-scripts`. It has no user command.
- [`zulip-proxy`](zulip-proxy/) provides bounded, read-only Zulip transcript and topic access through `bin/zulip`. It requires `~/.zuliprc`; exported private-channel content remains sensitive. See the [operator guide](zulip-proxy/README.md).

## Repository and package commands

- [`cargo-aliases`](cargo-aliases/) implements `generate-cargo-fish-abbr [cargo-command]`, converting `cargo --list` aliases to Fish abbreviations on standard output.
- [`fork-github`](fork-github/) implements `fork-github REPOSITORY [DIRECTORY]`, cloning a GitHub repository and configuring upstream and personal remotes.
- [`gh-comments`](gh-comments/) implements `gh-comments <<REPOSITORY ISSUE>|URL>`, exporting a GitHub issue and its comments without publishing partial output.
- [`git-autosquash`](git-autosquash/) implements `git-autosquash [--rebase] [BASE] [ARGS...]`, selecting an upstream base before an interactive revise or rebase.
- [`git-backup`](git-backup/) implements `git-backup URL-OR-PATH DESTINATION`, creating a Git bundle and compressed checkout. It requires Git and tar with xz support and never overwrites its destination.
- [`git-hooks`](git-hooks/) implements the tracked pre-commit and pre-push hooks. They may block operations after inspecting staged files or relevant Rust pushes, but do not rewrite source files.
- [`package-inspection`](package-inspection/) implements `what-belongs`, `what-runs`, `what-package`, `pip-upgrade-all`, and `purge-removed`. The last two mutate installed packages and prompt without `--yes`.
- [`package-plan`](package-plan/) validates and applies cross-platform package policy through `dev/package-plan validate|show|matrix|explain|apply`. `apply` may elevate privileges and change repositories or packages. See the [operator guide](package-plan/README.md).
- [`remote-git-url`](remote-git-url/) implements `remote-git-url FILE LINE-START [LINE-END]`, producing a GitHub or GitLab source link and opening it when a graphical display exists.
- [`shell-boundaries`](shell-boundaries/) runs from `dev/test` and rejects new unsafe shell substitutions, filename pipelines, and persistent writes. `baseline.json` records existing debt.

## Desktop and shell commands

- [`man-page`](man-page/) implements `open-man-page [SECTION] PAGE`, trying OpenBSD and Ubuntu web manpages before native fallback. Web results require network access and a graphical opener.
- [`picker-actions`](picker-actions/) implements `picker-action copy|edit|open|search` for explicit or NUL-delimited selections. Actions may write the clipboard, inject tmux keys, launch an editor, or open a URL.
- [`prompt`](prompt/) implements `prompt-command` and `jj-info`, rendering shell and Claude prompts from host, path, Git, and Jujutsu state. Repository queries are read-only and time-bounded.
- [`shell-cache`](shell-cache/) implements `refresh-fish-cache`, transactionally refreshing generated Fish source when dependencies change while preserving the old cache on producer failure.
- [`shell-data`](shell-data/) validates the shared abbreviation file for shell loaders. Run `python3 tools/shell-data/main.py [FILE]`; it preserves expansions without interpreting shell syntax.
- [`take-a-break`](take-a-break/) displays a modal Zenity reminder and uses `wmctrl`, when available, to keep it above other windows.
- [`watch`](watch/) implements buffered `watch [-n INTERVAL] [-x SHELL] COMMAND...`, running commands in a PTY and replacing the terminal after each complete frame.

## Content and device tools

- [`extract-chat`](extract-chat/) extracts user and assistant turns from local Codex or Claude JSON/JSONL sessions. It supports session lookup, final-answer filtering, and per-session Markdown; output may expose private conversations.
- [`extract-chat-share`](extract-chat-share/) converts public ChatGPT or Claude share pages to Markdown. Claude extraction requires Safari automation on macOS; remote formats may change.
- [`lapwing-prototype`](lapwing-prototype/) is a compact, heap-free Lapwing stenography translator prototype for Moonlander/QMK. Start with its [README](lapwing-prototype/README.md), then the [firmware specification](lapwing-prototype/SPEC.md); it is not hardware-verified.
- [`moonlander`](moonlander/) implements `sync-moonlander` and `flash-moonlander` for ZSA Oryx synchronization and QMK compilation or flashing. These can change remote state, a QMK checkout, or hardware; `COMPILE_ONLY=1` avoids flashing. See the [operator guide](moonlander/README.md).
- [`pdf-optimize`](pdf-optimize/) implements `pdf-optimize INPUT [OUTPUT]`, using Ghostscript without image downsampling. It requires `gs`, `file`, and `du` and never overwrites its destination.
