import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { once } from 'node:events';
import WebSocket from 'ws';
import { appendLiveMessage, participantLabel, readerFollowsTranscript } from './public/transcript.js';

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

function relativeLuminance(hex) {
  const channels = hex.slice(1).match(/../g).map(value => Number.parseInt(value, 16) / 255);
  return channels.map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4)
    .reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
}

function contrastRatio(first, second) {
  const [lighter, darker] = [relativeLuminance(first), relativeLuminance(second)].sort((a, b) => b - a);
  return (lighter + .05) / (darker + .05);
}

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
  assert.deepEqual(body.names, { mine: 'Ada', theirs: 'Grace' });
  assert.match(mine, new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/r/`));
  assert.equal('expires_days' in body, false);
});

test('lists capability links only on the loopback admin server', async () => {
  const index = await fetch(`${adminBase}/`);
  const page = await index.text();
  assert.equal(index.status, 200);
  assert.equal(index.headers.get('cache-control'), 'no-cache');
  assert.ok(index.headers.get('etag'));
  assert.match(page, new RegExp(mine.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(page, new RegExp(theirs.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(page, /settle on a design/);
  assert.match(page, /\/[^"/]+\/toggle/);
  assert.match(page, /data-confirm="Delete this conversation permanently\?"/);
  assert.doesNotMatch(page, /T\d{2}:\d{2}:\d{2}\.\d{3}Z/);
  assert.equal((await fetch(`${base}/rooms`)).status, 404);
  const homeResponse = await fetch(base);
  assert.equal(homeResponse.headers.get('cache-control'), 'no-cache');
  assert.ok(homeResponse.headers.get('etag'));
  const home = await homeResponse.text();
  assert.match(home, new RegExp(`${adminBase}/`.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.doesNotMatch(home, /webhook/i);
});

test('serves markdown to agents and HTML to humans', async () => {
  const markdown = await fetch(mine, { headers: { accept: 'text/markdown' } });
  assert.match(await markdown.text(), /keep long-polling/i);
  const html = await fetch(mine, { headers: { accept: 'text/html' } });
  const page = await html.text();
  assert.equal(html.headers.get('cache-control'), 'no-cache');
  assert.ok(html.headers.get('etag'));
  assert.match(page, /Say something as yourself/);
  assert.match(page, /settle on a design/);
  assert.match(page, /data-side="a"/);
  assert.match(page, /data-mine-name="Ada" data-their-name="Grace"/);
  assert.match(page, /<a class="home-link" href="\/">Home<\/a>/);
  assert.match(page, /<button id="close" class="close-room" type="button">Close<\/button>/);
});

test('does not expose webhook registration', async () => {
  const response = await fetch(mine + '/webhook', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'http://127.0.0.1:1/' })
  });
  assert.equal(response.status, 404);
});

test('revalidates static assets with ETags', async () => {
  const asset = await fetch(`${base}/assets/home.js`);
  assert.equal(asset.headers.get('cache-control'), 'no-cache');
  assert.ok(asset.headers.get('etag'));
  const transcript = await fetch(`${base}/assets/transcript.js`);
  assert.equal(transcript.status, 200);
  assert.match(await transcript.text(), /appendLiveMessage/);
});

test('dark primary buttons retain readable contrast', async () => {
  const css = await fetch(`${base}/assets/agent-room.css`).then(response => response.text());
  const darkTheme = css.slice(css.indexOf('@media (prefers-color-scheme: dark)'), css.indexOf('\n\n* {'));
  const ink = darkTheme.match(/--ink: (#[0-9a-f]{6})/i)?.[1];
  const bone = darkTheme.match(/--bone: (#[0-9a-f]{6})/i)?.[1];

  assert.ok(ink);
  assert.ok(bone);
  assert.ok(contrastRatio(ink, bone) >= 4.5);
  assert.match(css, /\.mint \{[\s\S]*background: var\(--ink\)[\s\S]*color: var\(--bone\)/);
  assert.match(css, /\.send button \{[\s\S]*background: var\(--ink\)[\s\S]*color: var\(--bone\)/);
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
  const page = await fetch(mine, { headers: { accept: 'text/html' } }).then(response => response.text());
  assert.match(page, /<span class="name">Ada<\/span>/);
  assert.match(page, /<span class="name">Grace<\/span>/);
  const index = await fetch(`${adminBase}/`).then(r => r.text());
  assert.match(index, /<button[^>]*>open<\/button><\/form><span class="message-count">2 sent<\/span>/);
});

test('renders Markdown safely for browser transcripts', async () => {
  const sent = await fetch(mine + '/messages', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text: '# Heading\n\n**bold** and `code`\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert(1))' })
  }).then(response => response.json());
  const rendered = await fetch(`${mine}/messages?since=${sent.id - 1}&render=html`).then(response => response.json());
  const message = rendered.messages[0];

  assert.match(message.html, /<h1>Heading<\/h1>/);
  assert.match(message.html, /<strong>bold<\/strong>/);
  assert.match(message.html, /<code>code<\/code>/);
  assert.match(message.html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(message.html, /<script|href="javascript:/);

  const page = await fetch(mine, { headers: { accept: 'text/html' } }).then(response => response.text());
  assert.match(page, /<div class="body"><h1>Heading<\/h1>/);
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

test('live messages use participant names when available', () => {
  assert.equal(participantLabel('a', 'a', 'Ada', 'Grace'), 'Ada');
  assert.equal(participantLabel('b', 'a', 'Ada', 'Grace'), 'Grace');
  assert.equal(participantLabel('a', 'a', '', ''), 'your side');
  assert.equal(participantLabel('b', 'a', '', ''), 'their side');
});

test('live messages preserve a reader who has scrolled away from the end', () => {
  let appended = false;
  let scrolled = false;
  const stream = { append: () => { appended = true; } };
  const item = { scrollIntoView: () => { scrolled = true; } };

  assert.equal(readerFollowsTranscript({ scrollY: 400, innerHeight: 500 }, { scrollHeight: 1000 }), false);
  appendLiveMessage(stream, item, false);

  assert.equal(appended, true);
  assert.equal(scrolled, false);
});

test('live messages keep following when the reader is at the end', () => {
  let scrolled = false;
  const stream = { append: () => {} };
  const item = { scrollIntoView: () => { scrolled = true; } };

  assert.equal(readerFollowsTranscript({ scrollY: 500, innerHeight: 500 }, { scrollHeight: 1000 }), true);
  appendLiveMessage(stream, item, true);

  assert.equal(scrolled, true);
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
  assert.match(event.message.html, /<p>live reply<\/p>/);
  socket.close();
});

test('closing makes both capabilities read-only', async () => {
  assert.equal((await fetch(mine + '/close', { method: 'POST' })).status, 204);
  const page = await fetch(mine, { headers: { accept: 'text/html' } }).then(response => response.text());
  assert.match(page, /<button id="close" class="close-room" type="button" hidden>Close<\/button>/);
  const response = await fetch(theirs + '/messages', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: 'too late' })
  });
  assert.equal(response.status, 409);
});

test('admin can close and delete a conversation', async () => {
  const minted = await fetch(`${base}/api/rooms`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ seed: 'admin lifecycle test', from: 'One', to: 'Two' })
  }).then(r => r.json());

  const close = await fetch(`${adminBase}/${minted.room}/toggle`, { method: 'POST', redirect: 'manual' });
  assert.equal(close.status, 303);
  const closed = await fetch(`${minted.links.mine}/messages`).then(r => r.json());
  assert.equal(closed.closed, true);

  const blocked = await fetch(`${minted.links.mine}/messages`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: 'too soon' })
  });
  assert.equal(blocked.status, 409);

  const reopen = await fetch(`${adminBase}/${minted.room}/toggle`, { method: 'POST', redirect: 'manual' });
  assert.equal(reopen.status, 303);
  const opened = await fetch(`${minted.links.mine}/messages`).then(r => r.json());
  assert.equal(opened.closed, false);
  assert.equal((await fetch(`${minted.links.mine}/messages`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: 'open again' })
  })).status, 201);

  const deletion = await fetch(`${adminBase}/${minted.room}/delete`, { method: 'POST', redirect: 'manual' });
  assert.equal(deletion.status, 303);
  assert.equal((await fetch(minted.links.mine)).status, 404);
});
