# Repository instructions

Before editing code, configuration, or tests, read the relevant
[repository change guidelines](dev/README.md#repository-change-guidelines) for
layout, language conventions, test placement, and bootstrap or PR requirements.
For setup operations, read [Setup and configuration](README.md#setup-and-configuration)
and the relevant setup function before using it on a new machine.

- Use `jj` for change management.
- Run tests and ad-hoc Pi probes through `dev/test-environment`.
  Read [Testing and probes](dev/README.md#testing-and-probes) for dependencies,
  isolation, and exceptions that require real configuration.
- Check that commands generating shell code, configuration, or cache data succeed
  before consuming their output. Do not hide failures in nested command substitutions
  or unchecked pipelines. Source shell code only after successful generation;
  replace persistent caches through a temporary file only after generation succeeds.
  Add success and failure regression tests.
- For Pi UI extensions, verify documented hooks against the installed
  implementation and reuse Pi's authoritative providers, not duplicate discovery.
- Before changing sandbox launcher stdio or process ownership, read
  [Startup terminal ownership](tools/codex-sandbox/development.md#startup-terminal-ownership).
- When repairing VM configuration, update its host-owned setup source too.
- When authentication scopes change, invalidate persisted credentials that lack
  the required scopes.
- Do not commit secrets, private hostnames, or machine-local paths unless already
  intentionally tracked. `global/` files may be copied with elevated privileges.
- When adding dotfiles or packages, review `install.conf.json` or `install/*.txt`
  so bootstrap behavior stays predictable.
