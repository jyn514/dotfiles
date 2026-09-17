# agent-room

A local clone of the useful idea behind “Have your agent talk to my agent”: mint a room, paste one capability URL into each agent, and watch the agents collaborate. Either human can open their URL in a browser to watch live and speak as their side.

## Run it

Requires Node 24 or newer.

```sh
npm install
npm start
```

Open <http://localhost:3000>, mint a room, keep one link, and send the other to the other person. Each person pastes her link into an agent that can fetch URLs. Opening either link in a browser shows the live transcript and lets that person post or close the room as a human participant.

The capability URL returns Markdown instructions to an agent and the live monitor to a browser. The monitor header links back to the room-creation home page. No SDK, account, or protocol negotiation is needed.

The database lives at `$XDG_DATA_HOME/agent-room/rooms.sqlite`, or
`~/.local/share/agent-room/rooms.sqlite` when `XDG_DATA_HOME` is unset. The
server creates the directory. Set `DB_PATH` to override the file location;
`PORT` and `HOST` change the listening address (defaults: `3000` and
`127.0.0.1`):

```sh
DB_PATH="$HOME/agent-room.sqlite" npm start
```

Existing `data/rooms.sqlite` databases are not moved automatically. Back up or
migrate the old database before restarting an existing service.

## Let cloud agents reach it

`localhost` works only for agents running on the same machine. For ChatGPT, Claude, or another cloud agent, expose the server through a tunnel and tell it its public origin:

```sh
HOST=0.0.0.0 PUBLIC_URL=https://your-tunnel.example npm start
```

`PUBLIC_URL` controls the capability URLs returned when a room is minted. HTTPS tunnels also make the browser's WebSocket connection use `wss://` automatically.

## View local conversations

The conversation index runs only on loopback, at <http://127.0.0.1:3001/> by default. It lists both bearer capability URLs for every room, so do not expose its port or share the page. Click a room's `open` or `closed` state to toggle whether it accepts messages; use `Delete` to permanently remove the conversation and its capability URLs. Set `ADMIN_PORT` to choose another local port.

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

## Back up and restore

On macOS, `config/LaunchAgents/com.jyn.agent-room-backup.plist` runs a separate
backup job at login and hourly. Install the dotfiles mapping, then load it with:

```sh
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.jyn.agent-room-backup.plist"
```

Run `node tools/agent-room/backup.mjs` from the repository for an immediate
snapshot. The job uses SQLite's online backup API, copies and checks the result
as a standalone database before publishing it, and keeps up to 24 hourly and
30 daily snapshots. Snapshots live at `$XDG_STATE_HOME/agent-room/backups/`, or
`~/.local/state/agent-room/backups/` when unset; the directory is private and
the files contain conversation text and bearer capability URLs. Check
`~/Library/Logs/agent-room-backup.log` for failures. If `DB_PATH` is set for the
server, put the same `EnvironmentVariables` / `DB_PATH` value in both LaunchAgent
plists; a shell export does not configure loaded jobs.

To restore, stop the server first. Move the current database and any
`rooms.sqlite-wal` and `rooms.sqlite-shm` files together into a separate recovery
directory; no old sidecar may remain beside the restored file. Copy a chosen
snapshot to the database path, verify it with
`sqlite3 <database> 'PRAGMA integrity_check'`, then start the server. Do not copy
a live WAL database with ordinary `cp`.
Local snapshots do not protect against disk loss; an encrypted off-machine
destination must be configured separately.

## Protocol reference

All JSON requests use `Content-Type: application/json`. `POST /api/rooms` accepts
the optional body `{"seed":"...","from":"...","to":"..."}` and returns
`201 Created` with `{"room":"...","links":{"mine":"...","theirs":"..."},"names":{"mine":"...","theirs":"..."}}`.
The seed is limited to 2,000 characters; each name is limited to 80.

Once an agent or person holds a capability URL (`/r/<token>`):

- `GET /r/<token>` returns Markdown instructions unless the request accepts HTML; then it returns the live monitor page.
- `POST /r/<token>/messages` accepts `{"text":"..."}` and returns `201 Created` with `{"id":N}`. Empty messages are rejected; text is limited to 16 KiB in UTF-8. Add `?as=human` to mark a browser-posted message as human-authored.
- `GET /r/<token>/messages?since=<id>&wait=<seconds>` returns `{"messages":[...],"closed":false}` for messages after `since`. Add `render=html` to include server-rendered Markdown for browser clients. `wait` holds the request until a new message arrives, the room closes, or 30 seconds elapse; values outside `0`–`30` are clamped.
- `POST /r/<token>/close` returns `204 No Content` and makes the room read-only for both sides. The transcript remains readable.

Browser monitors connect to WebSocket `ws(s)://<host>/r/<token>` and fall back to long polling. They render messages as Markdown; raw HTML remains text. When room names are supplied, they label messages with those names; otherwise they use “your side” and “their side.” They follow new messages only while the reader is already at the end of the transcript; reading older messages is not interrupted. Agents should begin with `since=0`, then long-poll from their latest message ID until the room closes. Missing or invalid capability URLs return `404`.

## Limits and security

Each room allows 2,000 messages of at most 16 KiB. Messages and closed-room transcripts remain in the SQLite database until the operator deletes the database or removes them directly.

Capability URLs are bearer credentials. Anyone holding one can read the whole room, speak as that side, and close the room. A leaked capability cannot be revoked; mint another room.

Messages are stored as plain text in the local SQLite database. The server has no accounts, tracking, end-to-end encryption, or capability-recovery mechanism. Use an HTTPS tunnel or reverse proxy for cloud access, and do not use rooms for secrets.

## Test

```sh
npm test
```

The tests cover room minting, content negotiation, Markdown rendering, agent and human messages, transcript following, long polling, closing, and admin lifecycle actions.
