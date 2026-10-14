# Zulip proxy operator guide

## Purpose

The Zulip proxy gives host tools and sandboxed agents bounded, read-only access to channel transcripts and topic lists without exposing `~/.zuliprc`.
Use the `zulip` command;
`server.py` and `forward.py` are lifecycle components, not operator interfaces. The adapter requires the fixed Caddy endpoint and never reads credentials or contacts Zulip directly.

## Prerequisites and setup

Install Python 3 and Jujutsu, put this repository's `bin/` on `PATH`, and create `~/.zuliprc`:

```ini
[api]
site=https://chat.example.com
email=reader@example.com
key=REDACTED
```

```sh
chmod 600 ~/.zuliprc
```

`site` must be a plain HTTPS URL without embedded credentials, query, or fragment.
The account determines which channels and history the proxy can read.
When credentials are present at startup, `codex-sandbox` enables the trusted Zulip proxy by default.
Set `"zulip": false` under `capabilities` in the repository's version 2 `.agents/sandbox/proxy-commands.json` to disable it.
Credential and policy changes take effect after all sandboxes for that checkout exit.

## Common commands

```sh
zulip 123
zulip 123 --topic 'release planning'
zulip 'https://chat.example.com/#narrow/channel/123-name/topic/release.20planning'
zulip 123 --after 2026-03-01 --before 2026-04-01
zulip --list-channels
zulip 123 --list-topics
zulip 123 --format jsonl > transcript.jsonl
```

The default output is Markdown.
Dates use `YYYY-MM-DD`;
`--after` must precede `--before`.
`--list-channels` lists channel IDs and names returned by Zulip's `/streams` API with
`include_can_access_content=true`, limited to channels whose content the account can
access. The API filter was introduced in Zulip 10.0; the helper rejects responses that
report it unsupported. This option cannot be combined with a channel, topic, date, or
`--list-topics` option. `--list-topics` cannot be combined with topic or date filters.

On the host, the client routes through the active repository proxy when one exists and otherwise performs the same read-only request locally.
In a sandbox, it uses only the mounted proxy socket and never falls back locally.

## Safety and recovery

### Operational and security boundaries

- The protocol supports only bounded `GET` requests for available channels, topic lists, and paginated messages on one configured Zulip server.
  It cannot send, edit, delete, or react to messages.
- In sandbox sessions the typed adapter, official pinned Caddy, and Zulip profile helper are separate containers. Only the no-egress helper receives the read-only credential mount; Caddy receives fixed GET routes over the ordinary application network, and credentials are never mounted into the adapter or agent.
- The launcher supplies the adapter's private `ZULIP_CADDY_TOKEN` from the recorded Caddy/helper pair token.
  The adapter validates it before startup and before constructing upstream requests, then sends its bearer Authorization on every fixed GET, page, and retry.
  Missing or malformed private tokens fail before network access; a well-formed but wrong token is rejected by the helper through Caddy.
  This token is distinct from `ZULIP_BROKER_KEY`, which admits typed client requests.
  The private pair token is not written to the client-facing token file or added to public request/response schemas.
  The adapter never receives Zulip API credentials, and errors retain typed responses without direct-provider fallback.
- Socket possession authorizes every supported read allowed by the Zulip account.
  Exported transcripts, including private-channel content, remain sensitive—protect files, logs, and terminal output accordingly.
- Typed requests and complete responses are size-bounded. The adapter rejects malformed fields and unsupported operations; Caddy owns TLS, redirects, HTTP framing, and fixed-origin routing. Failures do not trigger a more privileged fallback.
- The profile helper logs each credential-gate decision with the original method, path, result, and a reason for failures. Its internal request uses a fixed query-free path; the original query is excluded from logs. Helper-route failures also include the helper path, while requests rejected by Caddy before reaching the gate do not appear in these logs.
- The proxy serializes API access, waits two seconds between requests, and honors HTTP 429 `Retry-After` up to five minutes.
  A warning about server history limits means older messages were omitted.

### Failure recovery

- `proxy 'zulip' is unavailable`: check the repository's `capabilities.zulip` switch and `~/.zuliprc` permissions (`0600`), then restart all sandboxes for that checkout.
- Credential errors: verify the `[api]` keys (`site`, `email`, `key`), HTTPS URL, account access, and file permissions.
- HTTP or timeout errors: retry after checking Zulip availability and account permissions.
  Rate-limited requests wait automatically.
- A malformed response, oversized response, or stalled pagination exits with status 125.
  Preserve any prior output only as an incomplete export and retry;
  do not silently treat it as complete.
- If an active proxy container dies, restart the sandbox.
  The client intentionally does not bypass failed host coordination.

## Tests

Run unit and admission checks from the repository root through the isolated test environment:

```sh
dev/test-environment pytest tools/zulip-proxy/tests/zulip_proxy_test.py tools/zulip-proxy/tests/caddy_admission_test.py
```

Normal `dev/test` discovery includes both files.
The local admission check sends actual adapter requests through generated precheck header mutations to the real Unix helper,
using disposable credentials and no external provider access.
This validates the producer/helper boundary, not Caddy's HTTP engine.
The separate native matrix exercises the actual typed adapter, generated pinned Caddy configuration, and actual helper for all three operations.
It checks correct and wrong pair tokens, missing tokens failing before network access, trusted API auth reaching only the application fixture,
and zero application requests on rejection.
It requires already-installed `python:3.12-alpine` and the pinned Caddy manifest for the Docker daemon's platform;
missing images cause an explicit skip, never an image pull.
It creates and removes only disposable containers, volumes, and a network.
This local-image prerequisite does not change the existing native Caddy checks' pull-on-demand policy.
See [Caddy test and logging limits](../codex-sandbox/development.md#tests).

The end-to-end test builds the real image and requires Docker, OpenSSL, host-gateway support, and local port availability:

```sh
python3 tools/zulip-proxy/tests/container_integration.py
```

For a provisioned Lima-Docker test VM, use its explicit state:

```sh
python3 tools/zulip-proxy/tests/container_integration.py --docker-state /path/to/test/state
```

This uses the pinned client, VM-shared scratch directory and production volume initialization.
Both modes use dummy credentials and a local HTTPS server, and remove their test containers and volume.
The VM must share this checkout.
The fixture checks message/topic requests and rejects upstream authentication failure without emitting a transcript or leaking the dummy credential.

## Design and reference

The authoritative [sandbox command proxy design](../codex-sandbox/spec/proxy-design.typ) defines the generic proxy lifecycle, including isolation and host coordination.
See the [tools overview](../README.md).
