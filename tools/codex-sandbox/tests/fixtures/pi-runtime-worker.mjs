import assert from 'node:assert/strict';
import { once } from 'node:events';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createConnection } from 'node:net';

const directory = await mkdtemp('/tmp/staged-worker-');
const socketPath = '/tmp/codex-tool-worker.sock';
assert(process.versions.bun, 'run the worker probe under Bun');
assert.equal((await readFile('/proc/1/comm', 'utf8')).trim(), 'bun');
try {
    for (let attempt = 0; !existsSync(socketPath) && attempt < 100; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 20));
    }
    assert(existsSync(socketPath), 'worker failed to listen');
    await writeFile(`${directory}/example.txt`, 'staged-worker-read-ok');
    for (const [tool, params, expected] of [
        ['read', { path: `${directory}/example.txt` }, 'staged-worker-read-ok'],
        ['bash', { command: 'printf staged-worker-bash-ok' }, 'staged-worker-bash-ok'],
    ]) {
        const socket = createConnection(socketPath);
        await once(socket, 'connect');
        socket.write(JSON.stringify({ tool, params, model: null, session: null }) + '\n');
        let received = '';
        for await (const chunk of socket) received += chunk.toString();
        const frames = received.trim().split('\n').map(line => JSON.parse(line));
        const result = frames.find(frame => frame.kind === 'result');
        assert(result, received);
        assert(JSON.stringify(result).includes(expected), received);
    }
} finally {
    await rm(directory, { recursive: true, force: true });
}
