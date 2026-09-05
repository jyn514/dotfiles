# Codex config migration

`move-generated-config PROFILE CONFIG` moves Codex-generated `[projects.*]` and `[tui.model_availability_nux]` tables from a tracked profile into the untracked user config. Top-level settings such as `model` remain tracked.

`bin/codex` runs it before launch and after Codex exits outside the sandbox:

```text
~/.codex/dotfiles.config.toml -> ~/.codex/config.toml
```

The tool preserves all other TOML text and writes the destination before removing source tables. The active profile replaces stale model-availability state; conflicting project tables leave both files unchanged. Publishing the destination first makes interruption recoverable: a retry removes any harmless duplicate. Post-exit migration removes state Codex writes during startup or the session without racing the running process.

Run the tests with:

```sh
python3 tools/codex-config/tests/test_move_generated_config.py
python3 tests/agent-wrappers/codex_wrapper_test.py
```
