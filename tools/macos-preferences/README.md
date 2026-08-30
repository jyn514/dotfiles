# macOS preferences

Preview differences between the repository policy and the current user preferences:

```sh
swift run --package-path tools/macos-preferences macos-preferences plan lib/macos-preferences.json
```

Use `check` for a quiet drift check with exit status 1 when preferences differ. Use
`apply` to write only differing keys; quit the applications named by the command first.
The tool does not manage login items, symbolic hotkeys, absent keys, or whole preference
domains.

Run the real write-path test separately:

```sh
tools/macos-preferences/tests/run-disposable-domain.sh
```

It creates a unique `com.jyn.dotfiles.macos-preferences-test.*` domain, applies the
disposable fixture, verifies the complete exported domain, and deletes it on exit.
