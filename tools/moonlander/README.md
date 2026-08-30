# Moonlander operator guide

## Purpose

Synchronize the repository-owned [ZSA Oryx](https://www.zsa.io/oryx) layout in `tools/moonlander/moonlander-layout.json`, then build and flash its patched [QMK](https://docs.qmk.fm/) firmware.

## Prerequisites and setup

- Python 3 on Linux or another system with `fcntl` support.
- Network access to Oryx and, for first-time builds, GitHub/QMK dependencies.
- For `--apply`, an `ORYX_TOKEN` for the account that owns the layout. Keep it out of logs and source control.
- For builds, [`qmk`](https://docs.qmk.fm/newbs_getting_started) in `PATH`, or [`uvx`](https://docs.astral.sh/uv/guides/tools/) so the tool can run QMK without a permanent install.
- For flashing, a connected Moonlander that can be put into bootloader mode.

Run commands from the repository root. Set `QMK_HOME` to choose the QMK checkout; it defaults to `~/src/qmk_firmware`.

## Common commands

### Synchronize Oryx

```sh
# Check Oryx against the tracked snapshot; exits 1 and prints a diff on drift.
tools/moonlander/sync-moonlander

# Replace the tracked snapshot with the latest Oryx state.
tools/moonlander/sync-moonlander --pull

# Initialize a missing custom snapshot.
tools/moonlander/sync-moonlander --snapshot /path/layout.json \
  --layout-id ORYX_LAYOUT_ID --pull

# Make Oryx match the tracked snapshot.
ORYX_TOKEN=... tools/moonlander/sync-moonlander --apply
```

`--snapshot PATH` works with every mode. `--layout-id` is only needed for the first pull and must match an existing snapshot thereafter.

Before applying, run the check without `--apply` and review the Oryx-to-repository diff. Applying can change metadata, layers, keys, automouse settings, and combos; it can delete extra remote layers or combos.

### Build or flash

```sh
# Pull Oryx, install/replace the revision keymap, and compile without touching hardware.
COMPILE_ONLY=1 tools/moonlander/flash-moonlander

# Do the same, then invoke qmk flash.
tools/moonlander/flash-moonlander

# Print subprocess commands while diagnosing a failure.
V=1 COMPILE_ONLY=1 tools/moonlander/flash-moonlander
```

On first use, the command creates a ZSA QMK checkout on branch `firmware25`. It caches the Oryx source archive under `~/.local/share/oryx/`, patches it with `tools/moonlander/keymap-additions.c`, and replaces the matching keymap under `$QMK_HOME/keyboards/zsa/moonlander/keymaps/`. The initial pull still changes `tools/moonlander/moonlander-layout.json`.

Flashing replaces the keyboard firmware. Use `COMPILE_ONLY=1` whenever hardware changes are not intended.

## Safety and recovery

- Keep `ORYX_TOKEN` out of logs and source control.
- Before applying, run the check without `--apply` and review the Oryx-to-repository diff. Applying can change metadata, layers, keys, automouse settings, and combos; it can delete extra remote layers or combos.
- Applying a compiled revision forks it to an editable layout, then updates the snapshot with the verified layout ID. A failed new fork is deleted automatically, but edits to an already-editable revision are not rolled back. Recover those through Oryx or correct the snapshot and apply again. Recover an accidental pull with version control.
- A patch or compile failure restores a previous keymap; a successful compile permanently removes that backup.
- Flashing replaces the keyboard firmware. If it fails or the layout is wrong, put the keyboard back in bootloader mode and flash a previously known-good firmware with this command or [ZSA Keymapp](https://www.zsa.io/flash). Use `COMPILE_ONLY=1` whenever hardware changes are not intended.

## Tests

```sh
python3 -m unittest discover -s tools/moonlander/tests -p '*_test.py'
python3 -m json.tool tools/moonlander/moonlander-layout.json >/dev/null
```

## Design and reference

For authoritative behavior, see [`oryx_sync.py`](oryx_sync.py), [`flash_moonlander.py`](flash_moonlander.py), and [`patch_keymap.py`](patch_keymap.py). See the [QMK flashing guide](https://docs.qmk.fm/newbs_flashing) for bootloader and recovery guidance.
See the [tools overview](../README.md).
