---
name: pi-link-tools
description: "Coordinate Pi sessions with link_set_identity, link_send, link_reply, link_list, and link_compact. Use for link identity or group changes, direct messages, group clarifications, delivered-author replies, callbacks, status, and remote compaction. Covers reply-only worker conventions when manager integration is available; not general subagent creation or task management."
---

# Pi-Link Tools

## Before acting

- Each terminal knows only its own conversation and acts with its own tools and access.
  Sending a message does not share the rest of your context.
- The user sees tool results and incoming panels in the transcript.
  Do not repeat exchanges in your ordinary reply merely to report them.
  Tell the user only new conclusions, decisions, or questions needing their attention.
- Send no acknowledgment unless requested.
  Ask a question only when its answer can change your next action.
- Cwd is a hint, not proof of shared workspace, branch, or access.
  A message's paths do not change the receiver's cwd; relative commands resolve there.

## Choose an identity and group

- Roots may call `link_set_identity({ name?, group? })` with at least one field.
  `name` is a nonempty local name without `@`; `group: ""` selects the ungrouped group.
  Omitted fields retain value and ownership.
- Name and group have separate origins: `generated`, `agent`, or `user`.
  Replacing either user-owned field rejects the whole update; same-value assignments leave user ownership intact.
  Legacy identities with unknown ownership are protected too.
  Do not seek an agent-side override.
- Inspect `preferred`, `assignedName`, `connectionState`, and `pending` in the result.
  The hub can suffix collisions without changing the saved preference; repeating that preference preserves its assigned suffix.
  A pending client rename is not an assigned name; explicit disconnect cancels it but keeps the saved preference.
  Offline changes save without reconnecting.
- Agree on a named group before moving.
  The case-sensitive text after the first `@` defines membership; later `@` characters belong to the group.
  Plain names and names ending in `@` share one empty group, including unrelated projects.
  Group changes can remove your ability to contact collaborators; the tools do not discover other groups.
  Groups limit attention, not authenticated access.

## Send, reply, or clarify

- Use `link_send({ to: "<terminal-name>", message: "..." })` for a direct message.
  A typo, offline name, or target outside your group fails the same local check; self-targeting fails too.
  Direct-send success on a client means handed to the hub, not confirmed receiver delivery.
  Its UUID is `messageId` in the result.
- Use `link_reply({ replyTo: "<full-received-message-id>", message: "..." })` to answer a delivered message's author privately.
  It resolves the author by session identity, not a remembered mutable name.
  Unknown references fail; an author offline or outside the permitted group is not replaced by a fallback recipient.
  Root delivery references survive reload and resume from admitted transcript messages, but old peers may lack sufficient attribution.
  Queued or cleared steering messages grant no reply permission.
  `link_send.replyTo` remains unchecked correlation only; it does not select the recipient.
- Roots broadcast general clarifications to the current group:

  ```typescript
  link_send({ to: { broadcast: true }, message: "<general clarification>", includeSubagents: true });
  ```

  The hub selects connected roots once, excluding your root context, and preserves one UUID plus a broadcast marker.
  An ungrouped broadcast can interrupt unrelated sessions; agree on a named group first.
  Late joiners receive no replay.
  **Worker delivery requires the supported manager/child bridge:** it selects active own workers; without it, worker inclusion reports unsupported.
  Do not claim workers received a root broadcast or invent an automatic parent-forwarding rule.
- Keep task-specific answers private through `link_reply` to the received message.
  A reply to a broadcast reaches its author only, not its audience.
  Do not automatically forward or rebroadcast received messages.
- Broadcast and `link_reply` wait at most five seconds for routing, not a model response.
  Inspect `details.outcomes`: `submitted`, `failed`, `skipped`, `unsupported`, and `unknown` can coexist.
  `details.messageId` is the new message UUID; `empty` identifies an empty selection.
  Submission is transport acceptance, not model reading or completion.
  Do not automatically resend unknown copies; partial failure does not undo submitted copies.
  Old hubs and peers can be unsupported for these operations.
- Incoming messages are batched in arrival order with full IDs, reply references, and broadcast markers when available.
  Delivery steers a running receiver after current tool calls finish, or starts a turn if idle.
  Manual compaction can hold the inbox; a routing receipt does not prove model admission.
- If a result or confirmation is needed, request it explicitly.
  An ordinary reply is not sent to a peer: use a link tool.
  Continue independent work or end your turn while awaiting a callback; do not sleep or poll merely to keep a run alive.
  A callback does not prove its sender is idle or has completed other work.

## Worker conventions with manager integration

These rules apply only when a supported manager/child bridge exposes `link_reply` and delivers attributed messages to workers.
The installed `pi-codex-subagents` manager/child bridge supplies this capability; without it, worker delivery is unsupported.

- Workers have `link_reply` only, addressed to the author of a message actually delivered to that worker.
  Never use arbitrary targeting, broadcast, group discovery, identity changes, or independent link connections.
- Ask the delivered author only for clarification that can change the next action, or send an answer they requested.
  Send normal task completions through the parent channel.
- Several workers may independently ask the same question.
  Do not add semantic deduplication, a suppression registry, or a wait period.
- Private answers go only to the requesting worker, not siblings or the parent's model context.
  Unavailable, finished, or paused workers must not be restarted or resumed to receive them.

## Inspect or compact a root

- `link_list` returns connected terminals in your group, with roles, full Pi session IDs, status, cwd, and available context usage.
  `details.sessionIds` maps names to reported IDs; a missing ID is unknown.
  Match a known parent session ID, not names or cwd, when identifying a parent terminal.
- Your own entry is marked `(you)` and cannot be a direct-send or compaction target.
  Your status is read at listing time; peer values are their latest snapshots, not reservations.
  Missing status is unknown, not idle; `?` context is unknown, including briefly after compaction.
- `tool:<name>` identifies one active tool call.
  `thinking` includes unsettled retries, automatic compaction, and queued continuations.
  `compacting` means manual compaction holds inbox delivery; automatic compaction instead remains `thinking`.
  Join/leave UI notices do not enter model context; use `link_list` only when current membership changes a decision.
- `link_compact({ to: "<terminal-name>", instructions?: "..." })` waits up to five minutes for a compaction result.
  Only a Pi-idle target with no compaction hold accepts; busy targets decline without interruption or queued work.
  Optional instructions guide the summary but do not guarantee what survives.
  Compaction can lose unreported detail.
  Timeout or caller cancellation stops your wait, not a compaction already dispatched to the target.
- The link is localhost-only, with no offline backlog or replay and no authentication.
  See [the operator reference](../../README.md#llm-tools) for tool fields and failure semantics.
