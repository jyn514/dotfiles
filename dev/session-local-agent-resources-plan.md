# Session-local agent resources: proposed implementation

Let one cocoa session use an unmerged dotfiles worktree's skills and role templates while retaining normal authentication, settings, and installed packages.
Do not change global links, require another login, or create a profile-management system.
This is a plan only; implementation is not authorized.

## Work

1. Resolve the bootstrap first: use existing package resolution and explicit extension loading to select the candidate subagent manager for this invocation without also loading the installed manager.
   This has not been demonstrated and can change the implementation scope and estimate.
2. Select one worktree for the invocation; derive its skill and template sources from the existing `install.conf.json` mapping rather than add another discovery scheme.
3. In `tools/codex-sandbox/sandbox-host-pi` and `tools/pi-codex-subagents/core.ts`, carry that selection into the root's native skill loading, named-template lookup, and child startup/recreation.
   Keep the normal agent directory and credential identity unchanged; preserve unrelated installed extensions and the default behavior when no source is selected.
4. In `tools/codex-sandbox/codex-sandbox`, reuse existing source mounts and path translation so advertised candidate files are readable through guest tools.
   Change staging only where the selected consumer path requires it.

## Acceptance

Use existing focused test facilities, not a new runner.
In a later authorized cocoa trial, the root must see candidate guidance and a named child must receive the candidate role prompt and skills, with their files readable through guest tools.
A concurrent ordinary session must retain installed sources, and exiting the trial must require no global restoration.
Check invalid source selection fails clearly rather than silently using installed resources.
These checks establish isolated resource selection, not improved agent effectiveness.
