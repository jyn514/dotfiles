# Pi extension bundle

`index.ts` is loaded by the existing `config/pi-agent/settings.json` settings as
`./pi-extensions/index.ts`, relative to the installed agent directory. Keep the
whole directory available because the entry point imports sibling modules. This
installation needs no separate `ask-user.ts` setting or package install. After
updating the bundle, run `/reload` in Pi. To test a checkout temporarily:

```sh
pi -e ./config/pi-agent/pi-extensions/index.ts
```

Do not load `ask-user.ts` independently alongside the bundle.

The bundle adds the current date and Pi's host OS to the system prompt. On Linux,
the OS name comes from `/etc/os-release`, or `/usr/lib/os-release` when the former
cannot be read. Without a display name, and on other platforms, it uses the OS
and kernel release. This describes the host running Pi, not its guest shell tools;
send a prompt, then use `/system-prompt` to inspect the captured prompt.

The bundle requires a Pi build with the mutable `systemPromptOptions.sections` API.

Prompt additions use named sections: `current_date`, `host_os`,
`instruction_includes`, and `web_search`. Each extension owns its section;
web-search guidance disappears
when the active provider does not support it. Pi patches changed sections on
later turns unless another extension forces a full-prompt replacement.
`guest-tools.ts` remains an explicit exception: it rewrites paths in the rendered
prompt, including Pi's generated docs section, then replaces the full prompt.
Section-only updates do not apply while that guest-routing hook is active.

Web search uses stock request-payload and provider-event hooks, not the fork's
`registerProviderTool()` API. It adds native search to Anthropic Messages,
OpenAI/Azure/Codex Responses, and Google/Vertex requests without replacing local
tool declarations. OpenAI search uses medium context; search options supplied by
an earlier payload handler remain unchanged. Parsed citations are appended to the
same assistant message, without repeating URLs already in its text. Both the
installed SDK's `provider_event` and v0.99's `provider_stream_event` are supported.
The selected model must identify a supported API; virtual selectors that hide the
routed provider's API receive neither search injection nor search guidance.

`task-directed-docs.ts` replaces Pi's blanket complete-file reading rules in the
`docs` section. Read relevant sections and references that define a needed API or
constraint; read whole files only when the task needs whole-file understanding.
Pi still supplies documentation paths and topic routes. The hook runs before guest
routing and leaves missing docs sections or unrecognized policies unchanged. Its
native regression checks Pi's rendered format and rule wording when Pi is updated.

Tool descriptions and parameter schemas retain input and lifecycle contracts.
Prompt guidelines add workflow rules rather than repeat those contracts. Parameter
defaults do not replace observation sequencing or user-authorization requirements.

## Prompt inspection

`/system-prompt` shows the last prepared Pi system prompt, with the selected model
and capture time. Both this viewer and `/context-breakdown` retain a shared snapshot
from `before_provider_request`; Pi's idle getter otherwise loses per-run changes.
The snapshot includes expanded instructions and guest path rewriting. It is not the
final serialized request: context-message and provider-payload rewrites are excluded.

Session start, resume, fork, and `/reload` clear the snapshot. Until the next provider
request, both commands report that no prompt has been captured instead of showing
an untransformed base prompt. Captures are in memory only and never persisted.

`/context-breakdown` estimates the captured prompt alongside the current persisted
conversation and active tool schemas. Its source labels use current base prompt
inputs; extension additions appear in the remainder rather than as separate rows.
These are local estimates, not provider token accounting.

## Subscription usage: `/usage`

`/usage` fetches your ChatGPT account limits, credit balance, and additional limits
such as Luna Reserve. Bars show the percentage **left**, with reset times in the
host's local time zone. Missing limits or balances are not treated as zero.

Use Pi's `/login` with OpenAI Codex first. The command uses Pi's resolved provider
credentials and token refresh; it does not read Codex CLI credentials. It requires
the direct ChatGPT provider, not a custom authentication proxy. This is account-wide
subscription usage, unlike the session token counts in `/session`.

The command fetches only when invoked, makes no model request, and stores nothing
in the session or on disk. It is interactive-only. It uses the same account-usage
endpoint as Codex CLI; this is an undocumented backend API and can change.
On the host, run `./setup dotfiles` from the repository root to link the new module.
Then run `/reload` in Pi, followed by `/usage`.

## Skill validation: `validate_skill`

Call `validate_skill({ "path": "skills/example/SKILL.md" })` to check whether
Pi's own loader accepts a skill file. Paths are relative to the current working
directory or absolute; `~/` paths also work. The result contains `loaded`, `name`
when accepted, and Pi's `diagnostics`. Warnings do not necessarily prevent loading.

This checks only the supplied path, not whether the current session discovers or
uses the skill. It does not reload or change the session.

In a sandbox, validation runs through the attached guest worker's Pi loader.
Absolute paths, `~/` paths, symlinks, and diagnostics use the guest filesystem;
relative paths use the worker's working directory. Outside a sandbox, validation
uses the local Pi loader and session working directory. Guest attachment or
transport failures return tool errors, never host validation results.

Updating guest validation requires a new worker. Close existing sandbox panes
and start a new sandbox to deploy the host extension and worker together;
`/reload` alone cannot replace the worker.

## Compaction

The Luna extension uses [`compaction.md`](compaction.md) to produce one checkpoint
covering history and any split-turn prefix. Generated checkpoints must include
the `## Objective and authority` header; the extension does not evaluate the
meaning of their prose. If Luna fails, omits that header, or is unavailable, the
active model uses the same instructions. If generation fails, session history is
kept.

The extension appends a repository-state snapshot with `jj status`, the working
directory, and a capture timestamp. Its serialized JSON is limited to 8,192
characters. Oversized captures retain the beginning and end of text fields,
mark omissions, and set `truncated: true`; omitted paths are not evidence of a
clean working copy. The complete capture is saved in the compaction entry's
`details.repositoryState`, outside model-visible context.

Failed captures report unknown state. The snapshot can become stale and is not
evidence of task completion. It is excluded from later compaction requests
rather than summarized again.

Instructions are read afresh for each compaction; instruction-only edits need no
reload. After changing extension code, use `/reload` as described above. Follow
the [testing guide](../../../dev/README.md#testing-and-probes) to install locked
dependencies and run the offline compaction tests, including native extension
loading and resumed-context reconstruction. See [compaction replay](../../../dev/README.md#replay-a-compaction)
to compare instruction changes against saved sessions.

## Side conversations: `/side`

Under tmux, `/side` opens another host Pi pane on the same guest worker and
copies the active branch's completed context into a fresh saved session. It does
not stop the source or submit a prompt; pending tool batches and live
extension/child state are not transferred. Panes share files, not later messages.

The worker remains until its last Pi attachment closes; ordinary subagents remain
parent-owned. `/side` takes no arguments and is unavailable to ordinary subagents
or outside an interactive sandbox. Native `/clone`, `/fork`, and `/resume` are
unchanged.

Refused startup removes only its unpublished snapshot. If the host connection
fails after submission, the outcome is unknown: retain the snapshot and do not
retry. Check tmux before invoking `/side` again.

## Asynchronous questions: `ask_user`

The model queues one batch per tool call. `ask_user` returns question IDs
immediately; it does not open the panel or wait for answers. Titles, question text,
and supplied options must be non-empty. Options are optional, and free-text
answers are always available.

```json
{
  "questions": [
    {
      "title": "Output format",
      "question": "Which output format should the export use?",
      "options": ["JSON", "CSV"]
    },
    {
      "title": "Scope",
      "question": "Which directories should be included?"
    }
  ]
}
```

A pending count and **Alt+A** hint appear above the normal editor; the extension
does not modify that editor.

### Cancelling obsolete questions

The model can call `cancel_ask_user({ "question_ids": ["<ID from ask_user>"] })`
when later work makes a question unnecessary. Cancellation removes only those
pending questions and their drafts in the active session. It preserves unrelated
questions and drafts, switches away from a cancelled selection, and closes an
empty panel immediately.

The result reports `cancelled` and `notPending` IDs. Duplicate IDs are processed
once; unknown, already answered, or already cancelled IDs are reported as not
pending. Cancellation persists before changing the panel; a synchronous save
failure leaves the questions and drafts intact. Reload restores the saved queue
without cancelled questions. Cancellation does not recall an answer already
dispatched, supply an answer, or grant permission to do dependent work.

### Panel controls and drafts

- **Alt+A** opens the last-viewed pending question, or the oldest if none was viewed.
- The header shows **Question N of M — title**. **Alt+Left / Alt+Right** cycle
  through pending questions, wrapping at either end.
- **Up / Down**, then **Enter**, choose an option. Choose “Type a free answer…” or
  start typing to enter text; **Tab** switches between options and text.
- **Enter** submits free text. **Shift+Enter / Ctrl+J** insert a newline using
  Pi's default editor bindings.
- **Escape** closes the panel without answering or cancelling questions.

Text and option-selection drafts survive cycling and closing/reopening the panel.
New tool calls append questions without moving the open panel's selection.
Submission removes that question, advances to the next pending question (wrapping),
and closes the panel when none remain.

### Delivery and model guidance

A submission sends the question ID, title, original question, and answer through
`pi.sendUserMessage(..., { deliverAs: "steer" })`. Pi owns the transcript, normal
editor, message queue, and model-turn delivery; the extension owns pending
questions, drafts, and panel selection.

The transcript quotes the original question, then shows the unaltered answer as
normal Markdown. A display-only Markdown transformer hides the ID and
JSON-encoded title header in the TUI; the original steering message retains both
in session storage and model context. Rendering needs no pending state, including
on reload or resize. Historical label-based messages remain unchanged because
their multiline boundaries are ambiguous.

While questions are unanswered, the model may continue **only independent work**.
Silence, closing the panel, and successful queueing are **not an answer or
permission**. Work requiring an answer must wait for the corresponding steering
message.

`sendUserMessage` returns **void**, not a delivery acknowledgement. The panel
removes a question when the call returns without a synchronous exception. A
synchronous exception preserves the question and draft for retry with Enter. Pi
reports asynchronous delivery errors separately; the extension cannot guarantee
model receipt or automatically restore an answer after such an error. Users can
resend the answer as a normal message, including the question ID from the queued
tool result. Panel closure does not prove delivery.

### Persistence and errors

Unresolved questions are persisted as versioned Pi custom-entry snapshots through
`appendEntry`; the latest snapshot on `getBranch()` is authoritative. Reload or
resume restores pending questions from the active branch, and tree navigation and
forks follow that branch's saved state. Snapshots are not LLM messages. Storage
follows Pi's session persistence; an ephemeral session is not a durable disk backup.

Draft text, option selection, and last-viewed selection are **memory-only**. They
survive panel cycling and close/reopen, but not `/reload`, session replacement, or
tree navigation. Session shutdown closes an open panel and invalidates callbacks
so old answers cannot be submitted into a replacement session.

Print, JSON, and RPC modes produce an explicit tool error and queue nothing.
Cancelled calls, invalid inputs, and synchronous queue-persistence errors also
queue nothing. Invalid saved snapshots trigger a notification rather than
restoring malformed questions. If saving after dispatch fails, the answer is not
offered for duplicate submission; a notification warns reload may restore that
question. Asynchronous delivery remains Pi's responsibility.
