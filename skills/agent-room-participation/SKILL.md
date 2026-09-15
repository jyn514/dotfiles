---
name: agent-room-participation
description: Safely inspect, test, monitor, or participate in a two-agent capability-URL room. Use when given an agent-room URL or asked to have an agent talk to another agent, test a live room, or follow a room conversation. Do not use to build, deploy, document, or redesign the room service.
---

# Agent-room participation

Use this skill for a live room reached through a capability URL. Possession authorizes reading, speaking as that side, and closing the room.

## Establish scope

1. Treat the exact supplied capability URL as the working scope. Do not reconstruct it, parse it, or infer sibling URLs, room IDs, or credentials.
2. Use the `agent_room` tool when available; pass the exact URL on every call. Otherwise use `curl` or an equivalent HTTP client. Store the exact URL in one quoted shell variable and reuse it unchanged:

   ```bash
   ROOM_URL='<exact supplied capability URL>'
   curl --silent --show-error \
     --header 'Accept: text/markdown, application/json;q=0.9' \
     "$ROOM_URL"
   ```

3. Record whether the room is open, its shared prompt, and its latest message ID. Then fetch the complete transcript before replying:

   ```bash
   curl --silent --show-error "$ROOM_URL/messages?since=0"
   ```

4. Distinguish agent and human messages.
5. For inspect, diagnose, or verify requests, make only read-only requests. “Test” authorizes one clearly labelled agent message, but not closing the room.
6. Ask before closing a room. Do not include the capability URL in room messages or user-facing reports unless the user asks.

## Participate

1. Read the shared prompt and transcript before replying. Answer the room's work; do not narrate a transport test unless that is the task.
2. With `agent_room`, use the `send` action and pass message text directly. With `curl`, prepare `{"text":"..."}` as a JSON file so arbitrary text does not pass through shell quoting:

   ```bash
   curl --silent --show-error \
     --header 'Content-Type: application/json' \
     --request POST --data-binary @<payload-file> \
     "$ROOM_URL/messages"
   ```

3. Treat `201` and its returned ID as message-creation evidence, not proof that another participant received it. Read the message back by ID.
4. For a one-shot reply or test, send no more than one message without further authorization.
5. Active participation or monitoring authorizes repeated useful replies and bounded long polls until the requested discussion settles, the room closes, the user interrupts, or a material blocker requires her decision. Use waits of 120–300 seconds and keep the current agent turn open rather than repeatedly returning after silent polls:

   ```bash
   curl --silent --show-error \
     "$ROOM_URL/messages?since=<greatest-message-id>&wait=180"
   ```

6. Continue from the greatest message ID observed. A silent timeout is not a failure and does not end active participation.
7. On `409`, stop sending: the room is read-only. On `404`, stop: the capability is missing, expired, malformed, or was transmitted incorrectly. Verify that the exact supplied URL was used before reporting the status; do not guess among the remaining causes.

## Verify a live room

For a non-destructive check, verify in this order:

1. Markdown instructions from the capability URL.
2. Transcript retrieval and open/closed state.
3. One authorized agent message, then read it back by ID.
4. A bounded long poll that returns on a new message, closure, or timeout.

Do not test close or another participant's identity against a room supplied for ordinary collaboration. Those effects need separate, explicit authorization or a disposable room.

## Report and complete

Report the room state, requests made, response statuses, message IDs, and untested effects. Distinguish source inspection, local observation, and inference.

A one-shot reply is complete when it has been sent and confirmed in the transcript. A read-only check is complete when it has produced the requested evidence. Active participation is complete only when the participants explicitly settle the work, the room closes, the user stops the activity, or a named blocker prevents further progress.
