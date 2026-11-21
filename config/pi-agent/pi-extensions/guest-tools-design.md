# Configurable host and guest tool execution

**Status: selected design; implemented in the shared registration helper and existing worker.**

For configuration and updates, see [Host and guest execution](README.md#host-and-guest-execution).

Extend the existing sandbox bridge so portable extension tools can select host or guest execution through settings.
Keep Pi's tool registration, UI and live session management on the host.
Move only the selected tool's executable operation into the guest.

The first consumers are `read_session` and `validate_skill`.
This design does not make arbitrary extensions portable or introduce a new execution service.

## The problem

Pi and its extensions run on the host.
Before this integration, the sandbox forwarded seven built-in tools to an existing guest worker, while `validate_skill` implemented its own forwarding branch.
Other extension tools remained on the host unless their authors added equivalent integration.

For example, `read({path: "/work/frozen-session.jsonl"})` can open a guest file.
But `read_session({sessionFile: "/work/frozen-session.jsonl"})` tries to open that path on the host.
The reader's JSONL parsing does not require host Pi state, but its registration currently binds execution to the host process.

A configuration entry alone cannot move a JavaScript function to another process.
A tool's execution function may close over UI objects, a live session manager or other host resources.
Portable tools therefore need an independently callable implementation, as well as a setting that selects where to invoke it.

## Configuration and defaults

Use an extension-owned key in Pi's existing settings files:

```json
{
  "sandbox": {
    "toolExecution": {
      "read": "guest",
      "bash": "guest",
      "read_session": "guest",
      "spawn_agent": "host"
    }
  }
}
```

Each entry maps a registered tool name to `"host"` or `"guest"`.
The extension reads the effective configuration with `pi.getSettings()` and validates its own fields.
Pi preserves unknown settings, permits additional settings properties and merges nested user and trusted-project settings.
No Pi-core settings change is needed to carry this configuration.

An omitted entry preserves the tool's existing default:

- The seven built-ins forwarded by `guest-tools` use the guest while attached to a sandbox.
- `validate_skill` uses the guest while attached and the host outside a sandbox.
- `read_session` initially retains host execution unless explicitly configured otherwise.
- Existing host-bound tools retain host execution.

Route the seven existing built-in registrations through the shared helper during integration, preserving their guards and renderers.
The first portable extension registrations are `read_session` and `validate_skill`.
Other tools remain host-only unless their authors adapt them.
For an unadapted tool such as `spawn_agent`, a `"host"` entry asserts its existing placement; it does not require moving its registration into the helper.
Validate that assertion against Pi's registered-tool metadata, and reject a `"guest"` request for a host-only tool.
Existing sandbox policy can restrict a built-in to the guest even though Pi also has a local implementation.

Reject invalid target values and targets unsupported by the registered tool or current sandbox policy.
An explicit guest target without an attached guest is an error, not a request to execute on the host instead.
An override for a tool that has not registered yet may remain pending until that tool registers.
Report unresolved names so a misspelled name does not appear to configure a real tool.

`defaultTools`, tool exposure and execution placement remain separate.
Selecting a target neither enables a disabled tool nor changes how the model discovers it.

Configuration changes take effect when Pi reloads settings and the extension applies them.
Snapshot the resolved route when admitting a call; a reload does not move an in-flight call to another process.

## Registration and the worker entry point

A **worker entry point** is an exported function the existing guest worker can import and call.
It is not a second service or a second implementation of the tool.

Introduce a shared registration helper in the sandbox integration.
It associates a normal Pi tool definition with its supported targets, existing default and optional worker entry point.
The helper registers the host-facing tool through `pi.registerTool()` and selects its execution path from settings.
Other extensions can use the helper without duplicating attachment handling.

An illustrative descriptor is:

```ts
guest: {
  module: import.meta.url,
  export: "readSessionWorker",
}
```

This identifies code supplied by the tool author, not a module or export supplied in model arguments.
The module needs a guest-visible counterpart; it is not resolved against the caller's cwd.
The implementation uses `registerRoutedTool(pi, definition, { guest: { module, export }, sandboxDefault })`.
`module` is an absolute file URL, normally `import.meta.url` or a URL resolved against it; the helper maps that file through the existing guest resource paths.

The entry point receives the normal tool arguments and the execution context its implementation needs.
It returns a serializable result through the existing bridge.
Reconstruct cancellation signals and progress callbacks in the receiving process; do not serialize the host Pi context object.

The host and guest should invoke the same operation where possible.
A small adapter may convert an existing exported function's return value into the normal Pi tool result.
The registration still owns the parameter schema, descriptions, exposure and filesystem-independent rendering.

Tools that require live host Pi state remain host-only unless deliberately adapted.
For example, this design does not attempt to move the subagent manager's process ownership or interactive UI into the guest.

## One call, from registration to result

For a guest-routed `read_session` call:

1. Pi validates the normal tool arguments against the existing schema.
2. The registration helper resolves the effective target and checks support and policy.
3. The helper snapshots the route, worker descriptor and call context.
4. The existing attachment sends the call to the existing guest worker.
5. The worker resolves the registered entry point and invokes it against the guest filesystem.
6. The worker returns updates and the terminal result through the existing response frames.
7. Host Pi runs filesystem-independent result handling and displays the normal tool result.

Keep the original tool name throughout dispatch and policy checks.
An entry-point dispatch must not replace it with a generic operation name that bypasses tool-specific guards.

Host execution invokes the corresponding local operation without transport.
Both routes preserve the tool's public arguments, result shape, tool-specific errors and relative-path rules.
Available inputs depend on the selected environment, as described below.

## Context, paths and postprocessing

Placement selects the filesystem in which the operation runs.
It does not automatically expose additional host files, create mounts or copy a missing input into the guest.
A guest reader can only inspect session stores and files already available there.
Host and guest history inventories may therefore differ.

Pass the selected environment's cwd and preserve the existing model and caller-session identity needed by guards or tool semantics.
Resolve the agent directory in the executing environment rather than forwarding the host agent-directory path unchanged.
Do not pass host-only service objects, UI handles or the live session manager into the worker.

Keep each tool's existing relative-path rules.
For example, `validate_skill` resolves its input against the call's cwd, while the session reader documents its own session-root resolution.
Selecting the guest must not silently redefine either rule.

The current bridge translates selected host-bound session-tool arguments and projects session-file metadata into guest-visible paths.
Make that translation depend on the selected route:

- For host execution, preserve the existing guest-to-host argument mapping and host-to-guest metadata projection.
- For guest execution, use guest input paths directly and do not translate them to host paths first.
- Do not rewrite quoted transcript text, opaque cursors or historical evidence as if they were active filesystem paths.

Audit result hooks as well as the execution function.
A host hook that opens a returned guest path would recreate the original problem after successful guest execution.
For example, session-title enrichment must consume metadata supplied by the guest or perform its filesystem read in that environment.
Host-owned rendering is appropriate only where it does not read the selected filesystem.
Preserve the existing guest edit renderer, which deliberately avoids host-side file previews.

## The first two consumers

### `read_session`

The session reader already exports `readSession(opts)`.
Reuse that operation with the adapter needed to preserve its normal result format and metadata.
Do not create another JSONL parser or a reduced guest-only reader.

Keep transcript and edit-candidate views, session lookup, pagination, bounds and error behavior.
Resolve IDs and filenames using the selected environment's available session roots.
A missing guest session is a guest read failure; it must not trigger an implicit search of host history.

The existing search-to-read workflow passes a `search_sessions` result's `sessionFile` unchanged into `read_session`.
With host search and guest reading, this works only when the selected file is guest-accessible through the existing path mapping and mounts.
A host-only search result is not made guest-accessible by changing the reader's target.
Test both cases, and make the missing-file error identify guest execution rather than implying that the host search result was invalid.
Keep pagination cursors opaque; do not promise that a cursor from one environment can continue a read in another.

The decisive example is an explicit guest JSONL path that exists only in the guest.
The normal `read_session` tool must read it through the bridge, without a shell workaround or an additional host copy.

### `validate_skill`

Extract the existing validation operation into one exported function shared by local and guest execution.
It receives the selected cwd and agent directory, calls Pi's skill loader, and returns the existing loaded/name/diagnostics data.
Keep its current output limits and full diagnostic details.

Register its worker entry point through the same helper used by `read_session`.
Remove its manual attachment branch and its special guest-worker dispatch branch once the shared path replaces them.
Preserve its current host-outside-sandbox and guest-inside-sandbox defaults.

This second consumer establishes that the mechanism can replace existing bespoke forwarding, rather than merely adding a new route.

## Transport, authority and failures

Reuse `createGuestAttachment`, the connector and the existing worker process.
Preserve progress updates, cancellation, transport limits, boundary-error metadata and terminal-result validation.
Disconnecting or cancelling an operation does not undo effects already performed.
Do not automatically retry a failed or interrupted call in another environment.

Routing is not permission.
Keep the existing filesystem protections and guarded host-command workflow.
In particular, selecting `"host"` must not turn ordinary sandboxed `bash` into an unreviewed alternative to `host_bash`.
Supported targets must reflect those existing restrictions, not merely whether a local JavaScript implementation exists.

Validate the configured target before dispatch.
Validate worker descriptors supplied by registered tools before import, and reject missing modules or exports clearly.
The model cannot choose executable modules through tool arguments.

For routed tools, expose the selected environment in tool descriptions and inspection, before the caller chooses filesystem paths.
Routing and transport errors identify the tool, resolved target and configuration/default source.
Distinguish unsupported placement, unavailable guest, missing worker support, module-loading failure, execution failure and cancellation.
Never silently fall back to the host when a guest route fails.

Preserve the current request format for existing calls where possible.
A host requesting a portable entry from an older worker must receive an explicit unsupported-operation error without running a different handler.
The request carries a validated `entry` descriptor alongside the original tool name.
An older worker's rejection of that field becomes `WORKER_PROTOCOL_UNSUPPORTED` with update guidance; no negotiation service or alternate-handler retry is added.

## Loading and updates

Keep extension registration, event subscriptions and UI ownership on the host.
Import only the execution module in the guest; importing it must not register a second extension instance or start host integration there.

The host already loads extension code and the worker already loads packaged Pi code.
Reuse those loading arrangements rather than introducing another process supervisor or package manager.
Module placement and dependency resolution must be demonstrated for both initial consumers before expanding support.

Distinguish routing changes from code installation.
Changing a route needs no worker restart when that worker already supports the entry point.
Installing new worker code or dependencies follows the existing worker image/update workflow.
Do not infer the host's loaded extension code from a staged guest-visible copy, or promise that host `/reload` replaces a running guest worker.

## Alternatives

**Add another special case for `read_session`.**
This is smaller for one tool, but repeats the split already present in `validate_skill` and provides no shared routing configuration.
Use the shared helper to remove that recurring integration work.

**Run complete extensions, or a second Pi instance, inside the guest.**
This could support more host-dependent code but also duplicates extension lifecycle, event handling and session/UI ownership.
It is unnecessary for the two filesystem-oriented consumers here.

**Add a general executor API to Pi core now.**
Pi's existing registration API, extensible settings and sandbox transport suffice for this integration.
Keep host/guest knowledge in the sandbox extension; reconsider a core API if another execution integration demonstrates the same need.

## Verification

The normal-discovery adapter `tests/native/test_native_tool_execution.py` owns the assembled routing checks.
The skill, guest-tool, worker, package-loading and session-reader suites retain their existing discovery routes.

The implementation should establish:

- Missing overrides preserve existing defaults and tool activation/exposure.
- User and trusted-project configuration merge as Pi defines, while invalid targets and policy-disallowed routes fail clearly.
- An explicit guest route without a guest never executes locally.
- The same registration can execute a portable operation on the host and through the guest worker.
- `read_session` reads a guest-only frozen JSONL file through its normal interface and preserves its public views and result hooks.
- Relative paths and session identifiers retain their documented resolution semantics in both environments.
- A host search result for a guest-accessible file passes unchanged into the guest reader; a host-only result fails clearly without host fallback.
- `validate_skill` preserves its loader results and output limits without a bespoke transport branch.
- Progress, cancellation, boundary failures, oversized responses and old-worker failures retain the existing transport guarantees.
- Reload affects subsequent calls without changing an in-flight call's target.
- Existing built-in guards, edit rendering and the guarded `host_bash` workflow remain intact.

Use disposable host and guest fixtures for these checks, not live session files or user skill directories.
The relevant existing tests include `native_validate_skill.mjs`, `validate_skill_test.ts`, session-reader/title tests and guest-tool path tests under `tests/pi/`.
The selected design defines these acceptance checks; writing this document does not establish a test result.

## Implementation references

- [Shared registration and transport](../../../libexec/pi-tool-execution.ts), [built-in integration](guest-tools.ts) and [path projection](guest-tools-core.ts).
- [Current skill-validation registration](validate-skill.ts).
- [Guest worker](../../../tools/codex-sandbox/image/tool-worker.mjs).
- [Session reader](../../../tools/pi-session-search/index.ts).
- [Extension bundle and skill-validation behavior](README.md#skill-validation-validate_skill).
- [Guarded host commands](host-bash.md).
- [Sandbox architecture and resources](../../../tools/codex-sandbox/README.md).
