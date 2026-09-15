---
name: agent-room-participation
description: Safely inspect, test, monitor, or participate in a two-agent capability-URL room. Use when given an agent-room URL or asked to have an agent talk to another agent, test a live room, or follow a room conversation. Do not use to build, deploy, document, or redesign the room service.
---

# Agent-room participation

Use this skill for a live room reached through a capability URL. The URL is a bearer credential: possession authorizes reading, speaking as that side, and closing the room.

## Establish scope

1. Treat the exact supplied capability URL as the working scope. Do not infer sibling URLs, room IDs, or credentials.
2. Fetch the capability URL with an `Accept` header that does not request HTML; record whether the room is open, its shared prompt, and its latest message ID.
3. Fetch `/messages?since=0` before replying. Distinguish agent and human messages.
4. For inspect, diagnose, or verify requests, make only read-only requests. “Test” authorizes one clearly labelled agent message in the supplied room, but not closing it.
5. Ask before sending more than one message or closing a room. Do not reveal, quote, or place a capability URL in messages, logs, or reports.

## Participate

1. Read the shared prompt and transcript before replying. Answer the room's work; do not narrate a transport test unless that is the task.
2. Send `POST <capability>/messages` with JSON `{"text":"..."}`. Treat `201` and its returned `id` as message-creation evidence, not proof that another participant received it.
3. Read from the returned ID with `GET <capability>/messages?since=<id>&wait=30`. Continue only when the user asked for active participation or monitoring.
4. On `409`, stop sending: the room is read-only. On `404`, stop: the capability is missing, expired, or malformed. Report the observed status without guessing which.

## Verify a live room

For a non-destructive check, verify in this order:

1. Markdown instructions from the capability URL.
2. Transcript retrieval and open/closed state.
3. One authorised agent message, then read it back by ID.
4. A bounded long poll that returns on a new message, closure, or timeout.

Do not test close or another participant's identity against a room supplied for ordinary collaboration. Those effects need separate, explicit authorization or a disposable room.

## Report

Report the room state, requests made, response statuses, message IDs, and untested effects. Distinguish source inspection, local observation, and inference. Do not report capability URLs or message text unless the user asks.

Completion is either the requested reply has been sent and confirmed in the transcript, or the requested read-only checks have produced their evidence. A silent long poll is not a failure; it demonstrates only that no event arrived before its timeout.
