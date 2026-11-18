# Development and maintenance

Run commands from the repository root.
For installation and adding dotfiles, see [configuration](../config/README.md).
For subsystem-owned commands and tests, see the [tools reference](../tools/README.md).

## Repository change guidelines

Before editing code, configuration or tests, read the [repository change guidelines](change-guidelines.md).
They cover file layout, language conventions, test placement, validation, review and bootstrap requirements.

## Testing and probes

Before running tests or probes, follow [testing and probes](testing.md) for dependencies, suite selection and isolation rules.
For wrapper internals, persistent caches and executable selection, use the [test-environment reference](test-environment.md).

## Bootstrap maintenance

Run `dev/update-bootstrap-lock --dry-run` to preview newer plugin revisions,
release assets, and checksums. Run it without `--dry-run` to update
`install/bootstrap.lock.json` and `install/bundles.json`, then review the diff
and run `dev/test`. The updater uses `GITHUB_TOKEN` when it is already set,
but does not require or export one.

## Replay a compaction

Use the [compaction replay guide](compaction-replay.md) to compare instruction changes against saved sessions.
It covers offline cut listing, live generation costs, authentication, retained evidence and comparison limits.
