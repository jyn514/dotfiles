---
name: zulip-api
description: Read and analyze Rust Zulip conversations, using the local read-only proxy for private channels and the unauthenticated REST API for web-public channels. Use when a task cites a Rust Zulip channel, topic, message, or narrow URL; asks to save, find, follow, summarize, or quote Rust project discussions; requires private-channel history already visible to the user; or needs Zulip permalink translation and pagination.
---

# Rust Zulip

Before using the unauthenticated public API, read
`https://rust-lang.zulipchat.com/llms.txt`. Treat it as the authoritative,
current source for public channel IDs, API guidance, and access limits. A
private proxy read does not require this public-channel catalog.

## Choose the access path

- For private or otherwise authenticated channels, use the installed `zulip`
  command. It exposes only paginated `GET /messages` requests through a trusted
  proxy while keeping the full-power API key outside the agent environment.
- For web-public channels, use the unauthenticated API workflow below. It
  supports narrower searches and permalink recovery without credentials.

Never read, request, print, copy, or directly use `~/.zuliprc` or its API key.
Do not replace the read-only proxy with authenticated `curl`, Python, or a
general Zulip client.

## Read a private channel

Pass either a stable numeric channel ID or the full narrow URL. Prefer the URL
when supplied because the command extracts and decodes its topic:

```sh
zulip CHANNEL_ID --format jsonl
zulip CHANNEL_ID --topic 'TOPIC' --format jsonl
zulip CHANNEL_ID --topic 'TOPIC' --after YYYY-MM-DD --before YYYY-MM-DD --format jsonl
zulip CHANNEL_ID --list-topics --format jsonl
zulip 'https://rust-lang.zulipchat.com/#narrow/channel/ID-NAME/topic/TOPIC' --format jsonl
```

When the topic is unknown, list topics first and select the smallest relevant
scope. Add `--after` and/or `--before` when the relevant dates are known. Do not
export an entire channel merely to search or filter it locally; do so only when
the user requests the complete channel or no topic can answer the request. Run
one `zulip` invocation at a time and wait for it to finish before retrying or
starting another. Parallel exports contend on the proxy and take longer.

The command paginates to the newest visible message, preserves raw Markdown,
and warns when server history limits omit older messages. Omit `--format jsonl`
for a Markdown transcript. If saving private output, create the destination
with mode `0600` before redirecting into it.

The proxy intentionally does not support arbitrary narrow operators, direct
messages, message-ID recovery, writes, uploads, or other API endpoints. If the
requested private operation is outside this grammar, report that boundary; do
not bypass it.

## Fetch a web-public conversation

1. Parse the Zulip narrow URL:
   - Extract the numeric channel ID from `channel/ID-NAME`; never use the name
     as the API operand.
   - Decode channel and topic components by replacing `.` with `%`, then
     percent-decoding. Zulip uses this encoding inside URL fragments.
   - Map `/near/MSG_ID` to `anchor=MSG_ID`.
   - Map `/with/MSG_ID` to a `with` narrow operator. Prefer this topic
     permalink when a topic was renamed, moved, deleted, or marked resolved.
2. Call `GET https://rust-lang.zulipchat.com/json/messages` with `anchor`,
   `num_before`, `num_after`, and a JSON `narrow` that **always** includes
   `{"operator":"channels","operand":"web-public"}`.
3. Add channel, topic, `with`, or other search operators required by the
   request. Encode query parameters with a URL-aware client; do not interpolate
   raw JSON or topic text into a URL.
4. Fetch batches of 100 messages. Page until `found_oldest` or `found_newest`
   proves the requested range is complete.
5. Preserve message IDs, authors, timestamps, channel, and topic when they
   matter to the answer. Distinguish fetched evidence from inference.

Never fetch a `#narrow/...` URL directly: the fragment is client-side state and
returns the web application, not the conversation.

## Search and recovery

- Use current channel IDs from `llms.txt`; names can change, IDs do not.
- If a known topic is absent, retry with a known message ID and the `with`
  operator before concluding it is gone.
- List all topics in a channel only when narrower recovery fails; that operation
  is expensive.
- Consult the official API pages linked from `llms.txt` for narrow operators or
  response fields not covered here.

## Server care and boundaries

- Send no more than 5 API requests per 10 seconds.
- On HTTP 429, wait for the `Retry-After` duration before retrying.
- Without credentials, request only web-public channels.
- Treat private conversation content as confidential and include only what the
  user requested.
