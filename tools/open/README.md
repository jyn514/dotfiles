# Open and editor integration

The `open` tool owns the repository's command-line file dispatch. Its public names are direct symlinks to one basename-sensitive implementation:

| Command | Behavior |
| --- | --- |
| `open TARGET` | Uses editor routing for diagnostics and selected macOS text files; otherwise delegates to the desktop opener. |
| `hx-hax TARGET` | Opens a file in an existing Helix or Neovim tmux pane, or creates one. |
| `editor-hax TARGET` | Executes the configured terminal editor directly. |

On macOS, command dispatch and desktop defaults cooperate but are not the same mechanism. See [macOS file associations](macos-file-associations.md) for the Launch Services model, repository ownership boundaries, and failure modes.

## Restore desktop defaults

Preview the exact managed changes:

```sh
python3 libexec/setup/setup_mimetypes.py --dry-run
```

Apply them:

```sh
./setup mimetypes
```

On macOS, a second dry-run should report `(none)` in every section. The setup owns only the types listed in `lib/mimetypes.json`; it does not reset the complete Launch Services database.

On Linux, setup assigns HTML, XHTML, and SVG to the browser after registering editor defaults. When Glide is installed, it selects Glide for those types and HTTP/HTTPS URLs. Otherwise it uses the current default browser for the file types.

`./setup install-local` installs `glide-browser-bin` on Arch, using pacman when a repository supplies it or an existing paru/yay for the AUR. macOS uses `brew install --cask glide-browser`; other Linux systems retain the locked mise provider. Native Linux Glide disables its mise provider through a managed `~/.config/mise/conf.d/dotfiles-glide.toml`. Setup leaves old installed copies in place.

The native package supplies `glide-browser-bin.desktop`. The mise fallback gets a generated `glide-mise.desktop` that invokes mise directly, so GUI launching does not require shell activation. Run `./setup mimetypes` after local installation to register the selected launcher.

Some AUR releases ship partially quoted executable paths and duplicate desktop-entry keys. MIME setup generates a corrected user override from the package's entry, leaving pacman-owned files intact and refreshing the override on subsequent runs.

When migrating a manual installation, replace stale `userapp-Glide-*.desktop` and `glide.desktop` associations with the selected desktop entry before removing the old launchers. After checking that `/usr/bin/glide-bin --version` works, remove the duplicate with `mise uninstall --all github:glide-browser/glide`.

## Verify changes

Run the behavioral tests:

```sh
python3 tools/open/tests/test_open.py
python3 tests/setup/mimetypes_test.py
```

Then inspect representative files with the commands in the troubleshooting section of [macOS file associations](macos-file-associations.md#troubleshooting).
