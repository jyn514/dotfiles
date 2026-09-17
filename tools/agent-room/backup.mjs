import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { backup, DatabaseSync } from 'node:sqlite';
import { backupDirectory, databasePath } from './storage.mjs';

const DAY = 24 * 60 * 60 * 1000;
const SNAPSHOT = /^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2}\.\d{3}Z)-[a-f0-9]{8}\.sqlite$/;

function snapshotTime(name) {
  const match = SNAPSHOT.exec(name);
  if (!match) return null;
  const time = Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4]}`);
  return Number.isFinite(time) ? time : null;
}

export function retainedBackupNames(names, now = Date.now()) {
  const snapshots = names.map(name => ({ name, time: snapshotTime(name) }))
    .filter(item => item.time !== null).sort((a, b) => b.time - a.time);
  const keep = new Set();
  const hours = new Set();
  const days = new Set();
  for (const { name, time } of snapshots) {
    const age = now - time;
    if (age < 0) { keep.add(name); continue; }
    const hour = name.slice(0, 13);
    const day = name.slice(0, 10);
    if (age < DAY && hours.size < 24 && !hours.has(hour)) { keep.add(name); hours.add(hour); }
    if (age < 30 * DAY && days.size < 30 && !days.has(day)) { keep.add(name); days.add(day); }
  }
  if (snapshots.length) keep.add(snapshots[0].name);
  return keep;
}

export function verifySnapshot(file) {
  const db = new DatabaseSync(file, { readOnly: true });
  try {
    if (db.prepare('PRAGMA integrity_check').get().integrity_check !== 'ok') {
      throw new Error('SQLite integrity check failed');
    }
    if (db.prepare('PRAGMA foreign_key_check').all().length) {
      throw new Error('SQLite foreign key check failed');
    }
    db.prepare('SELECT id, token_a, token_b, seed, name_a, name_b, created_at, updated_at, closed_by FROM rooms LIMIT 0').all();
    db.prepare('SELECT id, room_id, side, author, text, ts FROM messages LIMIT 0').all();
    return {
      rooms: db.prepare('SELECT count(*) AS count FROM rooms').get().count,
      messages: db.prepare('SELECT count(*) AS count FROM messages').get().count
    };
  } finally {
    db.close();
  }
}

export async function createBackup({ source = databasePath(), directory = backupDirectory(), now = new Date() } = {}) {
  if (source === ':memory:') throw new Error('Cannot back up an in-memory database');
  if (!fs.statSync(source).isFile()) throw new Error('Database source is not a file');
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  if (!fs.lstatSync(directory).isDirectory()) throw new Error('Backup directory is not a directory');
  fs.chmodSync(directory, 0o700);
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isFile() && snapshotTime(entry.name) !== null) {
      fs.chmodSync(path.join(directory, entry.name), 0o600);
    }
  }

  const stamp = now.toISOString().replaceAll(':', '-');
  const id = crypto.randomBytes(4).toString('hex');
  const target = path.join(directory, `${stamp}-${id}.sqlite`);
  const temporary = path.join(directory, `.${stamp}-${id}.tmp`);
  const sourceDb = new DatabaseSync(source, { readOnly: true });
  let restoreDirectory;
  try {
    restoreDirectory = fs.mkdtempSync(path.join(directory, '.restore-'));
    const restoreCopy = path.join(restoreDirectory, 'rooms.sqlite');
    const handle = fs.openSync(temporary, 'wx', 0o600);
    fs.closeSync(handle);
    await backup(sourceDb, temporary);
    const snapshotDb = new DatabaseSync(temporary);
    try {
      if (snapshotDb.prepare('PRAGMA journal_mode = DELETE').get().journal_mode !== 'delete') {
        throw new Error('Could not make the snapshot standalone');
      }
    } finally {
      snapshotDb.close();
    }
    fs.chmodSync(temporary, 0o600);
    fs.copyFileSync(temporary, restoreCopy, fs.constants.COPYFILE_EXCL);
    const counts = verifySnapshot(restoreCopy);
    const syncHandle = fs.openSync(temporary, 'r');
    try { fs.fsyncSync(syncHandle); } finally { fs.closeSync(syncHandle); }
    fs.renameSync(temporary, target);
    const directoryHandle = fs.openSync(directory, 'r');
    try { fs.fsyncSync(directoryHandle); } finally { fs.closeSync(directoryHandle); }

    const entries = fs.readdirSync(directory, { withFileTypes: true })
      .filter(entry => entry.isFile() && snapshotTime(entry.name) !== null)
      .map(entry => entry.name);
    const keep = retainedBackupNames(entries, now.getTime());
    for (const name of entries) if (!keep.has(name)) fs.unlinkSync(path.join(directory, name));
    return { target, ...counts };
  } finally {
    sourceDb.close();
    if (restoreDirectory) fs.rmSync(restoreDirectory, { recursive: true, force: true });
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    for (const suffix of ['-wal', '-shm']) {
      if (fs.existsSync(temporary + suffix)) fs.unlinkSync(temporary + suffix);
    }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  createBackup().then(({ target, rooms, messages }) => {
    console.log(`Validated backup ${target}: ${rooms} rooms, ${messages} messages`);
  }).catch(error => {
    console.error(`Backup failed: ${error.message}`);
    process.exitCode = 1;
  });
}
