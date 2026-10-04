# Pi extension bundle

`index.ts` is loaded by the existing `config/agents/pi/pi.json` settings as
`./pi-extensions/index.ts`, relative to the installed agent directory. Keep the
whole directory available because the entry point imports sibling modules. This
installation needs no separate `ask-user.ts` setting or package install. After
updating the bundle, run `/reload` in Pi. To test a checkout temporarily:

```sh
pi -e ./config/agents/pi/pi-extensions/index.ts
```

Do not load `ask-user.ts` independently alongside the bundle.

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
