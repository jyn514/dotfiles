# Tools reference

Every tracked `tools/` subsystem is indexed here. Follow linked READMEs and designs for operational or security detail.

## Agent infrastructure

- [`agent-permissions`](agent-permissions/) defines agent command policy, renders Codex rules or Claude settings, and audits Claude command history against generated Bash permissions. Policy changes alter agent authority.
- [`agent-docker`](agent-docker/) manages the separate rootless Docker build VM on Linux and macOS. See the [setup and recovery guide](agent-docker/README.md).
- [`agent-podman`](agent-podman/) retains lifecycle scripts for retired macOS Podman deployments. See its [teardown guide](agent-podman/README.md).
- [`agent-split`](agent-split/) performs deterministic, patch-level `jj split` operations with `bb agent-split`. It rewrites history; start with the [operator guide](agent-split/README.md), then consult the [design and safety contract](agent-split/design.typ).
- [`codex-archive-old`](codex-archive-old/) implements `codex-archive-old [--days N] [--apply]`, listing or archiving stale interactive Codex sessions through the app-server protocol.
- [`codex-config`](codex-config/) moves Codex-generated project trust, model-availability, and hook-state tables from the tracked dotfiles profile into the untracked user config before launch and after exit.
- [`codex-import`](../bin/codex-import) repairs missing synced sessions in Codex's local index while other Codex sessions run.
  The [`codex` wrapper](../bin/codex) runs it before interactive startup; import failures print a warning and startup continues.
  Administrative commands, help, version checks, and noninteractive commands such as `exec` skip startup import.

  A receipt in `CODEX_HOME/codex-import-receipt.json` avoids launching an app-server when index coverage and previously scanned unindexed files are unchanged.
  Indexed sessions can keep growing without invalidating the receipt.
  New files, changed unindexed files, deleted paths, lost index coverage, configuration changes, and replaced executables trigger a full repair.
  The fast path reads Codex 0.162.1's `state_5.sqlite` schema without modifying it; unsupported layouts and custom `sqlite_home` configuration fall back to full repair.
  Use `codex-import --force` to bypass the receipt, including when retrying a file Codex silently omitted during an earlier scan.

  Full repair starts a temporary `codex app-server --stdio` and pages through `thread/list` with scan-and-repair enabled for current and archived sessions, across providers and source kinds.
  It leaves the persistent daemon running and does not resume sessions, reset the backfill marker, or edit SQLite directly.
  Codex owns the index repairs; transcripts stay unchanged.

  Completion reports the number of sessions listed, not the number newly imported or a guarantee that every rollout parsed successfully.
  On failure, completed page repairs may remain; retry `codex-import`.
  It uses `CODEX_HOME` (default `~/.codex`) and requires `codex` and `python3`.
  The scan-and-repair behavior was verified with Codex 0.162.1; it depends on Codex's implementation of `thread/list`.
- [`codex-sandbox`](codex-sandbox/) runs host Pi with a guest tool worker and trusted Git/Jujutsu proxies, optional Zulip authenticated egress, and nested Docker or R2 relays. Model providers and authentication stay native to host Pi; no Codex model broker is started. See the [operator guide](codex-sandbox/README.md); before changing security boundaries, read the [proxy design](codex-sandbox/spec/proxy-design.typ).
- [`jj-proxy`](jj-proxy/) exposes restricted Jujutsu operations to untrusted containers without writable repository metadata. Start with the [operator guide](jj-proxy/README.md); the [design](jj-proxy/design.typ) covers its policy and threat model.
- [`pi-link`](pi-link/) is a local fork of alvivar's live-session messaging extension, with message IDs and optional reply references in the transcript.
  Pi settings load the fork and its skill on startup; new sessions connect automatically.
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

- [`copy`](../bin/copy) and [`paste`](../bin/paste) use the installed X11, Wayland, or macOS clipboard backend.
  Pass `--primary` for the primary selection, or `--type MIME` before it for xclip and Wayland backends.
  The MIME value stays one literal backend argument, including any spaces or glob characters.
- [`mosh-agent`](mosh-agent/) keeps an autossh agent tunnel open alongside mosh, using a fixed remote socket for existing tmux shells.
- [`backup`](backup/) backs up Documents and consistent Mica state to restic, using systemd timers on Linux and a LaunchDaemon on macOS.
- [`macos-preferences`](macos-preferences/) checks, previews, and applies the semantic macOS preference policy in `lib/macos-preferences.json`. `apply` writes only differing keys and refuses to proceed while an affected application is running.
- [`man-page`](man-page/) implements `open-man-page [SECTION] PAGE`, trying OpenBSD and Ubuntu web manpages before native fallback. Web results require network access and a graphical opener.
- [`open`](open/) implements the basename-sensitive `open`, `hx-hax`, and `editor-hax` commands for desktop dispatch and editor integration, including managed [macOS file associations](open/macos-file-associations.md).
- [`picker-actions`](picker-actions/) implements `picker-action copy|edit|open|search` for explicit or NUL-delimited selections. Actions may write the clipboard, inject tmux keys, launch an editor, or open a URL.
- [`plover-reconnect`](plover-reconnect/) automatically reconnects a configured Plover steno device after USB disconnection and reconnection. See the [operator README](plover-reconnect/README.md).
- [`prompt`](prompt/) implements `prompt-command` and `jj-info`, rendering shell and Claude prompts from host, path, Git, and Jujutsu state. Repository queries are read-only and time-bounded.
- [`shell-cache`](shell-cache/) implements `refresh-fish-cache`, transactionally refreshing generated Fish source when dependencies change while preserving the old cache on producer failure.
- [`shell-data`](shell-data/) validates the shared abbreviation file for shell loaders. Run `python3 tools/shell-data/main.py [FILE]`; it preserves expansions without interpreting shell syntax.
- [`search-bsky-likes`](search-bsky-likes/) finds media posts by `theotherhappyplace.bsky.social` liked by `jyn.dev`, then opens a temporary local gallery. See the [operator README](search-bsky-likes/README.md).
- [`take-a-break`](take-a-break/) displays a modal Zenity reminder and uses `wmctrl`, when available, to keep it above other windows.
- [`watch`](watch/) implements buffered `watch [-n INTERVAL] [-x SHELL] COMMAND...`, running commands in a PTY and replacing the terminal after each complete frame.

## Content and device tools

- [`archive-webpage`](archive-webpage/) implements `archive-webpage DIRECTORY URL [TITLE]`, saving a rendered page and JSON metadata through PhantomJS.
- [`clean-discord`](../bin/clean-discord) converts Discord copy-pasted text to `[HH:MM] <name> message` lines; requires Babashka (`bb`).
  Run `clean-discord chat.txt` or `paste | clean-discord`; output goes to stdout without changing the source.
  Use `clean-discord -i chat.txt` to rewrite the file instead, with no stdout output.

  In-place mode requires a file, preserves permissions, follows symlinks, and atomically replaces the file only after cleaning succeeds.
  Failed cleaning leaves the original unchanged; already-cleaned IRC text is not accepted as Discord input.

  It recognizes timestamp/name/colon headers split across lines, including a missing opening bracket on the first timestamp.
  It removes trailing `[badge],` name decorations, detached copies at message boundaries, and blank lines.
  An opening four-space-indented block separated from the reply by blank lines becomes a `>` quote; other indentation stays unchanged.
  Other UI layouts are not supported; unrecognized text before the first header fails without output.
- [`extract-chat`](extract-chat/) extracts user and assistant turns from local Pi, Codex, or Claude JSON/JSONL sessions. It supports session lookup, `--final-only`, and per-session Markdown.
  `--session ID` selects the newest matching Codex rollout by filename timestamp and rollout UUID, including replacement rollouts created by revert.
  Session lookup prefers Codex sources over imported Pi copies with the same ID, falling back to Pi when no Codex source matches.
  A bare session UUID also implies `--session`, so `extract-chat ID --branches --native` works directly.
  Existing paths take precedence over UUID lookup, and positional UUIDs can be mixed with file or directory inputs.

  Codex exports follow `history_base` references through active and archived rollouts, including inherited fork history only up to the saved byte and ordinal cutoffs.
  References use physical rollout IDs, so later parent edits and reverted turns stay out of the selected history.
  Explicit file paths export that rollout's history; copied histories need their ancestor files alongside them or in the configured Codex home.
  Missing ancestors, reference cycles, and invalid cutoffs fail instead of producing a partial transcript.
  Markdown exports omit standalone injected `<skill>` instruction blocks; skill invocations and discussion remain visible.

  For Pi, `--native` uses `pi --export` to produce HTML (`pi` must be on PATH); other formats remain Markdown. Native Pi exports include the full session regardless of `--final-only`; without `--extract-dir`, Pi writes to the current directory.
  For Codex, `extract-chat --session ID --branches --native` uses `codex-to-pi --branches` and Pi's native exporter to produce a navigable HTML conversation tree.
  This requires Python and Pi on PATH and local paginated Codex history; `--branches` requires `--native`.
  Codex HTML uses the source rollout's basename with `.html` in `--extract-dir` or the current directory; temporary Pi sessions are removed after success or failure.
  Native Codex exports use the converter's user/assistant message selection and ignore `--final-only`.

  Pi Markdown includes saved goal status, objective, and token budget; provider/model switches and assistant or shell cancellations appear in session order, and partial replies remain visible. These events remain with `--final-only`; goal usage counters and continuation prompts are omitted.
  Empty file/directory scans report the searched source paths on stderr and exit 0, without creating or removing export files. Output may expose private conversations.
- [`codex-to-pi`](../bin/codex-to-pi) converts a Codex session ID, JSONL path, or ChatGPT share URL to Pi v3 JSONL.
  Local conversion uses the same read-only [history reader](../libexec/chat-history.clj) as `extract-chat` and requires `bb` on PATH.
  It also omits injected skill instructions while preserving skill invocations and discussion.
  Use `codex-to-pi SESSION -o FILE` to choose the destination; otherwise it writes to Pi's session directory.
  `--archived` searches archived sessions; `--normalize` rewrites macOS paths for sandbox sessions.
  `codex-to-pi SESSION --branches -o FILE` imports related forks and superseded rollouts into one Pi tree; use `/tree` to navigate it.
  Discovery includes active and archived history, ancestors, sibling forks, and descendants, while excluding spawned subagent sessions.
  Branch endpoints carry Codex thread and rollout labels, and the requested rollout is selected when Pi opens the file.
  Shared source records appear once; repeated messages from different records remain distinct.
  Branch import requires local paginated history and all referenced ancestors; legacy sessions and share URLs are rejected.
  Without `--branches`, conversion and Markdown extraction follow only the selected thread.
- [`pi-to-codex`](pi-to-codex/) imports a Pi session file's selected compacted context, text tool calls, and results into a new Codex thread visible in the resume picker.
  It uses unstable history injection plus native display records, leaves the source unchanged, and prints a resume command without making a model request.
- [`extract-chat-share`](extract-chat-share/) converts public ChatGPT or Claude share pages to Markdown. Claude extraction requires Safari automation on macOS; remote formats may change.
- [`lapwing-prototype`](lapwing-prototype/) is a compact, heap-free Lapwing stenography translator prototype for Moonlander/QMK. Start with its [README](lapwing-prototype/README.md), then the [firmware specification](lapwing-prototype/SPEC.md); it is not hardware-verified.
- [`moonlander`](moonlander/) implements `sync-moonlander` and `flash-moonlander` for ZSA Oryx synchronization and QMK compilation or flashing. These can change remote state, a QMK checkout, or hardware; `COMPILE_ONLY=1` avoids flashing. See the [operator guide](moonlander/README.md).
- [`pdf-optimize`](pdf-optimize/) implements `pdf-optimize INPUT [OUTPUT]`, using Ghostscript without image downsampling. It requires `gs`, `file`, and `du` and never overwrites its destination.
