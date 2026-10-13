# dotfiles

Shell and desktop configuration, bootstrap scripts, and agent tooling.

Partly taken (with love) from Charles Daniels' [excellent repository](https://github.com/charlesdaniels/dotfiles).

## Setup and configuration

Run `./setup dotfiles` from the repository root to install or refresh configuration
links. Conflicting regular files move to `~/.local/config/`. Other `./setup`
options can install packages or change system configuration; read the relevant
function before running them on a new machine.

Mise's Python is scoped to bootstrap tasks, including `pi-install`; it is not a global shell default.
Shell startup removes stale mise shim directories from PATH, including in non-interactive shells.
Non-interactive shells load the configured tool directories directly without prompt hooks.
Run `mise run bootstrap-python -- <arguments>` from the repository root for bootstrap scripts.
Run `./setup py` to install runtime libraries from `install/python.txt` into system Python's per-user package directory.
This does not overwrite distro-owned packages; user packages can still take precedence over distro packages when imported.
On Windows, install native Python with its `py` launcher before running `setup.ps1`.
After refreshing configuration links, start a new shell to clear an already-active mise Python from PATH.
If `~/.local/bin/python`, `py`, or `pip` still points into a mise installation, remove only those stale links and rerun `./setup install-local`.
Existing mise Python installations are retained for bootstrap use.

See [configuration layout](config/README.md) for grouped sources and adding files,
and [Pi configuration](config/pi-agent/README.md) for agent settings and extensions.

## Tools and skills

- [Tools reference](tools/README.md): standalone commands and executable subsystems.
- [Agent skills](skills/README.md): installation, use, and publishing.

## Testing and probes

Run `dev/test` for the suite. Use `dev/test-environment COMMAND [ARGS...]` for
focused tests and ad-hoc Pi probes, including `--help` checks. The wrapper uses a
private HOME and Pi/XDG state; it is not a filesystem sandbox and cannot prevent
writes to explicit paths outside HOME.

Before running tests, follow the [development guide](dev/README.md#testing-and-probes)
for dependencies and exceptions that require installed configuration or authentication.
See [bootstrap maintenance](dev/README.md#bootstrap-maintenance) to update locked
plugin revisions and release assets.





























[Games?](https://candybox2.github.io/)
