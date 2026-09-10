# Zulip proxy operator guide

## Purpose

The Zulip proxy gives host tools and sandboxed agents bounded, read-only access to channel transcripts and topic lists without exposing `~/.zuliprc`. Use the `zulip` command; `server.py`, `forward.py`, and `local.py` are lifecycle components, not operator interfaces.

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

`site` must be a plain HTTPS URL without embedded credentials, query, or fragment. The account determines which channels and history the proxy can read. When credentials are present at startup, `codex-sandbox` automatically builds and enables the trusted Zulip proxy. Add them before starting the session.

## Common commands

```sh
zulip 123
zulip 123 --topic 'release planning'
zulip 'https://chat.example.com/#narrow/channel/123-name/topic/release.20planning'
zulip 123 --after 2026-03-01 --before 2026-04-01
zulip 123 --list-topics
zulip 123 --format jsonl > transcript.jsonl
```

The default output is Markdown. Dates use `YYYY-MM-DD`; `--after` must precede `--before`. `--list-topics` cannot be combined with topic or date filters.

On the host, the client routes through the active repository proxy when one exists and otherwise performs the same read-only request locally. In a sandbox, it uses only the mounted proxy socket and never falls back locally.

## Safety and recovery

### Operational and security boundaries

- The protocol supports only paginated `GET` requests for messages and topic lists on one configured Zulip server. It cannot send, edit, delete, or react to messages.
- Credentials remain on the host or in the dedicated proxy container; they are not returned to the client or mounted into the agent.
- Socket possession authorizes every supported read allowed by the Zulip account. Exported transcripts, including private-channel content, remain sensitive—protect files, logs, and terminal output accordingly.
- Requests and responses are size-bounded. The server rejects redirects, malformed fields, unsupported operations, and non-HTTPS credential sites; failures do not trigger a more privileged fallback.
- The proxy serializes API access, waits two seconds between requests, and honors HTTP 429 `Retry-After` up to five minutes. A warning about server history limits means older messages were omitted.

### Failure recovery

- `proxy 'zulip' is unavailable`: create/fix `~/.zuliprc`, enforce mode `0600`, stop the current sandbox, and start a new one. Proxy capabilities are fixed at session startup.
- Credential errors: verify the `[api]` keys (`site`, `email`, `key`), HTTPS URL, account access, and file permissions.
- HTTP or timeout errors: retry after checking Zulip availability and account permissions. Rate-limited requests wait automatically.
- A malformed response, oversized response, or stalled pagination exits with status 125. Preserve any prior output only as an incomplete export and retry; do not silently treat it as complete.
- If an active proxy container dies, restart the sandbox. The client intentionally does not bypass failed host coordination.

## Tests

Run unit tests from the repository root:

```sh
python3 -m unittest tools/zulip-proxy/tests/zulip_proxy_test.py
```

The end-to-end test builds the real image and requires Docker, OpenSSL, host-gateway support, and local port availability:

```sh
python3 tools/zulip-proxy/tests/container_integration.py
```

For a provisioned Lima-Docker test VM, use its explicit state:

```sh
python3 tools/zulip-proxy/tests/container_integration.py --docker-state /path/to/test/state
```

This uses the pinned client, VM-shared scratch directory and production volume
initialization. Both modes use dummy credentials and a local HTTPS server, and
remove their test containers and volume. The VM must share this checkout.
The fixture checks message/topic requests and rejects upstream authentication
failure without emitting a transcript or leaking the dummy credential.

## Design and reference

The authoritative [sandbox command proxy design](../codex-sandbox/proxy-design.typ) defines the generic proxy lifecycle, including isolation and host coordination.
See the [tools overview](../README.md).
