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

The local [pi-link fork](../../tools/pi-link/README.md#install) is an exception: setup links its whole package at `~/.pi/agent/pi-link`.
Settings load that package's extension and skill, and new sessions connect automatically.
Install its locked dependencies before reloading Pi; `/link-disconnect` opts a session out and persists across reload and resume.
The sandbox exposes the package read-only at the same agent-directory path, so guest tools can read its bundled skill.

See the [extension bundle](pi-extensions/README.md) for loading, reloading,
compaction, side conversations, and asynchronous questions. Follow the
[development guide](../../dev/README.md#testing-and-probes) before running tests
or probes.

Ctrl+G requires tmux and opens the prompt in a new pane while Pi keeps the transcript visible.
Pi applies the edited prompt after that pane exits.

## Subagent routing

Exact allowlisted skills may route a subagent through the `luna` template.
Absent, unknown, or mixed skill sets inherit the parent model.
Use the explicit `parent` template to bypass automatic routing or for generic delegation so the child receives its startup instructions.

Use [work-selection](../../skills/work-selection/SKILL.md) for when to scout, the parent's next-action comparison, and the fallback when no compatible template is available.
Use [`goal-scout`](pi-codex-subagents/agents/goal-scout.md) for fresh-context read-only inspection within an authorized task or goal; follow its advertised caller contract.
Include a complete path to a current use example when available so ignored files remain reachable.
Neither reassessment nor scouting activates autonomous execution or changes goal permissions.
The scout inherits the parent's model and thinking level and restricts active tools to `read`, `grep`, `find`, and `ls`.
The scout decides when it has enough evidence for a recommendation or identifies a concrete blocker; there is no fixed lookup limit.
Its 200-word report limit is an instruction, not a runtime limit.
Reload Pi after installing a template so the tool description advertises it.
Adding this template does not replace separately packaged `/goal` coordinator guidance.

## Installation and update routes

Pi has separate installation and update paths. Choose the owner for the component
being changed; a test dependency update does not update the running application.

| Component | Owner | How an update reaches it |
| --- | --- | --- |
| Host Pi executable | [Installer](../../libexec/setup/install_pi.py) | `mise run pi-install` rebuilds and installs the fork from any working directory. See the [sandbox installation guide](../../tools/codex-sandbox/README.md#purpose). |
| Guest tool worker | [Sandbox operator guide](../../tools/codex-sandbox/README.md#purpose) | Fresh sandboxes use the installed host Pi commit; existing workers require the documented restart. |
| Libraries used by dotfiles tests | [Manifest](../../package.json) and [lockfile](../../package-lock.json) | Update the manifest and lockfile, then install locked dependencies through the [testing guide](../../dev/README.md#testing-and-probes). |
| Dotfiles' local extensions | [Extension bundle](pi-extensions/README.md) | Setup links new files; `/reload` loads code changes in Pi. |
| Separately packaged extensions | [Package references](settings.json) | Settings select sources; `pi update --extensions` updates host package checkouts. Reload Pi afterwards. |
| Dashboard application and bridge | [Mise pin](../mise.toml) and [versioned patch](../../libexec/setup/patches/) | Ordinary package setup installs the patched application; `./setup services` reconciles its machine-local configuration. See [Browser and phone access](#browser-and-phone-access). |

For package-update options, use the installed Pi's `pi update --help`.
The sandbox [runtime documentation](../../tools/codex-sandbox/README.md#prerequisites-and-setup)
explains how packaged extensions affect the guest image cache.

## Browser and phone access

Pi Dashboard is a trial browser interface to the original host Pi processes, not a terminal streamed into a web page.
It keeps the desktop TUI and sandbox workers in place.
A paired device with the `operate` tier can also use Dashboard's host editor, terminal, and Git controls.
Those are human-operated host controls, not additional sandboxed model tools.

### Install and configure

Install the ordinary dotfiles prerequisites first, including mise, Node, pnpm, tmux, and the Pi fork.
Run `./setup dotfiles` if the Pi settings links are not installed.
Tailscale must be running and connected before configuring Dashboard.
Use the existing services entrypoint from the repository root:

```sh
./setup services
```

This also performs the existing [user-services setup](../../README.md#user-services), including tmux startup and Obsidian Sync configuration.
Its Dashboard step ensures the patched mise package is installed and reconciles the native daemon configuration without starting it.
Ordinary local package setup installs Dashboard too, but does not activate its bridge or require an online tailnet.
No Dashboard login hook, user service, reverse proxy, or public tunnel is installed.
Automatic login startup remains deferred until after the trial.

Setup binds the primary HTTP listener to this machine's Tailscale IPv4 address and also listens on `127.0.0.1` at the same port.
It requires native device pairing, disables the public tunnel, selects tmux session creation, and keeps the daemon available after its last Pi session closes.
The tailnet range permits pairing requests; it does not bypass device authentication.
Dashboard's Pi connection still uses its native local gateway and discovery, not a connection through the guest container.

The settings package entry `./pi-dashboard` resolves through a machine-local symlink to the mise-installed extension package.
Its public package manifest declares the bridge; `skills: []` excludes the package's separate skill declarations.
The Pi fork must include its canonical-package-path loader fix; older installs pass the lexical symlink path to Jiti and fail to resolve the bridge's runtime dependencies.
Do not point this link at the core package: its bundled extension source lacks the split package's pnpm dependency scope.
Neither setup nor Dashboard registration replaces `~/.pi/agent/settings.json` or its symlink.
Tracked Dashboard policy lives in `config/pi-dashboard.json`.
Setup merges those managed fields into the real runtime configuration under `~/.pi/dashboard/`; it does not symlink that mutable file.
Machine-specific addresses and the launcher path are derived during setup.
Setup preserves paired devices, credentials, unrelated preferences, and other tool overrides.
The downstream patch fixes Dashboard to a web-interface-only profile.
It keeps explicit browser chat, session, question, abort, model, thinking, editor, terminal, and Git controls while disabling Dashboard-owned agent policy, automatic inference, trust decisions, credential delivery, provider and role management, plugins, automation, and OpenSpec hooks.
Stored preferences cannot re-enable automatic session naming or automatic worktree creation.

The mise pin selects the root release, not a fully locked transitive dependency graph.
Setup checks that every patched Dashboard component matches that release and records the resolved component and Pi SDK versions in its installation receipt.
A missing patch, mismatched component, failed hunk, or modified installed file stops setup before bridge activation.
Review the [patch maintenance instructions](../../libexec/setup/patches/README.md) before changing the pin.

### Start, pair, and stop

Start Dashboard explicitly for the first trial:

```sh
pi-dashboard start --no-tunnel
pi-dashboard status
tailscale ip -4
```

Open `http://<the printed Tailscale address>:8000` on the phone with Tailscale connected.
Desktop browsers can use `http://127.0.0.1:8000` with the same device authentication.
If an existing configuration uses a different HTTP port, use that port instead.
Request access in the browser, then inspect and approve the request on the host:

```sh
pi-dashboard pair list
pi-dashboard pair approve <pending-id> --name phone --tier operate
```

The approval command prompts for the code displayed on the phone.
Do not pass the code in a command-line argument, where process listings can expose it.
The `operate` tier grants the host controls described above; use `control` instead if the device should only control Pi sessions.

Start a normal `pi` session, or `/reload` an existing session to load the newly configured bridge.
Fresh Pi sessions can use Dashboard's native bridge auto-start.
Existing bridges respect an explicit daemon stop; launching a later fresh Pi can start it again unless native `autoStart` is disabled.
These commands operate on Dashboard, not on Pi or its workers:

```sh
pi-dashboard restart --no-tunnel
pi-dashboard stop
```

Daemon output is in `~/.pi/dashboard/server.log`.
Tailscale must remain available while using the bound listener.
Do not use `pi-dashboard --help` as a harmless inspection command: in this release it starts the foreground server.
The metadata command `pi-dashboard --version` is safe.

### Browser-created sessions and questions

Dashboard's supported executor override points to dotfiles' `bin/pi`.
Create, continue, and fork use the normal sandbox launcher in a tmux TUI, not Dashboard's RPC session path.
A missing tmux reports an error rather than silently selecting RPC.
The existing launcher still requires a Git repository and retains project-trust and worker ownership rules.

Dashboard keeps its `pi-dashboard` backing session.
Before the new Pi starts, the wrapper links its window into the most recently active existing tmux session containing a live foreground Pi job.
Pane directories do not affect placement.
The linked window shares the same pane and process; placement does not select a window or change desktop focus.
Without an eligible session, the window stays only in the backing session.

The existing asynchronous `ask_user` queue owns browser and terminal answers.
Dashboard does not register a competing tool or persist a second queue.
Questions stay pending without a timeout or a false indication that the agent is blocked.
Browser options are literal answers, including `Cancel`, and free text is available.
The terminal's Alt+A panel, drafts, cancellation, and steering delivery retain their existing contract.
See [Asynchronous questions](pi-extensions/README.md#asynchronous-questions-ask_user).

### Update and removal

For an update, review and regenerate the versioned patch, change the mise pin and lock together, then run `./setup services`.
Do not use `pi update --extensions` to update this machine-local bridge.
Setup neither restarts Dashboard nor reloads live Pi processes.
Explicitly restart Dashboard afterwards and `/reload` affected Pi sessions so they use the new bridge code.
Reload browser pages to load the updated UI.
A Dashboard restart alone does not replace an already loaded Pi extension.

To remove the integration, first set native `autoStart` to `false` in `~/.pi/dashboard/config.json` and stop Dashboard.
Remove only the `./pi-dashboard` package entry from the tracked Pi settings, then `/reload` affected Pi sessions.
Remove the managed `~/.pi/agent/pi-dashboard` symlink.
If uninstalling the application too, remove its mise declaration and lock entry before uninstalling the tool.
Keep session files, pairing data, unrelated settings, and the rest of `~/.pi/` unless their deletion is intentional.
Running `./setup services` again reconciles the configured policy; restore the package entry first if it was removed.

## Inspect the installed Pi

For provider errors or undocumented hooks, inspect the installed implementation
before changing a dotfiles extension or sandbox proxy. The installer owns
`~/.local/share/pi/source`; `~/.local/share/pi/node/node_modules/@earendil-works/pi-coding-agent`
is a symlink into its `packages/coding-agent` directory.
The installer explicitly disables npm's `install-links` packing behavior so SDK imports use the fork's built workspace dependencies.
It verifies the public SDK import before recording success and before accepting an existing installation as current.
Rerun `mise run pi-install` to repair an older copied installation, even when its revision marker already matches.
Search the source checkout directly: `rg` does not follow that package symlink by default.

```sh
cat ~/.local/share/pi/node/.source-revision
rg --files ~/.local/share/pi/source/packages | rg 'codex|retry|agent-session'
rg -n 'exceeded request buffer limit|isRetryableErrorMessage' ~/.local/share/pi/source/packages
```

The revision marker identifies the successfully installed build. The source
checkout can differ after a failed update; check its revision before attributing
behavior to that build. Do not edit this checkout or installed build outputs:
the installer force-checks out the selected revision. Make Pi changes in a
separate source checkout and land them in the fork before reinstalling.

Model-request retries belong to Pi. Inspect `packages/ai/src/utils/retry.ts` for
the shared error classifier, `packages/ai/src/api/openai-codex-responses.ts` for
Codex transport retries, and `packages/coding-agent/src/core/agent-session.ts`
for session retry policy and context-overflow recovery. The installed classifier
recognizes `exceeded request buffer limit while retrying upstream`; this is an
implementation detail to recheck after updates, not a reason to add proxy retries.
The sandbox proxy forwards application requests without retrying them.

### Request-hook failures

In the installed Pi 1.3.0 build, `before_provider_request` handler errors report an extension error but do not abort the request.
The runner continues with the last payload returned by a successful handler, or the original payload if none succeeded.
Throwing from this hook therefore cannot enforce validation or prevent an uncapped request.
Check `emitBeforeProviderRequest` in `packages/coding-agent/src/core/extensions/runner.ts` after Pi updates.
Tests that invoke a handler directly do not verify this failure behavior; use the real runner when testing request rejection.

## Testing

The native prompt-section regression needs an installed Pi build with `systemPromptOptions.sections` because the locked test SDK predates that API.
The shared-skill discovery regression also uses the installed Pi loader and an isolated copy of the skill tree.
Run them with Node so Bun's module mocks cannot replace the installed SDK:

```sh
dev/test-environment node --test tests/pi/native_prompt_sections.mjs tests/pi/native_work_selection.mjs
```

The discovery check verifies catalog eligibility and description delivery, not model compliance or better next-action selection.

### Dashboard queue regression

The opt-in browser regression needs the patched Dashboard installation, the installed Pi fork SDK,
Python with POSIX PTY support, Playwright, and Chromium.
It uses a disposable home, an offline test provider, and a real native Pi TUI on a PTY; it does not contact a model provider.
Point `DASHBOARD_TEST_CORE` at the installed core package and `DASHBOARD_TEST_INSTALL` at its owning mise installation.
The check runs setup against disposable settings, then loads the selected extension through the persisted `./pi-dashboard` declaration.
Run from the repository root with the actual resolved installation paths:

```sh
env DOTFILES_TEST_DASHBOARD_QUEUE=1 \
  PI_PACKAGE_DIR=/path/to/pi/packages/coding-agent \
  DASHBOARD_TEST_CLI=/path/to/installed/bin/pi-dashboard \
  DASHBOARD_TEST_CORE=/path/to/pi-agent-dashboard \
  DASHBOARD_TEST_INSTALL=/path/to/mise/installs/npm-blackbelt-technology-pi-agent-dashboard/0.11.0 \
  DASHBOARD_TEST_PLAYWRIGHT=/path/to/playwright/index.mjs \
  DASHBOARD_TEST_CHROMIUM=/path/to/chromium \
  DASHBOARD_TEST_ARTIFACT_DIR="$PWD/target/dashboard-queue-integration" \
  dev/pytest tests/native/test_native_dashboard_queue.py -q
```

Without the opt-in variable, the discoverable adapter skips the regression.
The check covers native browser answers, terminal Alt+A, cancellation, reconnect, queue persistence, and exact-once steering.
It does not establish normal sandbox-launcher operation, full-extension compatibility, host terminal spawning, or phone/Tailscale acceptance.

### Subagent templates

For template-only changes, validate configuration delivery without starting an architecture workflow.
Revisit architecture only if the change introduces a runtime-design or ownership decision.
Run probes through `dev/test-environment`, using a private agent directory and a disposable RPC child without live provider calls.
Use the configured subagent package's actual template loader and process launcher, not a separate frontmatter parser.
Check that:

- The loader discovers the template and advertises its caller hint.
- Model and thinking settings inherit from the parent unless the template intentionally overrides them.
- The launched tool allowlist matches the template, excluding mutation and delegation tools for read-only agents.
- The child receives the template instructions and minimal caller input without coordinator restatement.
- Changing the template reaches the child without a matching caller edit.

These checks establish configuration delivery, not model compliance or better task ranking.
See [testing and probes](../../dev/README.md#testing-and-probes) for shared prerequisites and isolation rules.
