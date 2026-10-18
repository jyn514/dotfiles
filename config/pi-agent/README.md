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

## Subagent routing

Exact allowlisted skills may route a subagent through the `luna` template.
Absent, unknown, or mixed skill sets inherit the parent model.
Use the explicit `parent` template to bypass automatic routing or for generic delegation so the child receives its startup instructions.

## Installation and update routes

Pi has separate installation and update paths. Choose the owner for the component
being changed; a test dependency update does not update the running application.

| Component | Owner | How an update reaches it |
| --- | --- | --- |
| Host Pi executable | [Installer](../../libexec/setup/install_pi.py) | `mise run pi-install` rebuilds and installs the fork. See the [sandbox installation guide](../../tools/codex-sandbox/README.md#purpose). |
| Guest tool worker | [Sandbox operator guide](../../tools/codex-sandbox/README.md#purpose) | Fresh sandboxes use the installed host Pi commit; existing workers require the documented restart. |
| Libraries used by dotfiles tests | [Manifest](../../package.json) and [lockfile](../../package-lock.json) | Update the manifest and lockfile, then install locked dependencies through the [testing guide](../../dev/README.md#testing-and-probes). |
| Dotfiles' local extensions | [Extension bundle](pi-extensions/README.md) | Setup links new files; `/reload` loads code changes in Pi. |
| Separately packaged extensions | [Package references](settings.json) | Settings select sources; `pi update --extensions` updates host package checkouts. Reload Pi afterwards. |

For package-update options, use the installed Pi's `pi update --help`.
The sandbox [runtime documentation](../../tools/codex-sandbox/README.md#prerequisites-and-setup)
explains how packaged extensions affect the guest image cache.

## Inspect the installed Pi

For provider errors or undocumented hooks, inspect the installed implementation
before changing a dotfiles extension or sandbox proxy. The installer owns
`~/.local/share/pi/source`; `~/.local/share/pi/node/node_modules/@earendil-works/pi-coding-agent`
is a symlink into its `packages/coding-agent` directory. Search the source checkout
directly: `rg` does not follow that package symlink by default.

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
Run it with Node so Bun's module mocks cannot replace the installed SDK:

```sh
dev/test-environment node --test tests/pi/native_prompt_sections.mjs
```

See [testing and probes](../../dev/README.md#testing-and-probes) for shared prerequisites and isolation rules.
