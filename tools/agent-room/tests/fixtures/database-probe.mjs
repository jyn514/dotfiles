import assert from 'node:assert/strict';
import { once } from 'node:events';

const { server, adminServer, db } = await import('../../server.mjs');
if (!server.listening) await once(server, 'listening');
if (!adminServer.listening) await once(adminServer, 'listening');

const response = await fetch(`http://127.0.0.1:${server.address().port}/api/rooms`, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ seed: 'persist across restarts' })
});
assert.equal(response.status, 201);

await Promise.all([
  new Promise(resolve => server.close(resolve)),
  new Promise(resolve => adminServer.close(resolve))
]);
db.close();
