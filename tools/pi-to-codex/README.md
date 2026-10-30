# Import a Pi session into Codex

`pi-to-codex` creates a new Codex thread from a Pi session's selected branch, including text tool calls and its current compacted context.
The thread appears in Codex's resume picker.
Its retained messages and tool results appear in Codex's transcript.
The command prints its ID and a resume command; it does not launch an interactive session or send your conversation to a model.
Its compatibility preflight uses only a synthetic session and a local fake provider; it makes no hosted-provider requests.

```sh
pi-to-codex /path/to/pi-session.jsonl
pi-to-codex 6502432f-b4aa-4460-bab2-2bb899dfd1ed
pi-to-codex /path/to/pi-session.jsonl --cwd "$PWD"
codex resume THREAD_ID
```

Pass a file path or an exact Pi session UUID.
IDs use Pi's installed session discovery across projects, including `PI_CODING_AGENT_DIR` configuration.
Existing paths take precedence; missing or ambiguous IDs fail before creating a Codex thread.
For ambiguous IDs, pass one of the paths printed in the error.

By default, the destination uses the cwd recorded in the Pi session.
Use `--cwd` when that directory is unavailable on this machine or you want to continue elsewhere.
The destination directory must already exist.
The importer reads `$CODEX_HOME/dotfiles.config.toml` (default `~/.codex/dotfiles.config.toml`) and applies it as configuration overrides on both import resumes.
This includes the model, permissions, and approval reviewer; Pi credentials and model settings are not transferred.
Codex's app-server rejects `--profile`, so these overrides take precedence over base and project configuration rather than loading as a native profile layer.
A missing or invalid profile fails before thread creation.
This applies to new imports; existing imported threads retain their saved settings.
Saved Pi system prompts are omitted with a diagnostic; Codex uses its own instructions.
Each invocation creates a distinct thread, including repeated imports of the same file.

## Requirements and compatibility

Install Node, Pi, Codex, Python 3.11 or later, `cp`, and `cmp` on PATH.
The repository's normal bin PATH setup exposes `bin/pi-to-codex`; no extra bootstrap mapping is needed.
The importer loads Pi's installed public SDK, not the repository's older unit-test dependencies.
It searches `~/.local/share/pi/node/node_modules/@earendil-works/pi-coding-agent` and `/opt/agent-pi/src/packages/coding-agent`.
Set `PI_PACKAGE_DIR` to another installed package directory if necessary.
`CODEX_HOME` selects the destination Codex home, as for Codex itself.

Native acceptance tests cover Pi 1.3.0 with Codex 0.162.1 and 0.165.0.
Codex labels the history-injection parameter `[UNSTABLE] FOR CODEX CLOUD - DO NOT USE`.
The visibility update also depends on its internal paginated JSONL rollout format.
These interfaces can change across Codex upgrades; unsupported headers and ordinals fail rather than receive a guessed update.

### Automatic compatibility preflight

Before publishing your conversation, the CLI checks the installed Pi/Codex combination using disposable storage.
It imports one tiny synthetic Pi session, including a tool call and result, through the same importer.
It then verifies the persisted resume index and displayed transcript, and continues that same thread against a localhost fake provider to inspect the retained model context.
No tools are replayed, no unrelated thread is created, and no hosted provider is contacted.
The check uses private HOME, XDG, and Codex directories without your configuration, credentials, MCP servers, or hooks.
Even `codex --version` runs with private homes, because a CLI wrapper may otherwise update configuration.
Your input and destination profile are validated first; a failed or cancelled preflight leaves the destination Codex home unchanged.

A successful check is cached atomically in `$XDG_CACHE_HOME/pi-to-codex/compatibility.json`, or `~/.cache/pi-to-codex/compatibility.json` when XDG_CACHE_HOME is unset.
The receipt is written only after the check's processes, local provider, and temporary storage have been cleaned up.
Cache hits perform cheap installed-build identity lookup and `codex --version`; they start no probe app-server or provider.
Caching skips only the synthetic check, not loading the Pi SDK or starting Codex processes to publish and verify your conversation.
When measuring cache overhead, separate SDK loading and normal import work from the compatibility check itself.
A changed Codex version string, Pi package/SDK version, or Pi recorded build revision triggers another check, as does a missing or corrupt receipt.
Pi's normal installer records the build revision in `~/.local/share/pi/node/.source-revision`; the sandbox supplies its corresponding build marker.
A `PI_PACKAGE_DIR` override without a usable recorded revision still works, but is checked on every invocation instead of reusing a durable receipt.
To force a fresh check, remove just the receipt file, not your Codex history.
Failed checks preserve any older successful receipt and do not publish your conversation.

The exported `importSession(source, { env, childCwd, ...options })` remains a lower-level, preflight-free API for isolated callers.
App-servers inherit the caller's working directory unless `childCwd` explicitly selects another startup directory, as the disposable check does.
This does not change the imported thread's destination cwd.
The CLI checks compatibility between input preparation and destination publication.

## What is preserved

Pi's session loader and `convertToLlm()` determine the selected branch, compaction summary, retained messages, branch summaries, custom context messages, and included shell executions.
The original session stays unchanged; any SDK migration happens in a private temporary copy.

The importer preserves user/assistant text, repeated message occurrences, tool names, JSON arguments, and completed call/result pairs.
Parallel tool results retain their recorded order and call/result pairing.
Call IDs longer than the provider's 64-character limit receive unique shorter IDs in both calls and results.
Shorter call IDs stay unchanged.
Successful text results retain their output; failed results become a JSON output string with `isError: true` and the original text in `content`.
Provider-specific thinking blocks and their signatures are omitted with a diagnostic.
Images, unsupported message/content types, incomplete tool calls, duplicate IDs, and mismatched results cause an error before creating a thread.

This imports the selected model context, not a complete conversation archive.
Other branches and messages removed by compaction stay out of Codex's context.
The importer does not reproduce transient extension prompt hooks, live workers, or provider-specific reasoning state.
It does not replay tools or install Pi tool implementations in Codex.
Native tests verify Codex's UI history API and capture the resumed request through a local mock provider.
Hosted-provider acceptance remains unverified.

## Visibility and recovery

History injection alone creates a persistent thread that Codex hides from its picker.
After the first owned app-server exits, the importer appends one native event containing the first imported user message, which may be a compaction summary.
That event supplies picker metadata.
The importer also appends completed native turns and items for the retained messages and tool calls.
Tools appear as historical dynamic tool calls with their arguments, output, and success status.
These display records do not add model-context messages or run tools.
Turn boundaries follow retained user messages; original turn IDs and timing are not reconstructed.
A second app-server resumes the thread and gives it a name from the first imported user message: whitespace is normalized and the name is limited to 80 Unicode code points.
This explicit metadata update commits the reconstructed picker preview; resuming and closing alone can leave that update deferred.
The name does not change the imported message text.
A third app-server verifies database-only picker visibility and the displayed item identities before reporting success.
Existing Codex sessions and the persistent daemon are left running.

On success, temporary files and owned app-servers are removed before the command reports the thread ID.
On failure before injection, no destination thread is created.
After injection starts, an error or cancellation can leave a partial import.
The error identifies the thread when its ID is known; inspect it with `codex resume THREAD_ID` before retrying.
The importer never retries an ambiguous injection or deletes Codex-owned history automatically.

### Recover an import missing from the picker

An earlier importer can leave a complete rollout that Codex 0.165.0 omits from its resume index.
Do not re-import it merely because the picker is empty: that creates another thread.
Open the ID printed in the failure directly:

```sh
codex resume --no-daemon THREAD_ID
```

Inspect the transcript first.
If it contains the expected imported messages, enter `/rename Recovered Pi session` (or another name), then exit normally.
Renaming the resumed thread commits its reconstructed picker metadata without adding a prompt or making a model request.
Do not rely on a bare resume followed by exit: unchanged settings can leave the update deferred.
The thread should then appear in the picker; if it does not, stop and investigate rather than deleting the state database or editing its rollout.
If the transcript is missing or incomplete, do not treat renaming as a history repair.

## Tests

```sh
dev/test-environment pytest -q -p no:cacheprovider tests/native/test_native_pi_to_codex.py
```

The suite uses the installed Pi SDK and a native Codex executable with private HOME and configuration directories.
Set `DOTFILES_TEST_CODEX_REAL` if PATH contains a transport wrapper instead of the native CLI.
The native test binds a localhost mock provider; it needs local socket permission and makes no paid requests.
When native tmux is installed, a separate test opens Codex in a private terminal and checks that imported text renders.
Conversion tests cover seeded JSON arguments, repeated messages, and parallel-result permutations.
CLI tests cover source preservation, migrations, rejection before publication, partial failures, cancellation, and child-process cleanup.
Preflight regressions cover private single-sample imports, local retained-context capture, warm-path startup avoidance, version/revision invalidation, malformed receipts, failure/cancellation preservation, and unrecorded SDK overrides.
