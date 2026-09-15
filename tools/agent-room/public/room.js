const mine = document.body.dataset.mine;
const stream = document.querySelector('#stream');
const empty = document.querySelector('#empty');
const closed = document.querySelector('#closed');
const form = document.querySelector('#send');
const input = document.querySelector('#text');
const dot = document.querySelector('#dot');
const status = document.querySelector('#status');
const side = document.body.dataset.side;
let seen = Number(stream.lastElementChild?.dataset.id || 0);
let polling = false;

function add(message) {
  if (message.id <= seen) return;
  seen = message.id;
  empty.hidden = true;
  const item = document.createElement('li');
  item.className = `msg${message.side === side ? ' self' : ''}${message.author === 'human' ? ' human' : ''}`;
  const meta = document.createElement('div');
  meta.className = 'meta';
  const name = document.createElement('span');
  name.className = 'name';
  name.textContent = message.side === side ? 'your side' : 'their side';
  const author = document.createElement('span');
  author.className = 'tag';
  author.textContent = message.author;
  const time = document.createElement('span');
  time.textContent = new Date(message.ts).toLocaleString();
  const body = document.createElement('p');
  body.className = 'body';
  body.textContent = message.text;
  meta.append(name, author, time);
  item.append(meta, body);
  stream.append(item);
  item.scrollIntoView({ block: 'nearest' });
}

function markClosed() {
  closed.hidden = false;
  form.hidden = true;
}

function markOpen() {
  closed.hidden = true;
  form.hidden = false;
}

function fallback() {
  if (polling) return;
  polling = true;
  (async function loop() {
    try {
      const response = await fetch(`${mine}/messages?since=${seen}&wait=25`);
      const body = await response.json();
      body.messages?.forEach(add);
      if (body.closed) markClosed();
    } catch {}
    if (window.socket?.readyState === WebSocket.OPEN) {
      polling = false;
      return;
    }
    setTimeout(loop, 1000);
  })();
}

function connect() {
  const socket = new WebSocket(mine.replace(/^http/, 'ws'));
  window.socket = socket;
  socket.onopen = () => {
    dot.className = 'dot on';
    status.textContent = 'live';
  };
  socket.onmessage = event => {
    const body = JSON.parse(event.data);
    if (body.type === 'message') add(body.message);
    if (body.type === 'closed') markClosed();
    if (body.type === 'opened') markOpen();
  };
  socket.onclose = () => {
    dot.className = 'dot';
    status.textContent = 'reconnecting';
    fallback();
    setTimeout(connect, 2500);
  };
  socket.onerror = () => socket.close();
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch(`${mine}/messages?as=human`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text })
    });
    if (!response.ok) throw Error();
  } catch {
    input.value = text;
  } finally {
    button.disabled = false;
    input.focus();
  }
});

connect();
