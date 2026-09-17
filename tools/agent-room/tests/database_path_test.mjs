import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const probe = fileURLToPath(new URL('./fixtures/database-probe.mjs', import.meta.url));

test('rooms persist outside the checkout across server restarts', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-room-db-'));
  try {
    const cwd = path.join(root, 'run');
    const dataHome = path.join(root, 'xdg-data');
    fs.mkdirSync(path.join(cwd, 'data'), { recursive: true });
    const { DB_PATH: _dbPath, XDG_DATA_HOME: _dataHome, ...environment } = process.env;
    const env = { ...environment, HOME: path.join(root, 'home'), XDG_DATA_HOME: dataHome,
      PORT: '0', ADMIN_PORT: '0', HOST: '127.0.0.1' };

    for (let count = 1; count <= 2; count++) {
      const run = spawnSync(process.execPath, [probe], { cwd, env, encoding: 'utf8', timeout: 10_000 });
      assert.equal(run.status, 0, run.stderr || run.error?.message);
      const db = new DatabaseSync(path.join(dataHome, 'agent-room', 'rooms.sqlite'), { readOnly: true });
      try {
        assert.equal(db.prepare('SELECT count(*) AS count FROM rooms').get().count, count);
      } finally {
        db.close();
      }
    }

    const fallback = { ...env };
    delete fallback.XDG_DATA_HOME;
    const run = spawnSync(process.execPath, [probe], { cwd, env: fallback,
      encoding: 'utf8', timeout: 10_000 });
    assert.equal(run.status, 0, run.stderr || run.error?.message);
    const fallbackDb = new DatabaseSync(path.join(fallback.HOME, '.local', 'share',
      'agent-room', 'rooms.sqlite'), { readOnly: true });
    try {
      assert.equal(fallbackDb.prepare('SELECT count(*) AS count FROM rooms').get().count, 1);
    } finally {
      fallbackDb.close();
    }
    assert.equal(fs.existsSync(path.join(cwd, 'data', 'rooms.sqlite')), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
