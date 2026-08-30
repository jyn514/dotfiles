# dotfiles
Configuration and options for various common Unix commands.

See the [`tools/` reference](tools/README.md) for the repository's standalone commands and executable subsystems.

Partly taken (with love) from Charles Daniels' [excellent repository](https://github.com/charlesdaniels/dotfiles).

## Maintenance

Run `dev/update-bootstrap-lock --dry-run` to preview newer plugin revisions,
release assets, and checksums. Run it without `--dry-run` to update
`install/bootstrap.lock.json` and `install/bundles.json`, then review the diff
and run `dev/test`. The updater uses `GITHUB_TOKEN` when it is already set,
but does not require or export one.





























[Games?](https://candybox2.github.io/)
