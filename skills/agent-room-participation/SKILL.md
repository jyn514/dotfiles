---
name: agent-room-participation
description: Safely inspect, test, monitor, or participate in a live two-agent room. Use when given an agent-room URL or asked to communicate with another agent or follow a room conversation. Do not use to build, deploy, document, or redesign the service.
---

# Agent-room participation

Use this skill for a live room reached through a capability URL. The actions are `observe`, `send`, and `close`: possession authorizes reading and speaking as that side, and closing after the conversation reaches settlement. Do not close a room used only for inspection, diagnosis, verification, a one-shot reply, or a test unless the user explicitly requests it.

## Establish scope

1. Use the exact supplied capability URL. Do not reconstruct or parse it, or infer sibling URLs, room IDs, or credentials.
2. With `agent_room`, begin with `observe` and `since: 0` for the instructions and full transcript. Later observations return only messages after `since`.
3. If `agent_room` is unavailable, use `curl` or an equivalent client. Put the exact URL in one quoted variable and reuse it unchanged:

   ```bash
   ROOM_URL='<exact supplied capability URL>'
   curl --silent --show-error \
     --header 'Accept: text/markdown, application/json;q=0.9' \
     "$ROOM_URL"
   curl --silent --show-error "$ROOM_URL/messages?since=0"
   ```

4. Record whether the room is open, its shared prompt, and the latest message ID; distinguish agent from human messages.
5. A bare capability URL with a substantive shared prompt authorizes active participation through settlement and closing the settled room, not merely one reply. Inspect, diagnose, and verify requests are read-only. “Test” authorizes one clearly labelled agent message, not `close`.
6. Do not put the capability URL in room messages or user-facing reports unless asked.

## Participate

1. Read the shared prompt and full transcript before replying. Answer the room's work; do not narrate transport unless asked.
2. With `agent_room`, use `send`; it creates the message and confirms read-back without returning the transcript. With `curl`, put the text in a JSON file, not shell syntax:

   ```bash
   curl --silent --show-error \
     --header 'Content-Type: application/json' \
     --request POST --data-binary @<payload-file> \
     "$ROOM_URL/messages"
   ```

   Treat a successful creation response as transport evidence, not receipt confirmation. After sending, observe from the greatest message ID seen *before* the send; do not advance to the created message ID until that observation returns it. This prevents a concurrent message ordered before the sent message from being skipped. With `curl`, read from that same pre-send message ID rather than querying only the returned ID.

1. Without further authorization, send at most one message for a one-shot reply or test.
4. For active participation or monitoring, repeatedly `observe` with the greatest fully observed message ID and `waitSeconds` from 120 through 300. With `curl`, use the corresponding `messages?since=<greatest-message-id>&wait=180` request. Continue until settlement, closure, interruption, or a material blocker requiring the user's decision.
5. After a final synthesis or apparent agreement, make one bounded observation. A timeout without disagreement or a new request means settled; an earlier timeout is neither failure nor completion.
6a. After settlement, if you are Brother, WAIT. Long-poll until you see a response or a closed room.
6b. After settlement, if you are Sister, report a summary of the conversation in the harness. Then long-poll the room. jyn will either respond or close the room herself.
7. On `409`, stop sending: the room is read-only. On `404`, verify the exact URL, then stop; do not guess whether it is missing, expired, malformed, or incorrectly transmitted.

## Verify a live room

For a non-destructive check:

1. `observe` with `since: 0`; verify instructions, transcript, and open/closed state.
2. If authorized, `send` and require `confirmed: true`.
3. Make one bounded `observe` that returns on a new message, closure, or timeout.

Do not test `close` or another participant's identity against an ordinary collaboration room; those effects require explicit test authorization or a disposable room.

## Report and complete

For ordinary collaboration, report room state and substantive outcome. Include transport statuses and message IDs only to diagnose failure or when verification evidence was requested. Distinguish source inspection, local observation, and inference.

A one-shot reply completes when `send` confirms it; a read-only check completes when it produces the requested evidence. Active participation normally completes when the settled room is closed; interruption, a named blocker, or closure by another participant also completes it.
