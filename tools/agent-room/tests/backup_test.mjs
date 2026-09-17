import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createBackup, retainedBackupNames, verifySnapshot } from '../backup.mjs';
import { backupDirectory, databasePath } from '../storage.mjs';

const schema = fs.readFileSync(fileURLToPath(new URL('../templates/schema.sql', import.meta.url)), 'utf8');

test('a live WAL database becomes a private, standalone snapshot', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-room-backup-'));
  try {
    const source = path.join(root, 'data', 'rooms.sqlite');
    const directory = path.join(root, 'state', 'backups');
    fs.mkdirSync(path.dirname(source));
    const live = new DatabaseSync(source);
    try {
      live.exec(schema);
      live.prepare(`INSERT INTO rooms
        (id, token_a, token_b, created_at, updated_at)
        VALUES ('room', 'room.a', 'room.b', 1, 1)`).run();
      live.prepare(`INSERT INTO messages (room_id, side, author, text, ts)
        VALUES ('room', 'a', 'agent', 'preserve this message', 2)`).run();
      const result = await createBackup({ source, directory, now: new Date('2026-09-17T12:00:00Z') });
      assert.deepEqual({ rooms: result.rooms, messages: result.messages }, { rooms: 1, messages: 1 });
      assert.deepEqual(verifySnapshot(result.target), { rooms: 1, messages: 1 });
      assert.equal(fs.statSync(result.target).mode & 0o777, 0o600);
      assert.equal(fs.statSync(directory).mode & 0o777, 0o700);
      assert.deepEqual(fs.readdirSync(directory), [path.basename(result.target)]);
    } finally {
      live.close();
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('a failed backup cannot remove the last good snapshot', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-room-backup-'));
  try {
    const source = path.join(root, 'broken.sqlite');
    const directory = path.join(root, 'backups');
    fs.mkdirSync(directory);
    const prior = path.join(directory, '2026-09-16T12-00-00.000Z-12345678.sqlite');
    fs.writeFileSync(prior, 'previous snapshot');
    fs.writeFileSync(source, 'not a SQLite database');
    await assert.rejects(createBackup({ source, directory }), /database|SQLite|file/i);
    assert.equal(fs.readFileSync(prior, 'utf8'), 'previous snapshot');
    assert.deepEqual(fs.readdirSync(directory), [path.basename(prior)]);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('successful retention removes only expired managed snapshots', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-room-backup-'));
  try {
    const source = path.join(root, 'rooms.sqlite');
    const directory = path.join(root, 'backups');
    fs.mkdirSync(directory);
    const db = new DatabaseSync(source);
    db.exec(schema);
    db.close();
    const expired = '2026-08-01T12-00-00.000Z-12345678.sqlite';
    fs.writeFileSync(path.join(directory, expired), 'expired');
    const existing = path.join(directory, '2026-09-16T12-00-00.000Z-12345678.sqlite');
    fs.writeFileSync(existing, 'earlier snapshot', { mode: 0o644 });
    fs.chmodSync(existing, 0o644);
    fs.writeFileSync(path.join(directory, 'manual-copy.sqlite'), 'keep');
    const result = await createBackup({ source, directory, now: new Date('2026-09-17T12:00:00Z') });
    assert.equal(fs.existsSync(path.join(directory, expired)), false);
    assert.equal(fs.statSync(existing).mode & 0o777, 0o600);
    assert.equal(fs.readFileSync(path.join(directory, 'manual-copy.sqlite'), 'utf8'), 'keep');
    assert.deepEqual(verifySnapshot(result.target), { rooms: 0, messages: 0 });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('retention keeps distinct hourly and daily snapshots, not duplicate runs', () => {
  const now = new Date('2026-09-17T12:00:00Z');
  const name = date => `${date.toISOString().replaceAll(':', '-')}-12345678.sqlite`;
  const hourly = Array.from({ length: 27 }, (_, i) => name(new Date(now.getTime() - i * 60 * 60 * 1000)));
  const daily = Array.from({ length: 35 }, (_, i) => name(new Date(now.getTime() - i * 24 * 60 * 60 * 1000)));
  const duplicate = `${now.toISOString().replaceAll(':', '-')}-abcdef12.sqlite`;
  const keep = retainedBackupNames([...hourly, ...daily, duplicate], now.getTime());
  assert.equal(keep.has(hourly[26]), false);
  assert.equal(keep.has(daily[34]), false);
  assert.equal(keep.has(daily[29]), true);
  assert.equal(keep.has(duplicate) && keep.has(hourly[0]), false);
  assert.equal(keep.has('unrelated.sqlite'), false);
});

test('server and backup resolve the same database override', () => {
  const env = { DB_PATH: '/private/tmp/custom-room.sqlite', XDG_STATE_HOME: '/private/tmp/state' };
  assert.equal(databasePath(env), env.DB_PATH);
  assert.equal(backupDirectory(env), '/private/tmp/state/agent-room/backups');
});
