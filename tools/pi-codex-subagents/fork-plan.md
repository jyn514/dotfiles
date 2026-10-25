# Bounded native history for spawn_agent

## Contract

Decided: add optional `fork_from: { session_id, through_entry_id }` to `spawn_agent` while keeping `message` required.
The inclusive cut selects a native branch, including messages, tool results and compaction; the required task then uses the existing prompt/RPC path.
Omission keeps fresh spawning unchanged; direct skill routing does not acquire history implicitly.
Current child model, template, skills, resources and dedicated system prompt apply, not historical environment or filesystem state.

User choice, October 25, 2026: forks retain Pi's native source-active tool selection when template tools are omitted.
Explicit plain-name template tools override that selection; modifiers apply through Pi's native rules.
Only tools registered by current child configuration are executable; no default reset, reconstructed policy or activation-code change is needed.
Existing task control, completion, pause and recreation remain authoritative (`core.ts`, `child-helper.ts`, `index.ts`).

Use public `SessionManager` lists plus known parent/managed paths to resolve an exact native header ID, refusing missing or ambiguous sources and missing cuts before child provider work.
Compose `SessionManager.forkFrom(sourcePath, cwd, ownedDirectory)` and `createBranchedSession(through_entry_id)` without a custom transcript parser or migration subsystem.
Keep the full private fork because the final native header references it; place both within existing owned run storage and retention cleanup.
Persist origin on `AgentInfo` and expose actual child identity alongside existing model provenance in the tool result.
Recreation opens the child transcript, never the original again.
Source conversation and active parent stay unchanged; native trailing-newline repair and current-label behavior are accepted.
Older Pi versions that cannot materialize a cut before startup refuse it rather than lose its retained context.

## Implementation

One logical change (no commit requested):
- `core.ts`: resolve and validate source/cut; create owned native sessions before startup; persist origin and child identity; keep cleanup coherent.
- `index.ts`: add the narrow tool schema and forward it only from tool spawns; return origin and child identity.
- `test/fork.test.ts`, native fixtures and source-test driver: exercise producer-to-consumer history, native tool selection and managed lifecycle through actual SDK/RPC execution.
- Package `README.md` and `test/SOURCE-CORE.md`: document usage, compatibility and verification limits.

## Acceptance and validation

Use only synthetic owned sessions and faux provider requests through the source-backed SDK/RPC fixture.
Inspect actual request context and native files, not only launch arguments.
A branched source includes message/tool call/result/compaction, a selected non-head metadata cut and later unrelated branch; labels may follow native behavior.
Verify retained context followed by one required task, current prompt, native source-active selection and explicit plain/modifier template behavior.
Check actual source `setActiveTools()` declarations, current registration of default-active/inactive extension tools and native rejection of an unavailable historical tool.
Verify distinct child identity, native parent links, semantically unchanged source and unaffected active parent.
Verify exact-source lookup from known parent, native lists and managed paths; missing IDs/cuts and ambiguous IDs do not start child provider work.
Verify fresh omission, settled continuation, pause/recreation without re-extraction or repeated effects, suspended retention exemption and expired-fork cleanup preserving source and neighbors.
Run focused fork tests, then `bun run test:subagents` through `/src/dotfiles/dev/test-environment` with actual pi-link and native/guest JJ boundary integrations enabled.
Protect preexisting root `README.md` and `boundary-smoke-extracted.md` changes and unrelated shared skill work.
