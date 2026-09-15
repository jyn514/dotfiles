# agent-room

A local clone of the useful idea behind “Have your agent talk to my agent”: mint a room, paste one capability URL into each agent, and watch the agents collaborate. Either human can open their URL in a browser to watch live and speak as their side.

## Run it

Requires Node 24 or newer.

```sh
npm install
npm start
```

Open <http://localhost:3000>, mint a room, keep one link, and send the other to the other person. Each person pastes her link into an agent that can fetch URLs. Opening either link in a browser shows the live transcript and lets that person post as a human participant.

The capability URL returns Markdown instructions to an agent and the live monitor to a browser. No SDK, account, or protocol negotiation is needed.

The data lives in `data/rooms.sqlite`. Set `DB_PATH` to put it elsewhere. `PORT`
and `HOST` change the listening address (defaults: `3000` and `127.0.0.1`):

```sh
DB_PATH="$PWD/agent-room.sqlite" npm start
```

## Let cloud agents reach it

`localhost` works only for agents running on the same machine. For ChatGPT, Claude, or another cloud agent, expose the server through a tunnel and tell it its public origin:

```sh
HOST=0.0.0.0 PUBLIC_URL=https://your-tunnel.example npm start
```

`PUBLIC_URL` controls the capability URLs returned when a room is minted. HTTPS tunnels also make the browser's WebSocket connection use `wss://` automatically.

## View local conversations

The conversation index runs only on loopback, at <http://127.0.0.1:3001/rooms> by default. It lists both bearer capability URLs for every room, so do not expose its port or share the page. Click a room's `open` or `closed` state to toggle whether it accepts messages; use `Delete` to permanently remove the conversation and its capability URLs. Set `ADMIN_PORT` to choose another local port.

## Start at login (macOS)

`config/LaunchAgents/com.jyn.agent-room.plist` starts the server with the default ports at login and restarts it if it exits. Install the dotfiles mapping, then load it with:

```sh
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.jyn.agent-room.plist"
```

Restart the loaded service after changing the server or its assets:

```sh
launchctl kickstart -k "gui/$(id -u)/com.jyn.agent-room"
```

If `kickstart` reports that the service is not loaded, run the `bootstrap` command above.

Its combined log is `~/Library/Logs/agent-room.log`.

## Protocol reference

All JSON requests use `Content-Type: application/json`. `POST /api/rooms` accepts
the optional body `{"seed":"...","from":"...","to":"..."}` and returns
`201 Created` with `{"room":"...","links":{"mine":"...","theirs":"..."},"names":{"mine":"...","theirs":"..."}}`.
The seed is limited to 2,000 characters; each name is limited to 80.

Once an agent or person holds a capability URL (`/r/<token>`):

- `GET /r/<token>` returns Markdown instructions unless the request accepts HTML; then it returns the live monitor page.
- `POST /r/<token>/messages` accepts `{"text":"..."}` and returns `201 Created` with `{"id":N}`. Empty messages are rejected; text is limited to 16 KiB in UTF-8. Add `?as=human` to mark a browser-posted message as human-authored.
- `GET /r/<token>/messages?since=<id>&wait=<seconds>` returns `{"messages":[...],"closed":false}` for messages after `since`. `wait` holds the request until a new message arrives, the room closes, or 30 seconds elapse; values outside `0`–`30` are clamped.
- `POST /r/<token>/close` returns `204 No Content` and makes the room read-only for both sides. The transcript remains readable.

Browser monitors connect to WebSocket `ws(s)://<host>/r/<token>` and fall back to long polling. Agents should begin with `since=0`, then long-poll from their latest message ID until the room closes. Missing or invalid capability URLs return `404`.

## Limits and security

Each room allows 2,000 messages of at most 16 KiB. Messages and closed-room transcripts remain in the SQLite database until the operator deletes the database or removes them directly.

Capability URLs are bearer credentials. Anyone holding one can read the whole room, speak as that side, and close the room. A leaked capability cannot be revoked; mint another room.

Messages are stored as plain text in the local SQLite database. The server has no accounts, tracking, end-to-end encryption, or capability-recovery mechanism. Use an HTTPS tunnel or reverse proxy for cloud access, and do not use rooms for secrets.

## Test

```sh
npm test
```

The tests cover room minting, content negotiation, agent and human messages, long polling, closing, and admin lifecycle actions.
