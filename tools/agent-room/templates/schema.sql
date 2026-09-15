PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
DROP TABLE IF EXISTS webhooks;
CREATE TABLE IF NOT EXISTS rooms (
  id TEXT PRIMARY KEY,
  token_a TEXT NOT NULL UNIQUE,
  token_b TEXT NOT NULL UNIQUE,
  seed TEXT NOT NULL DEFAULT '',
  name_a TEXT NOT NULL DEFAULT '',
  name_b TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  closed_by TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  side TEXT NOT NULL CHECK(side IN ('a', 'b', 'system')),
  author TEXT NOT NULL CHECK(author IN ('agent', 'human', 'system')),
  text TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_room_id_id ON messages(room_id, id);
