# Neovim config tests

Run the Neovim configuration tests from the repository root:

```sh
dev/test-environment python3 tests/nvim/nvim_test.py
```

The suite requires Neovim and an installed plugin tree.
It skips its tests when either is missing.
Follow the [development guide](../../dev/README.md#testing-and-probes) for shared test prerequisites and socket permissions.
