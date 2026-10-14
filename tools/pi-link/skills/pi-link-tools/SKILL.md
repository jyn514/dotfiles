---
name: pi-link-tools
description: "How `link_send`, `link_list` and `link_compact` behave between Pi terminals: delivery, status snapshots, callbacks, groups and remote compaction."
---

# Pi-Link Tools

- Each terminal knows only its own conversation; sending a message does not share the rest of yours.
- A message asks another terminal to act with its own tools and access, which may differ from yours.
- Messages that reach another terminal enter its reasoning and can redirect its work.
- The user can see sent and received messages in the transcript.
  Do not repeat or paraphrase them in your ordinary reply merely to report the exchange.
  Reply to peers with `link_send`; tell the user only new conclusions, decisions, or questions that need their attention.

---

## Tools

### `link_list`

- Returns connected terminals with names, Pi session IDs, status (`idle`, `thinking`, `compacting`, `tool:<name>`), cwd, and available context usage.
  Full IDs appear in the text and in `details.sessionIds`, keyed by terminal name.
  Older peers may not report an ID; missing means unknown.
  Match a known parent session ID to this list to find its terminal; do not infer parentage from names or cwd.
- Your own entry is marked `(you)` and cannot be a target of `link_send` or `link_compact`; its status and context are computed when listed, while peer values are their latest published snapshots.
- A missing status means no status has been reported yet, not `idle`.
- A `?` context value means usage is unknown; it can appear after successful compaction until a new measurement is available.
- An `idle` snapshot does not reserve the terminal: it may become busy before your next call.
- `tool:<name>` names one of the running tool calls.
- `thinking` covers every kind of unsettled work, not just an LLM call, including automatic retries and compactions that run after the visible turn ends.
- `compacting` means a compaction holds that terminal's delivery gate: messages to it are held, and the sender is not told. An automatic (threshold or overflow) compaction never shows it: it is not gated, and reads `thinking` like the rest of the run it belongs to.
- Only connected terminals are visible; messages missed while a terminal was disconnected are not replayed.

### `link_send`

- Messages that reach the receiver close together are batched before entering its model.
  A batch arrives as one `[Link: N message(s) received]` block, in arrival order, containing one sender block per message.
  New messages include their full message ID; a reply also includes `Reply to <original-message-id>`.
  Both the model and the transcript panel receive these references.
  Older peers' messages may have no ID.
- A delivered message always enters the receiver's reasoning: if the receiver is idle it starts a turn; if it is running, the batch is steered into that run at Pi's next safe boundary — current tool calls finish first, before the next LLM call. The receiver's state is read when the batch is delivered, not when you send and not when you last ran `link_list`.
- Each call has one recipient; there is no broadcast.
- Successful sends return a new UUID as `messageId` in the tool result text and details.
  To answer any received message, call `link_send({ to: "<sender-name>", message: "...", replyTo: "<full-received-message-id>" })`.
  `to` selects the recipient; `replyTo` only records which message is being answered.
  No pending ask is required, and replies get their own IDs.
- The call returns send status, not the receiver's eventual work result. A target absent from your local, group-filtered list — a typo, an offline terminal or a name in another group — fails immediately; the error lists the names currently visible to you. A successful send means the message was accepted for delivery, not that it arrived. For a client, if the target has vanished, the routing failure is shown to the human as a notification and never reaches the sending model. A terminal's queued messages are invisible to you, and silence alone does not tell you whether your message was received or acted on.

### `link_compact`

- Asks another terminal to compact its context and waits for a result.
- Has a five-minute ceiling that bounds your wait only:
  - Nothing aborts the target.
  - A timed-out call may mean the compaction is still running.
- A target accepts only when Pi reports its session idle and no compaction holds its gate.
- Busy targets decline the request rather than being interrupted; the request is not queued to run later.
- Optional `instructions` guide the summary; they are not a new task and do not guarantee what survives.
- Compaction discards detail. Its summary may omit information, so anything the target learned but has not written down or reported can be lost.

---

## Callbacks

- A callback is an ordinary `link_send` from the other terminal back to you.
  Include `replyTo` to correlate it with the message being answered.
  There is no automatic response, delivery receipt, or protocol timeout; an ID does not prove delivery or completion.
- Your ordinary reply stays in your own conversation; use `link_send` to send a result to the requester or the designated recipient.
  If you need a reply, say who should receive it and ask the peer to include your message ID as `replyTo`.
  With an older peer that has no IDs, use an ordinary unthreaded message instead.
- When confirmation matters, request a read acknowledgment: “Reply when you read this, using this message’s ID as `replyTo`.”
  The reply confirms the peer processed the message, not that it completed the requested action.
  If your next step depends on an action, ask for confirmation of that action instead.
- Continue independent work or end your turn while awaiting a callback.
  Waiting for one requires no live run.
  Keeping a run alive only to wait — by sleeping or polling `link_list` — can postpone delivery to the model until active tool calls end.
- A callback can be sent before its sender's run settles; receiving it does not prove the sender is idle, so a `link_compact` aimed at it can still decline as busy.
- An accepted send does not wait for a reply, so several requests can be sent before any callback arrives, and callbacks may arrive separately or batched into one of your turns. The protocol does not decide when an exchange is complete; it supplies no exit condition for an A → B → C → A chain.

---

## Constraints

- **Localhost only.** All terminals run on the same machine.
- **Cwd is a hint, not proof.** Same cwd does not prove the same workspace, branch, or access. Paths named in a message are only text: they do not change the receiver's cwd, and relative commands resolve from the receiver's own cwd.
- **Names are identities.** The hub suffixes collisions, so the name you remember may not be the name that is connected; `link_list` shows the current one.
- **`@group` in a name limits your world.** The text after the first `@` is the group (case-sensitive): `link_list`, `link_send` and `link_compact` only see and reach terminals of your own group, and names without `@` form one group of their own. These tools cannot change your name or group; `/link-name` is the local command for changing them. Groups scope visibility and targeting, not authentication.
