import os from 'node:os';
import path from 'node:path';

function xdgHome(value, fallback) {
  return value && path.isAbsolute(value) ? value : path.join(os.homedir(), '.local', fallback);
}

export function databasePath(env = process.env) {
  return env.DB_PATH || path.join(xdgHome(env.XDG_DATA_HOME, 'share'), 'agent-room', 'rooms.sqlite');
}

export function backupDirectory(env = process.env) {
  return path.join(xdgHome(env.XDG_STATE_HOME, 'state'), 'agent-room', 'backups');
}
