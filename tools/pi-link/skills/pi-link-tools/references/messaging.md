# Send, reply, or clarify

Read before sending a message, replying to a delivered author, broadcasting, or arranging a callback.
Apply the [common authority and identity rules](../SKILL.md) first.
For manager-delivered worker replies, also read [worker integration](workers.md).

## Send a direct message

Use `link_send({ to: "<terminal-name>", message: "..." })` for a direct message.
A typo, offline name, or target outside your group fails the same local check; self-targeting fails too.
Direct-send success on a client means handed to the hub, not confirmed receiver delivery.
Its UUID is `messageId` in the result.

## Reply to a delivered message

Use `link_send({ to: { authorOf: "<full-received-message-id>" }, message: "..." })` to answer a delivered message's author privately.
It resolves the author by session identity, not a remembered mutable name.
Unknown references fail; an unavailable author is never replaced by a fallback recipient.
Named sends remain connected-only.
With the updated manager bridge, an admitted stable worker author can reopen its completed conversation; failed, interrupted, suspended, and paused workers cannot reopen.
A native worker’s current group and connection intent still apply, independently of its owner’s group.
Root delivery references survive reload and resume from admitted transcript messages, but old peers may lack sufficient attribution.
Queued or cleared steering messages grant no reply permission.
Do not supply `inReplyTo` or `includeSubagents` with `authorOf`; the tool supplies the reference and chooses one author.
`link_send.inReplyTo` remains unchecked correlation only; it does not select the recipient.

## Broadcast a group clarification

Roots broadcast general clarifications to the current group:

  ```typescript
  link_send({ to: { broadcast: true }, message: "<general clarification>", includeSubagents: true });
  ```

The hub selects connected roots once, excluding your root context, and preserves one UUID plus a broadcast marker.
An ungrouped broadcast can interrupt unrelated sessions; agree on a named group first.
Late joiners receive no replay.

**Worker delivery requires the supported manager/child bridge:** it selects active own workers; without it, worker inclusion reports unsupported.
Do not claim workers received a root broadcast or invent an automatic parent-forwarding rule.

## Keep replies private

Keep task-specific answers private through `link_send` with `to: { authorOf: messageId }` to the received message.
A reply to a broadcast reaches its author only, not its audience.
Do not automatically forward or rebroadcast received messages.

## Interpret routing results

Broadcast and `link_send` with `to: { authorOf: messageId }` wait at most five seconds for routing, not a model response.
Inspect `details.outcomes`: `submitted`, `failed`, `skipped`, `unsupported`, and `unknown` can coexist.
`details.messageId` is the new message UUID; `empty` identifies an empty selection.
Submission is transport acceptance, not model reading or completion.
Do not automatically resend unknown copies; partial failure does not undo submitted copies.
Old hubs and peers can be unsupported for these operations.

## Understand incoming delivery and callbacks

Incoming messages are batched in arrival order with full IDs, reply references, and broadcast markers when available.
Delivery steers a running receiver after current tool calls finish, or starts a turn if idle.
Manual compaction can hold the inbox; a routing receipt does not prove model admission.

If a result or confirmation is needed, request it explicitly.
An ordinary reply is not sent to a peer: use a link tool.
Continue independent work or end your turn while awaiting a callback; do not sleep or poll merely to keep a run alive.
A callback does not prove its sender is idle or has completed other work.

