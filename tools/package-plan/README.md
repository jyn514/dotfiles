# Package plan operator guide

## Purpose

`dev/package-plan` validates, explains, previews, and applies the cross-platform package policy in [`install/packages.clj`](../../install/packages.clj). It supports Debian, Ubuntu, Fedora, Arch, Alpine, Chimera Linux, and Apple-silicon macOS; Intel macOS is unsupported. The [design](design.typ) records the ownership and bootstrap model.

## Prerequisites and setup

Run commands from the repository root. The launcher needs `uname`, `tar`, a downloader (`curl` or `wget`), and a SHA-256 tool (`sha256sum` or `shasum`). Minimal Debian/Ubuntu images generally need `ca-certificates` and `curl`; arm64 Alpine/Chimera also needs `gcompat`, and Chimera needs `libarchive-progs`.

No manual Babashka or mise installation is required. The launcher downloads checksum-pinned releases from the [bootstrap manifest](../../install/bootstrap.edn) into `${XDG_CACHE_HOME:-$HOME/.cache}/dotfiles/package-plan/`. For development, `PACKAGE_PLAN_BB=/path/to/bb` uses an existing [Babashka](https://babashka.org/) binary. Applying as a non-root user requires `sudo`; Chimera requires `doas` and the vendored sudo shim.

## Common commands

Ripgrep and shfmt come from native packages on Linux and Homebrew on macOS; Windows keeps their mise providers. Run global package setup before relying on these commands in local setup or `mise exec`. On Chimera, applying the plan enables the official `current/user` repository and refreshes its index before installing packages. Dry runs do not edit repositories.

Repository tests use an installed pytest with the required plugins, or `uvx` with the pinned requirements in `install/test.txt`; pytest is no longer a global mise tool. Bacon keeps its existing native/Homebrew routing, without introducing a source build. Markdown-oxide also retains its existing policy because the tested official prebuilt Linux release does not run on Alpine or Chimera. See the [compatibility evidence](evidence/2026-10-03/README.md).

Existing installed copies are not removed automatically. Verify replacement command paths before removing an old mise installation or Homebrew formula.

### Inspect and validate

```sh
dev/package-plan validate
dev/package-plan show
dev/package-plan matrix
dev/package-plan explain nvim
```

- `validate` checks the complete policy without changing packages.
- `show` prints the host-specific operations and skips.
- `matrix` prints every logical package's disposition on every target.
- `explain PACKAGE` shows one logical package's native name, fallback, or skip reason by target.

Planning detects the current OS, architecture, WSL state, and selected installed commands. Consequently, preview on the target host immediately before applying. `show` may populate the local Babashka/mise cache, but does not run package or repository operations.

### Apply safely

```sh
# Preferred preview: prints the exact plan and starts no package processes.
dev/package-plan apply --dry-run

# Apply after an interactive confirmation.
dev/package-plan apply

# Apply non-interactively only after reviewing a fresh dry run.
dev/package-plan apply --yes
```

`apply` may elevate privileges, refresh or upgrade package databases, install packages, download package files, and add repositories or signing keys. Host-specific effects include enabling Ubuntu Universe or the Git PPA; configuring Microsoft PowerShell, VS Code, 1Password, or RPM Fusion; installing codecs with DNF `--allowerasing`; and performing a full Arch `pacman` system upgrade. Operations already completed are not rolled back if a later operation fails.

## Safety and recovery

- Preview on the target host immediately before applying. Use `apply --yes` only after reviewing a fresh dry run.
- `apply` may elevate privileges, refresh or upgrade package databases, install packages, download package files, and add repositories or signing keys. Host-specific effects include enabling Ubuntu Universe or the Git PPA; configuring Microsoft PowerShell, VS Code, 1Password, or RPM Fusion; installing codecs with DNF `--allowerasing`; and performing a full Arch `pacman` system upgrade.
- Operations already completed are not rolled back if a later operation fails.
- Recovery is package-manager-specific: inspect the printed plan, remove unwanted packages or repository files with the native package manager, and restore any replaced packages after DNF `--allowerasing`.
- Re-running the corrected policy can add missing state but does not uninstall packages removed from the policy. Cache downloads can be deleted safely and will be fetched again.

## Tests

With Babashka installed:

```sh
bb -cp tools/package-plan/src tools/package-plan/tests/run.clj
# Equivalent from the tool directory: (cd tools/package-plan && bb test)
```

Container bootstrap tests require [Podman](https://podman.io/docs) and network access:

```sh
python3 tools/package-plan/tests/container.py
```

The migration's Chimera integration slice can also run in a disposable Docker container:

```sh
docker run --rm -v "$PWD:/repo:ro" -w /repo -e XDG_CACHE_HOME=/tmp/cache \
  chimeralinux/chimera:latest sh -eu -c '
    apk add curl ca-certificates libarchive-progs
    dev/package-plan validate
    /tmp/cache/dotfiles/package-plan/babashka/1.13.219/bb \
      -cp tools/package-plan/src tools/package-plan/tests/chimera-native.clj
    rg --version
    shfmt --version'
```

This checks actual repository discovery and package installation, dry-run purity, and repeat application. It exercises the two migrated packages rather than every existing package request.

## Design and reference

For authoritative command behavior, see [`src/package_plan.clj`](src/package_plan.clj), the [`dev/package-plan`](../../dev/package-plan) launcher, and [`install/packages.clj`](../../install/packages.clj). Package execution uses [`mise bootstrap packages`](https://mise.jdx.dev/cli/bootstrap/packages.html) except for Arch's direct `pacman` operation.
See the [tools overview](../README.md).
