import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { once } from 'node:events';
import WebSocket from 'ws';

process.env.PORT = '0';
process.env.ADMIN_PORT = '0';
process.env.HOST = '127.0.0.1';
process.env.DB_PATH = ':memory:';

const { server, adminServer } = await import('./server.mjs');
if (!server.listening) await once(server, 'listening');
if (!adminServer.listening) await once(adminServer, 'listening');
const base = `http://127.0.0.1:${server.address().port}`;
const adminBase = `http://127.0.0.1:${adminServer.address().port}`;
let mine;
let theirs;

after(() => Promise.all([
  new Promise(resolve => server.close(resolve)),
  new Promise(resolve => adminServer.close(resolve))
]));

test('mints two distinct capability URLs', async () => {
  const response = await fetch(`${base}/api/rooms`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ seed: 'settle on a design', from: 'Ada', to: 'Grace' })
  });
  assert.equal(response.status, 201);
  const body = await response.json();
  mine = body.links.mine;
  theirs = body.links.theirs;
  assert.notEqual(mine, theirs);
  assert.match(mine, new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/r/`));
  assert.equal('expires_days' in body, false);
});

test('lists capability links only on the loopback admin server', async () => {
  const index = await fetch(`${adminBase}/rooms`);
  const page = await index.text();
  assert.equal(index.status, 200);
  assert.match(page, new RegExp(mine.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(page, new RegExp(theirs.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(page, /settle on a design/);
  assert.equal((await fetch(`${base}/rooms`)).status, 404);
  const home = await fetch(base).then(r => r.text());
  assert.match(home, new RegExp(`${adminBase}/rooms`.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
});

test('serves markdown to agents and HTML to humans', async () => {
  const markdown = await fetch(mine, { headers: { accept: 'text/markdown' } });
  assert.match(await markdown.text(), /keep long-polling/i);
  const html = await fetch(mine, { headers: { accept: 'text/html' } });
  const page = await html.text();
  assert.match(page, /Say something as yourself/);
  assert.match(page, /settle on a design/);
  assert.match(page, /data-side="a"/);
});

test('agents and humans share the transcript', async () => {
  const sent = await fetch(mine + '/messages', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: 'first proposal' })
  }).then(r => r.json());
  await fetch(theirs + '/messages?as=human', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: 'human correction' })
  });
  const transcript = await fetch(theirs + '/messages?since=0').then(r => r.json());
  assert.deepEqual(transcript.messages.map(m => [m.side, m.author, m.text]), [
    ['a', 'agent', 'first proposal'],
    ['b', 'human', 'human correction']
  ]);
  assert.equal(sent.id, transcript.messages[0].id);
});

test('long polling wakes when the other participant speaks', async () => {
  const current = await fetch(mine + '/messages?since=0').then(r => r.json());
  const since = current.messages.at(-1).id;
  const waiting = fetch(mine + `/messages?since=${since}&wait=3`).then(r => r.json());
  await new Promise(resolve => setTimeout(resolve, 50));
  await fetch(theirs + '/messages', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: 'reply' })
  });
  const result = await waiting;
  assert.equal(result.messages[0].text, 'reply');
});

test('browser clients receive live messages over WebSocket', async () => {
  const socket = new WebSocket(mine.replace(/^http/, 'ws'));
  await once(socket, 'open');
  const received = once(socket, 'message');
  await fetch(theirs + '/messages', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: 'live reply' })
  });
  const [data] = await received;
  const event = JSON.parse(data.toString());
  assert.equal(event.type, 'message');
  assert.equal(event.message.text, 'live reply');
  socket.close();
});

test('closing makes both capabilities read-only', async () => {
  assert.equal((await fetch(mine + '/close', { method: 'POST' })).status, 204);
  const response = await fetch(theirs + '/messages', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: 'too late' })
  });
  assert.equal(response.status, 409);
});
