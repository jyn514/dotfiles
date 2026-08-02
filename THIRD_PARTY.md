# Third-party files

Most tools are installed by a platform package manager or by the locked Mise
configuration. A few files are intentionally stored in this repository so the
initial dotfile install does not depend on another package manager. Their
machine-readable provenance and checksums are in `install/vendored.json`.

## Inventory

- `config/bat/mumps.sublime-syntax` is derived from MUMPS.tmbundle at the
  recorded commit, with its file-extension list narrowed to `.m`.
- `lib/dotbot/` is a minimal Dotbot snapshot. `VERSION` records the exact
  upstream commit and the upstream license is stored beside it.
- `bin/git-filter-repo` is the upstream v2.38.0 single-file program. Its
  built-in `--version` output is the upstream Git blob ID, not the release tag.

## Updating an artifact

1. Download or build from an immutable upstream tag or commit.
2. Verify the upstream release signature or checksum when one is available.
3. Replace the file and update its version, SHA-256, source, and license entry
   in `install/vendored.json`. Keep any required license text in the repository.
4. Run `python3 scripts/setup/vendored_artifacts_test.py` and the full
   `scripts/test` suite.

The checksum is an integrity and review aid; it does not establish that an
unknown binary is trustworthy.
