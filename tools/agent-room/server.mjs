import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import express from 'express';
import { WebSocketServer, WebSocket } from 'ws';

const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || '127.0.0.1';
const ADMIN_PORT = process.env.ADMIN_PORT === undefined ? PORT + 1 : Number(process.env.ADMIN_PORT);
const DB_PATH = process.env.DB_PATH || 'data/rooms.sqlite';
const PUBLIC_URL = process.env.PUBLIC_URL?.replace(/\/$/, '');
const MAX_MESSAGE_BYTES = 16 * 1024;
const MAX_MESSAGES = 2000;
const STATIC_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), 'public');
const TEMPLATE_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), 'templates');
const SCHEMA = fs.readFileSync(path.join(TEMPLATE_DIR, 'schema.sql'), 'utf8');
const HOME_TEMPLATE = fs.readFileSync(path.join(TEMPLATE_DIR, 'home.html'), 'utf8');
const ROOM_TEMPLATE = fs.readFileSync(path.join(TEMPLATE_DIR, 'room.html'), 'utf8');
const ROOMS_TEMPLATE = fs.readFileSync(path.join(TEMPLATE_DIR, 'rooms.html'), 'utf8');

const db = new DatabaseSync(DB_PATH);
db.exec(SCHEMA);

const app = express();
app.set('trust proxy', true);
app.disable('x-powered-by');
app.use(express.json({ limit: '20kb' }));
const adminApp = express();
adminApp.disable('x-powered-by');

const waiters = new Map();
const sockets = new Map();

function base32(bytes) {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz234567';
  let bits = 0;
  let value = 0;
  let out = '';
  for (const byte of bytes) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      out += alphabet[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  if (bits) out += alphabet[(value << (5 - bits)) & 31];
  return out;
}

function randomToken(length) {
  return base32(crypto.randomBytes(Math.ceil(length * 5 / 8))).slice(0, length);
}

function roomForToken(token) {
  const room = db.prepare('SELECT * FROM rooms WHERE token_a = ? OR token_b = ?').get(token, token);
  if (!room) return null;
  return { ...room, side: room.token_a === token ? 'a' : 'b' };
}

function messageRows(roomId, since = 0) {
  return db.prepare(`
    SELECT id, side, author, text, ts
    FROM messages WHERE room_id = ? AND id > ? ORDER BY id
  `).all(roomId, since).map(m => ({ ...m, ts: new Date(m.ts).toISOString() }));
}

function origin(req) {
  return PUBLIC_URL || `${req.protocol}://${req.get('host')}`;
}

function wake(roomId) {
  const roomWaiters = waiters.get(roomId);
  if (roomWaiters) {
    for (const done of roomWaiters) done();
    waiters.delete(roomId);
  }
}

function broadcast(roomId, payload) {
  const roomSockets = sockets.get(roomId);
  if (!roomSockets) return;
  const encoded = JSON.stringify(payload);
  for (const socket of roomSockets) {
    if (socket.readyState === WebSocket.OPEN) socket.send(encoded);
  }
}

async function fireWebhooks(roomId, speakingSide, latest) {
  const hooks = db.prepare('SELECT side, url FROM webhooks WHERE room_id = ? AND side != ?').all(roomId, speakingSide);
  await Promise.allSettled(hooks.map(hook => fetch(hook.url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ room: roomId, latest }),
    signal: AbortSignal.timeout(5000)
  })));
}

app.post('/api/rooms', (req, res) => {
  const seed = String(req.body?.seed || '').trim();
  const nameA = String(req.body?.from || '').trim();
  const nameB = String(req.body?.to || '').trim();
  if (seed.length > 2000) return res.status(400).json({ error: 'The prompt is too long.' });
  if (nameA.length > 80 || nameB.length > 80) return res.status(400).json({ error: 'A name is too long.' });

  const id = randomToken(8);
  const tokenA = `${id}.${randomToken(24)}`;
  const tokenB = `${id}.${randomToken(24)}`;
  const now = Date.now();
  db.prepare(`INSERT INTO rooms
    (id, token_a, token_b, seed, name_a, name_b, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(id, tokenA, tokenB, seed, nameA, nameB, now, now);

  res.status(201).json({
    room: id,
    links: {
      mine: `${origin(req)}/r/${tokenA}`,
      theirs: `${origin(req)}/r/${tokenB}`
    }
  });
});

app.get('/r/:token', (req, res) => {
  const room = roomForToken(req.params.token);
  if (!room) return res.status(404).type('text').send('Room not found.');
  if (req.accepts('html') && req.get('accept')?.includes('text/html')) {
    return res.type('html').send(roomPage(room, `${origin(req)}/r/${req.params.token}`));
  }
  return res.type('text/markdown').send(agentInstructions(room, `${origin(req)}/r/${req.params.token}`));
});

app.get('/r/:token/messages', (req, res) => {
  const room = roomForToken(req.params.token);
  if (!room) return res.status(404).json({ error: 'Room not found.' });
  const since = Math.max(0, Number.parseInt(req.query.since || '0', 10) || 0);
  const waitSeconds = Math.min(30, Math.max(0, Number.parseInt(req.query.wait || '0', 10) || 0));

  const send = () => {
    if (res.headersSent || res.writableEnded) return;
    res.json({ messages: messageRows(room.id, since), closed: Boolean(room.closed_by) });
  };
  if (messageRows(room.id, since).length || room.closed_by || !waitSeconds) return send();

  const roomWaiters = waiters.get(room.id) || new Set();
  waiters.set(room.id, roomWaiters);
  let timer;
  const done = () => {
    clearTimeout(timer);
    roomWaiters.delete(done);
    if (!roomWaiters.size) waiters.delete(room.id);
    send();
  };
  roomWaiters.add(done);
  timer = setTimeout(done, waitSeconds * 1000);
  req.on('close', () => {
    clearTimeout(timer);
    roomWaiters.delete(done);
    if (!roomWaiters.size) waiters.delete(room.id);
  });
});

app.post('/r/:token/messages', (req, res) => {
  const room = roomForToken(req.params.token);
  if (!room) return res.status(404).json({ error: 'Room not found.' });
  if (room.closed_by) return res.status(409).json({ error: 'This room is closed.' });
  const text = String(req.body?.text || '').trim();
  if (!text) return res.status(400).json({ error: 'Message text is required.' });
  if (Buffer.byteLength(text, 'utf8') > MAX_MESSAGE_BYTES) return res.status(413).json({ error: 'Message exceeds 16KB.' });

  const count = db.prepare('SELECT count(*) AS n FROM messages WHERE room_id = ?').get(room.id).n;
  if (count >= MAX_MESSAGES) {
    db.prepare("UPDATE rooms SET closed_by = 'system' WHERE id = ?").run(room.id);
    wake(room.id);
    broadcast(room.id, { type: 'closed', by: 'system' });
    return res.status(409).json({ error: 'This room reached its message limit.' });
  }

  const author = req.query.as === 'human' ? 'human' : 'agent';
  const now = Date.now();
  const result = db.prepare('INSERT INTO messages (room_id, side, author, text, ts) VALUES (?, ?, ?, ?, ?)')
    .run(room.id, room.side, author, text, now);
  db.prepare('UPDATE rooms SET updated_at = ? WHERE id = ?').run(now, room.id);
  const message = { id: Number(result.lastInsertRowid), side: room.side, author, text, ts: new Date(now).toISOString() };
  wake(room.id);
  broadcast(room.id, { type: 'message', message });
  void fireWebhooks(room.id, room.side, message.id);
  res.status(201).json({ id: message.id });
});

app.post('/r/:token/webhook', (req, res) => {
  const room = roomForToken(req.params.token);
  if (!room) return res.status(404).json({ error: 'Room not found.' });
  let url;
  try { url = new URL(String(req.body?.url || '')); } catch { return res.status(400).json({ error: 'A valid webhook URL is required.' }); }
  if (!['http:', 'https:'].includes(url.protocol)) return res.status(400).json({ error: 'Webhook URL must use HTTP or HTTPS.' });
  db.prepare(`INSERT INTO webhooks (room_id, side, url) VALUES (?, ?, ?)
    ON CONFLICT(room_id, side) DO UPDATE SET url = excluded.url`).run(room.id, room.side, url.href);
  res.status(204).end();
});

app.delete('/r/:token/webhook', (req, res) => {
  const room = roomForToken(req.params.token);
  if (!room) return res.status(404).json({ error: 'Room not found.' });
  db.prepare('DELETE FROM webhooks WHERE room_id = ? AND side = ?').run(room.id, room.side);
  res.status(204).end();
});

app.post('/r/:token/close', (req, res) => {
  const room = roomForToken(req.params.token);
  if (!room) return res.status(404).json({ error: 'Room not found.' });
  db.prepare('UPDATE rooms SET closed_by = ? WHERE id = ? AND closed_by IS NULL').run(room.side, room.id);
  wake(room.id);
  broadcast(room.id, { type: 'closed', by: room.side });
  res.status(204).end();
});

app.use('/assets', express.static(STATIC_DIR));
app.get('/', (_req, res) => res.type('html').send(homePage()));

adminApp.use('/assets', express.static(STATIC_DIR));
adminApp.get('/rooms', (_req, res) => res.type('html').send(roomsPage()));

app.use((err, _req, res, _next) => {
  if (err?.type === 'entity.too.large') return res.status(413).json({ error: 'Request body is too large.' });
  console.error(err);
  res.status(500).json({ error: 'Internal server error.' });
});

const server = http.createServer(app);
const adminServer = http.createServer(adminApp);
const wss = new WebSocketServer({ noServer: true });

server.on('upgrade', (req, socket, head) => {
  const match = new URL(req.url, 'http://localhost').pathname.match(/^\/r\/([^/]+)$/);
  const room = match && roomForToken(decodeURIComponent(match[1]));
  if (!room) return socket.destroy();
  wss.handleUpgrade(req, socket, head, ws => {
    ws.roomId = room.id;
    const roomSockets = sockets.get(room.id) || new Set();
    sockets.set(room.id, roomSockets);
    roomSockets.add(ws);
    ws.on('close', () => {
      roomSockets.delete(ws);
      if (!roomSockets.size) sockets.delete(room.id);
    });
    wss.emit('connection', ws, req);
  });
});

server.listen(PORT, HOST, () => {
  const shownHost = HOST === '0.0.0.0' ? 'localhost' : HOST;
  console.log(`agent-room listening on http://${shownHost}:${server.address().port}`);
});
adminServer.listen(ADMIN_PORT, '127.0.0.1');

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}

function agentInstructions(room, mine) {
  const mineName = room.side === 'a' ? room.name_a : room.name_b;
  const theirName = room.side === 'a' ? room.name_b : room.name_a;
  const last = messageRows(room.id, 0).at(-1)?.id || 0;
  return `# Agent conversation room\n\nYou are ${mineName || 'one participant'} in a cooperative conversation with ${theirName || 'another agent'}.\n\n${room.seed ? `## Shared prompt\n\n${room.seed}\n\n` : ''}## How to participate\n\nThis capability URL is your identity. Do not reveal it.\n\n- Read messages: \`GET ${mine}/messages?since=<id>&wait=30\`\n- Send a message: \`POST ${mine}/messages\` with JSON \`{"text":"..."}\`\n- Close when the conversation is genuinely complete: \`POST ${mine}/close\`\n\nStart by reading from \`since=0\`. Reply when useful, then keep long-polling from the greatest message id you have seen. Cooperate toward a concrete conclusion; disagree plainly, repair each other's ideas, and do not stop merely because you have sent one message. Messages marked \`human\` come from a person watching the room and should be treated as part of the conversation.\n\nCurrent latest message id: ${last}. The room is ${room.closed_by ? 'closed' : 'open'}.\n`;
}

function roomPage(room, mine) {
  const title = [room.name_a, room.name_b].filter(Boolean).join(' & ') || 'agent conversation';
  const messages = messageRows(room.id, 0);
  return ROOM_TEMPLATE
    .replaceAll('{{TITLE}}', escapeHtml(title))
    .replaceAll('{{SIDE}}', room.side)
    .replaceAll('{{MINE}}', escapeHtml(mine))
    .replace('{{SEED}}', room.seed ? `<section class="seed"><span class="eyebrow">The prompt for both agents</span><p>${escapeHtml(room.seed)}</p></section>` : '')
    .replace('{{MESSAGES}}', messages.map(message => messageHtml(message, room.side)).join(''))
    .replace('{{EMPTY_HIDDEN}}', messages.length ? 'hidden' : '')
    .replace('{{CLOSED_HIDDEN}}', room.closed_by ? '' : 'hidden')
    .replace('{{SEND_HIDDEN}}', room.closed_by ? 'hidden' : '');
}

function homePage() {
  return HOME_TEMPLATE.replace('{{ROOMS_URL}}', escapeHtml(`http://127.0.0.1:${adminServer.address().port}/rooms`));
}

function messageHtml(message, side) {
  return `<li class="msg${message.side === side ? ' self' : ''}${message.author === 'human' ? ' human' : ''}" data-id="${message.id}"><div class="meta"><span class="name">${message.side === side ? 'your side' : 'their side'}</span><span class="tag">${escapeHtml(message.author)}</span><span>${escapeHtml(new Date(message.ts).toISOString())}</span></div><p class="body">${escapeHtml(message.text)}</p></li>`;
}

function roomsPage() {
  const rooms = db.prepare('SELECT * FROM rooms ORDER BY created_at DESC').all();
  const rows = rooms.map(room => {
    const title = [room.name_a, room.name_b].filter(Boolean).join(' & ') || 'agent conversation';
    return `<tr><td>${escapeHtml(title)}</td><td>${escapeHtml(descriptionSnippet(room.seed))}</td><td>${escapeHtml(new Date(room.created_at).toISOString())}</td><td>${room.closed_by ? 'closed' : 'open'}</td><td><a href="${escapeHtml(roomLink(room.token_a))}">side A</a><br><a href="${escapeHtml(roomLink(room.token_b))}">side B</a></td></tr>`;
  }).join('');
  return ROOMS_TEMPLATE.replace('{{ROWS}}', rows || '<tr><td colspan="5">No conversations yet.</td></tr>');
}

function descriptionSnippet(seed) {
  const text = seed.replace(/\s+/g, ' ').trim();
  return text.length > 180 ? `${text.slice(0, 177)}…` : text || '—';
}

function roomLink(token) {
  const origin = PUBLIC_URL || `http://${HOST === '0.0.0.0' ? '127.0.0.1' : HOST}:${server.address().port}`;
  return `${origin}/r/${token}`;
}

export { server, adminServer, db };
