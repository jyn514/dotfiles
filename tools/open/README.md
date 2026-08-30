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

A second dry-run should report `(none)` in every section. The setup owns only the types listed in `lib/mimetypes.json`; it does not reset the complete Launch Services database.

## Verify changes

Run the behavioral tests:

```sh
python3 tools/open/tests/test_open.py
python3 tests/setup/mimetypes_test.py
```

Then inspect representative files with the commands in the troubleshooting section of [macOS file associations](macos-file-associations.md#troubleshooting).
