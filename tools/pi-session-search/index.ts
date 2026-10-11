/*
Copyright 2026 Adobe. All rights reserved.
This file is licensed to you under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License. You may obtain a copy
of the License at http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under
the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
OF ANY KIND, either express or implied. See the License for the specific language
governing permissions and limitations under the License.
*/

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { open, readdir, realpath, stat, type FileHandle } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";

const DEFAULT_ROOT = path.join(homedir(), ".pi/agent/sessions");
const DEFAULT_MAX_RECORD_BYTES = 5 * 1024 * 1024;
const DEFAULT_SNIPPET_BEFORE = 120;
const DEFAULT_SNIPPET_AFTER = 240;
const DEFAULT_MAX_RESULTS = 20;
const MAX_RESULTS_HARD_CAP = 1000;
// Per-message haystack cap before running the user-supplied regex. Bounds the
// worst case for a pathological pattern (catastrophic backtracking). It does
// NOT bound an exponentially-backtracking regex within those 256KB; we rely
// on the local-trust threat model and document the limitation in the README.
const MAX_HAYSTACK_BYTES = 256 * 1024;

export function parseDateOrThrow(value: string | undefined, label: string): number {
	if (!value) return 0;
	const t = Date.parse(value);
	if (!Number.isFinite(t)) {
		throw new Error(`Invalid ${label} "${value}": not a parseable date/time.`);
	}
	return t;
}

export function getRoot(): string {
	return process.env.PI_SESSION_SEARCH_ROOT || DEFAULT_ROOT;
}

export function getMaxBytes(): number {
	const value = Number.parseInt(process.env.PI_SESSION_SEARCH_MAX_BYTES || "", 10);
	return Number.isFinite(value) && value > 0 ? value : DEFAULT_MAX_RECORD_BYTES;
}

/**
 * Read bounded JSONL records. `null` denotes one oversized record, not EOF.
 * Count raw bytes before decoding; never accumulate an unbounded line (as
 * readline would). Buffer decoding after assembly preserves split UTF-8.
 * The generator owns the stream and closes it on EOF, early return or abort.
 */
interface PositionedRecord {
	line: string | null;
	start: number;
	end: number;
	terminated: boolean;
}

async function* sessionRecords(
	file: string, size: number, maxRecordBytes: number, signal?: AbortSignal,
): AsyncGenerator<string | null> {
	for await (const record of positionedRecords(file, size, maxRecordBytes, signal)) yield record.line;
}

// Offsets count raw bytes including LF, never decoded characters. A supplied
// descriptor keeps all passes on the same opened file and initial snapshot.
async function* snapshotChunks(handle: FileHandle, size: number, signal?: AbortSignal): AsyncGenerator<Buffer> {
	let offset = 0;
	while (offset < size) {
		signal?.throwIfAborted();
		const buffer = Buffer.allocUnsafe(Math.min(64 * 1024, size - offset));
		const { bytesRead } = await handle.read(buffer, 0, buffer.length, offset);
		signal?.throwIfAborted();
		if (!bytesRead) throw new Error("Stale read_session cursor: file was truncated during reading.");
		offset += bytesRead;
		yield buffer.subarray(0, bytesRead);
	}
}

async function* positionedRecords(
	file: string, size: number, maxRecordBytes: number, signal?: AbortSignal, handle?: FileHandle,
): AsyncGenerator<PositionedRecord> {
	signal?.throwIfAborted();
	if (size === 0) return;
	const stream = handle ? undefined : createReadStream(file, { highWaterMark: 64 * 1024, start: 0, end: size - 1, signal });
	let parts: Buffer[] = [];
	let bytes = 0;
	let oversized = false;
	let offset = 0;
	let recordStart = 0;
	try {
		for await (const chunk of handle ? snapshotChunks(handle, size, signal) : stream!) {
			signal?.throwIfAborted();
			const buffer = chunk as Buffer;
			let start = 0;
			while (start < buffer.length) {
				const newline = buffer.indexOf(10, start);
				const end = newline < 0 ? buffer.length : newline;
				const length = end - start;
				offset += length;
				if (!oversized) {
					bytes += length;
					if (bytes > maxRecordBytes) { oversized = true; parts = []; }
					else if (length) parts.push(buffer.subarray(start, end));
				}
				if (newline < 0) break;
				offset += 1;
				yield { line: oversized ? null : Buffer.concat(parts, bytes).toString("utf8"),
					start: recordStart, end: offset, terminated: true };
				signal?.throwIfAborted();
				parts = []; bytes = 0; oversized = false; recordStart = offset;
				start = newline + 1;
			}
		}
		if (oversized || bytes) yield { line: oversized ? null : Buffer.concat(parts, bytes).toString("utf8"),
			start: recordStart, end: offset, terminated: false };
	} finally {
		stream?.destroy();
	}
}

/**
 * Validate a user-supplied or LLM-supplied `maxResults` value.
 *
 * - `undefined` / `null` → DEFAULT_MAX_RESULTS (the documented default).
 * - Any other input that is not a finite integer in [1, MAX_RESULTS_HARD_CAP]
 *   (NaN, Infinity, 0, negative, fractional, non-number) → throws.
 *
 * Silently coercing an explicit invalid value (`0` becoming 20, `-5` becoming
 * 20) is surprising; we reject loudly instead. The TypeBox schema enforces
 * the same range at the tool-call layer, so the throw path is mainly for
 * programmatic callers and slash-command misuse (the slash-command parser
 * already validates `--max=` separately and never reaches here with garbage).
 */
export function validateMaxResults(raw: unknown): number {
	if (raw === undefined || raw === null) return DEFAULT_MAX_RESULTS;
	return validateResultLimit(raw, "maxResults");
}

function validateResultLimit(raw: unknown, label: string): number {
	if (
		typeof raw !== "number" ||
		!Number.isFinite(raw) ||
		!Number.isInteger(raw) ||
		raw < 1 ||
		raw > MAX_RESULTS_HARD_CAP
	) {
		throw new Error(
			`${label} must be an integer in [1, ${MAX_RESULTS_HARD_CAP}]; got ${String(raw)}`,
		);
	}
	return raw;
}

// Decode the directory-name-encoded cwd back to a real path.
// pi encodes `/home/foo/bar` as `--home-foo-bar--` (slashes -> dashes, wrapped
// in leading/trailing `--`). The decoding is best-effort and reversible only
// when the original path didn't contain literal dashes; we don't try to be
// clever about that.
export function decodeSessionDirName(name: string): string {
	let s = name;
	if (s.startsWith("--")) s = s.slice(2);
	if (s.endsWith("--")) s = s.slice(0, -2);
	return "/" + s.replace(/-/g, "/");
}

/**
 * Compile a user-supplied query string into a RegExp.
 *
 * - `/pattern/flags` form (slash-delimited regex syntax — *not* full JS
 *   literal parsing; embedded slashes inside the pattern aren't treated
 *   specially, so `/a/b/c` parses as body `a/b` with flags `c`, which then
 *   throws because `c` isn't a valid flag): respects user flags **except**
 *   `g` and `y`, which are stripped because they break the rest of the
 *   search loop:
 *     - `g` makes `String.prototype.match()` return an array without `.index`,
 *       which would silently make every snippet start at offset 0.
 *     - `y` (sticky) maintains internal `lastIndex` state across calls and
 *       leads to non-deterministic matches when the same compiled regex is
 *       reused across haystacks.
 *   Case-sensitivity is honored: `/Foo/` is case-sensitive, `/Foo/i` is
 *   case-insensitive. Empty regex (`//`) is rejected by the `.+` in the
 *   matcher — it would match every position and be useless anyway.
 * - Plain string form: literal substring search, escaped against regex
 *   metacharacters, always case-insensitive (matches the historical default
 *   and is documented as such).
 */
export function compileQuery(q: string): RegExp {
	const m = q.match(/^\/(.+)\/([gimsuy]*)$/);
	try {
		if (m) {
			const safeFlags = m[2].replace(/[gy]/g, "");
			return new RegExp(m[1], safeFlags);
		}
		return new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
	} catch (e) {
		throw new Error(`Invalid query "${q}": ${(e as Error).message}`);
	}
}

// Parse the timestamp prefix of a pi session filename.
// Format: "2026-04-23T06-48-02-781Z_<uuid>.jsonl". Returns ms since epoch or 0.
export function parseSessionFileTimestamp(filename: string): number {
	const m = filename.match(/^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z_/);
	if (!m) return 0;
	const iso = `${m[1]}T${m[2]}:${m[3]}:${m[4]}.${m[5]}Z`;
	const t = Date.parse(iso);
	return Number.isFinite(t) ? t : 0;
}

export function extractText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const block of content) {
		if (!block || typeof block !== "object") continue;
		const b = block as { type?: string; text?: string };
		if (b.type === "text" && typeof b.text === "string") parts.push(b.text);
	}
	return parts.join("\n");
}

function isGoalContinuation(content: unknown): boolean {
	if (typeof content !== "string") {
		if (!Array.isArray(content) || content.length === 0) return false;
		if (!content.every((block: unknown) => {
			if (!block || typeof block !== "object") return false;
			const part = block as { type?: unknown; text?: unknown };
			return part.type === "text" && typeof part.text === "string";
		})) return false;
	}
	// This recognizes a historical prompt format, not its author. A pasted
	// whole envelope is excluded too; mixed content and quoted examples stay.
	const text = extractText(content).trim();
	const closing = "</pi_goal_continuation>";
	return /^<pi_goal_continuation goal_id="[^"\r\n]+">/.test(text) &&
		text.endsWith(closing) && text.indexOf(closing) === text.length - closing.length;
}

function copiedHitFingerprint(id: unknown, timestamp: unknown, message: object, kind: string): string | undefined {
	if (typeof id !== "string" || !id || typeof timestamp !== "string" || !timestamp) return;
	try {
		// Compare complete JSON values, including fields outside the searchable
		// text. Object-key order is not part of message identity; array order is.
		const value = JSON.stringify([id, timestamp, message, kind], (_key, value: unknown) => {
			// Parsed overflowing JSON numbers must not serialize as null and
			// accidentally suppress a different message.
			if (typeof value === "number" && !Number.isFinite(value)) throw new Error("Non-finite identity value");
			return value && typeof value === "object" && !Array.isArray(value)
				? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
				: value;
		});
		return createHash("sha256").update(value).digest("hex");
	} catch {
		// An identity we cannot serialize must not hide a valid search hit.
		return undefined;
	}
}

export function extractToolCallText(content: unknown): string {
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const block of content) {
		if (!block || typeof block !== "object") continue;
		const b = block as { type?: string; name?: string; arguments?: unknown };
		if (b.type === "toolCall" && typeof b.name === "string") {
			let args = "";
			try {
				args = JSON.stringify(b.arguments ?? {});
			} catch {
				args = "{}";
			}
			parts.push(`[tool: ${b.name} ${args.length > 400 ? args.slice(0, 400) + "\u2026" : args}]`);
		}
	}
	return parts.join("\n");
}

export interface Hit {
	// Path to the session JSONL file *relative to the configured sessions root*
	// (e.g. "--home-foo--/2026-04-23T06-48-02-781Z_<uuid>.jsonl"). Use this with
	// read_session — it accepts either this relative path or an absolute one.
	sessionFile: string;
	sessionId: string;
	entryId?: string;
	sessionCwd: string;
	timestamp: string;
	role: string; // "user" | "assistant" | "toolCall"
	snippet: string;
}

export interface SearchOptions {
	query: string;
	cwd?: string;
	since?: string;
	until?: string;
	role?: "user" | "assistant" | "any";
	includeToolCalls?: boolean;
	maxResults?: number;
	maxResultsPerSession?: number;
	excludeSessionId?: string;
	snippetBefore?: number;
	snippetAfter?: number;
	signal?: AbortSignal;
}

export interface SearchResult {
	hits: Hit[];
	scannedFiles: number;
	skippedFiles: number;
	truncated: boolean;
	sessionsAtLimit: number;
	skippedRecords: number;
	incompleteCoverage: boolean;
	excludedGoalContinuations: number;
	duplicateHitsSuppressed: number;
}

export async function searchSessions(opts: SearchOptions): Promise<SearchResult> {
	const root = getRoot();
	const maxRecordBytes = getMaxBytes();
	const re = compileQuery(opts.query);
	const sinceMs = parseDateOrThrow(opts.since, "since");
	const untilMs = parseDateOrThrow(opts.until, "until");
	const roleFilter = opts.role ?? "any";
	const max = validateMaxResults(opts.maxResults);
	const perSessionMax = opts.maxResultsPerSession === undefined
		? undefined : validateResultLimit(opts.maxResultsPerSession, "maxResultsPerSession");
	const before = opts.snippetBefore ?? DEFAULT_SNIPPET_BEFORE;
	const after = opts.snippetAfter ?? DEFAULT_SNIPPET_AFTER;

	const hits: Hit[] = [];
	let scannedFiles = 0;
	let skippedFiles = 0;
	let truncated = false;
	let sessionsAtLimit = 0;
	let skippedRecords = 0;
	let excludedGoalContinuations = 0;
	let duplicateHitsSuppressed = 0;
	// Only retained hits claim identity, so memory is bounded by maxResults.
	const retainedCopies = new Map<string, string>();

	// Resolve the configured root once so we can apply the same symlink-
	// containment check we already do in read_session to every subdirectory we
	// walk. This stops a symlinked entry inside the sessions root from
	// silently widening the search to arbitrary parts of the filesystem.
	let resolvedRoot: string;
	try {
		resolvedRoot = await realpath(root);
	} catch {
		resolvedRoot = path.resolve(root);
	}

	let dirs: Array<{ name: string; isDirectory: () => boolean }>;
	try {
		dirs = await readdir(root, { withFileTypes: true });
	} catch {
		return { hits, scannedFiles, skippedFiles, truncated, sessionsAtLimit, skippedRecords, excludedGoalContinuations, duplicateHitsSuppressed, incompleteCoverage: skippedRecords > 0 || skippedFiles > 0 || !!opts.signal?.aborted };
	}

	outer: for (const d of dirs) {
		if (opts.signal?.aborted) break;
		if (!d.isDirectory()) continue;
		const sessionCwd = decodeSessionDirName(d.name);
		if (opts.cwd && !sessionCwd.includes(opts.cwd) && !d.name.includes(opts.cwd)) continue;

		const dirPath = path.join(root, d.name);

		// Symlink containment per subdirectory. A directory entry that resolves
		// outside the configured sessions root is silently skipped (counted as a
		// skipped file for visibility). We accept the d.isDirectory() check
		// already filtering most cases; this is belt-and-braces.
		let resolvedSubdir: string;
		try {
			resolvedSubdir = await realpath(dirPath);
		} catch {
			continue;
		}
		if (
			!resolvedSubdir.startsWith(resolvedRoot + path.sep) &&
			resolvedSubdir !== resolvedRoot
		) {
			skippedFiles += 1;
			continue;
		}

		let files: string[];
		try {
			files = (await readdir(dirPath)).filter((f) => f.endsWith(".jsonl"));
		} catch {
			continue;
		}

		for (const f of files) {
			if (opts.signal?.aborted) break outer;
			const full = path.join(dirPath, f);

			// Symlink containment per file: a `.jsonl` symlinked to outside the
			// sessions root would otherwise be silently followed by the file reader
			// below. We resolve and check before stat-ing.
			let resolvedFile: string;
			try {
				resolvedFile = await realpath(full);
			} catch {
				continue;
			}
			if (
				!resolvedFile.startsWith(resolvedRoot + path.sep) &&
				resolvedFile !== resolvedRoot
			) {
				skippedFiles += 1;
				continue;
			}

			let st;
			try {
				st = await stat(resolvedFile);
			} catch {
				continue;
			}
			// Use the filename timestamp (session start) for since/until rather than
			// mtime, which reflects the last write and would let an old conversation
			// pass a recent `since` filter.
			const startMs = parseSessionFileTimestamp(f) || st.mtimeMs;
			if (sinceMs && startMs < sinceMs) continue;
			if (untilMs && startMs > untilMs) continue;

			let sessionId = "";
			let headerCwd = sessionCwd;
			try {
				let counted = false;
				let fileHits = 0;
				records: for await (const line of sessionRecords(resolvedFile, st.size, maxRecordBytes, opts.signal)) {
					if (!counted) {
						scannedFiles += 1;
						counted = true;
					}
					if (line === null) {
						skippedRecords += 1;
						continue;
					}
					if (!line) continue;
					const record = parseRecord(line);
					if (!record || typeof record !== "object") continue;
					const obj = record as {
						type?: unknown; id?: unknown; cwd?: unknown;
						timestamp?: unknown; message?: unknown;
					};

					if (obj.type === "session") {
						sessionId = String(obj.id ?? "");
						if (obj.cwd) headerCwd = String(obj.cwd);
						if (opts.excludeSessionId && sessionId === opts.excludeSessionId) {
							// stop scanning this file entirely
							break;
						}
						continue;
					}

					if (obj.type !== "message") continue;
					if (!obj.message || typeof obj.message !== "object") continue;
					const msg = obj.message as { role?: unknown; content?: unknown };
					const role = msg.role;
					if (roleFilter !== "any" && role !== roleFilter) continue;
					if (role !== "user" && role !== "assistant") continue;
					if (role === "user" && isGoalContinuation(msg.content)) {
						excludedGoalContinuations += 1;
						continue;
					}

					const haystacks: Array<{ kind: string; text: string }> = [];
					const text = extractText(msg.content);
					if (text) haystacks.push({ kind: role, text });
					if (opts.includeToolCalls && role === "assistant") {
						const tcText = extractToolCallText(msg.content);
						if (tcText) haystacks.push({ kind: "toolCall", text: tcText });
					}

					for (const h of haystacks) {
						// Cap haystack length before regex to bound worst-case backtracking.
						const haystack = h.text.length > MAX_HAYSTACK_BYTES ? h.text.slice(0, MAX_HAYSTACK_BYTES) : h.text;
						const m = haystack.match(re);
						if (!m) continue;
						const fingerprint = copiedHitFingerprint(obj.id, obj.timestamp, msg, h.kind);
						if (fingerprint) {
							const retainedFile = retainedCopies.get(fingerprint);
							if (retainedFile !== undefined && retainedFile !== full) {
								duplicateHitsSuppressed += 1;
								continue;
							}
							retainedCopies.set(fingerprint, full);
						}
						const idx = m.index ?? 0;
						const snippet = haystack.slice(Math.max(0, idx - before), idx + after).trim();
						hits.push({
							// Display path is the original (non-realpath) location so it round-trips
							// through read_session's relative-path acceptance and matches what the
							// user sees in their sessions directory.
							sessionFile: path.relative(root, full) || full,
							sessionId,
							...(typeof obj.id === "string" && obj.id ? { entryId: obj.id } : {}),
							sessionCwd: headerCwd,
							timestamp: String(obj.timestamp ?? ""),
							role: h.kind,
							snippet,
						});
						fileHits += 1;
						const atSessionLimit = fileHits === perSessionMax;
						// Count reached limits even when both limits coincide or this
						// is the final record. No further matches are implied.
						if (atSessionLimit) sessionsAtLimit += 1;
						if (hits.length >= max) {
							truncated = true;
							break outer;
						}
						if (atSessionLimit) break records;
					}
				}
				if (!counted) scannedFiles += 1;
			} catch {
				if (opts.signal?.aborted) break outer;
				// An I/O failure can occur after some records were searched.
				// Keep those hits but report that this file was not fully scanned.
				skippedFiles += 1;
			}
		}
	}

	// Sort hits newest-first by parsed timestamp. Falls back to 0 for unparseable
	// values so they sort to the end rather than scrambling lexicographically.
	hits.sort((a, b) => {
		const ta = Date.parse(a.timestamp);
		const tb = Date.parse(b.timestamp);
		return (Number.isFinite(tb) ? tb : 0) - (Number.isFinite(ta) ? ta : 0);
	});
	return { hits, scannedFiles, skippedFiles, truncated, sessionsAtLimit, skippedRecords, excludedGoalContinuations, duplicateHitsSuppressed, incompleteCoverage: skippedRecords > 0 || skippedFiles > 0 || !!opts.signal?.aborted };
}

interface WindowEntry {
	ts: number;
	timestamp: string;
	entryId?: string;
	role: "user" | "assistant";
	text: string;
}

function windowEntry(record: unknown): WindowEntry | undefined {
	if (!record || typeof record !== "object") return;
	const obj = record as { type?: unknown; id?: unknown; timestamp?: unknown; message?: unknown };
	if (obj.type !== "message" || !obj.message || typeof obj.message !== "object") return;
	const msg = obj.message as { role?: unknown; content?: unknown };
	if (msg.role !== "user" && msg.role !== "assistant") return;
	const text = extractText(msg.content);
	const tools = msg.role === "assistant" ? extractToolCallText(msg.content) : "";
	const combined = [text, tools].filter(Boolean).join("\n");
	if (!combined) return;
	return { ts: Date.parse(String(obj.timestamp ?? "")) || 0,
		timestamp: String(obj.timestamp ?? ""),
		...(typeof obj.id === "string" && obj.id ? { entryId: obj.id } : {}),
		role: msg.role, text: combined };
}

function parseRecord(line: string): unknown {
	try {
		return JSON.parse(line);
	} catch {
		return undefined;
	}
}

// Resolve IDs from bounded headers, not filenames or copied message content.
// SDK discovery does not enforce this tool's containment and record-size limits.
async function sessionFileById(
	id: string, root: string, resolvedRoot: string, maxRecordBytes: number, signal?: AbortSignal,
): Promise<string> {
	let match: string | undefined;
	for (const dir of await readdir(root, { withFileTypes: true })) {
		signal?.throwIfAborted();
		if (!dir.isDirectory()) continue;
		let subdir: string;
		try {
			subdir = await realpath(path.join(root, dir.name));
		} catch {
			continue;
		}
		if (!subdir.startsWith(resolvedRoot + path.sep) && subdir !== resolvedRoot) continue;
		let files: string[];
		try {
			files = await readdir(subdir);
		} catch {
			continue;
		}
		for (const file of files) {
			signal?.throwIfAborted();
			if (!file.endsWith(".jsonl")) continue;
			let resolvedFile: string;
			let size: number;
			try {
				resolvedFile = await realpath(path.join(subdir, file));
				if (!resolvedFile.startsWith(resolvedRoot + path.sep) && resolvedFile !== resolvedRoot) continue;
				const info = await stat(resolvedFile);
				if (!info.isFile()) continue;
				size = info.size;
			} catch {
				continue;
			}
			let matches = false;
			for await (const line of sessionRecords(resolvedFile, size, maxRecordBytes, signal)) {
				const header = line === null ? undefined : parseRecord(line);
				matches = !!header && typeof header === "object" && "type" in header
					&& header.type === "session" && "id" in header && header.id === id;
				break; // Only the first record is a session header.
			}
			if (!matches || resolvedFile === match) continue;
			if (match) throw new Error(`Multiple session files have ID "${id}"; use sessionFile instead.`);
			match = resolvedFile;
		}
	}
	signal?.throwIfAborted();
	if (!match) throw new Error(`No readable session with ID "${id}" under the configured sessions root.`);
	return match;
}

export interface ReadSessionOptions {
	sessionFile?: string;
	sessionId?: string;
	tail?: boolean;
	after?: string;
	aroundEntryId?: string;
	aroundTimestamp?: string;
	contextMessages?: number;
	maxMessages?: number;
	signal?: AbortSignal;
}

export interface ReadSessionMessage {
	/** 1-based eligible position in file order, not timestamp order. */
	index: number;
	entryId?: string;
	role: "user" | "assistant";
	timestamp: string;
}

export interface ReadSessionResult {
	text: string;
	messages: ReadSessionMessage[];
	nextCursor: string;
	hasMore: boolean;
	skippedRecords: number;
}

interface ReadCursor {
	v: 1;
	file: string;
	dev: string;
	ino: string;
	birth: number;
	offset: number;
	index: number;
	hash: string;
	cap: number;
}

function decodeCursor(raw: string): ReadCursor {
	// Bound before decoding/JSON parsing; opaque cursors never supply read paths.
	if (raw.length > 32768 || !/^[A-Za-z0-9_-]+$/.test(raw)) throw new Error("Invalid read_session cursor.");
	let value: unknown;
	try { value = JSON.parse(Buffer.from(raw, "base64url").toString("utf8")); }
	catch { throw new Error("Invalid read_session cursor."); }
	if (!value || typeof value !== "object") throw new Error("Invalid read_session cursor.");
	const c = value as ReadCursor;
	if (c.v !== 1 || typeof c.file !== "string" || c.file.length > 8192 || !c.file ||
		path.isAbsolute(c.file) || c.file.split(path.sep).some(p => !p || p === "." || p === "..") ||
		typeof c.dev !== "string" || typeof c.ino !== "string" ||
		!Number.isFinite(c.birth) || !Number.isSafeInteger(c.offset) || c.offset < 0 ||
		!Number.isSafeInteger(c.index) || c.index < 0 || !Number.isSafeInteger(c.cap) || c.cap < 1 ||
		typeof c.hash !== "string" || !/^[a-f0-9]{64}$/.test(c.hash)) {
		throw new Error("Invalid read_session cursor.");
	}
	return c;
}

async function prefixHash(handle: FileHandle, size: number, signal?: AbortSignal): Promise<string> {
	const hash = createHash("sha256");
	signal?.throwIfAborted();
	for await (const bytes of snapshotChunks(handle, size, signal)) hash.update(bytes);
	return hash.digest("hex");
}

/**
 * Read an initial, bounded file snapshot. Cursors commit a raw-byte prefix and
 * its eligible position. Appends are allowed; replacement or changes before
 * that boundary are stale. Incomplete non-newline JSON is replayed next time.
 * maxMessages=0 does not advance, except tail=true selects the safe EOF.
 */
export async function readSession(opts: ReadSessionOptions): Promise<ReadSessionResult> {
	const maxRecordBytes = getMaxBytes();
	const ctx = opts.contextMessages ?? 6;
	const max = opts.maxMessages ?? 30;
	if (!Number.isSafeInteger(ctx) || ctx < 0) {
		throw new Error("contextMessages must be a non-negative safe integer.");
	}
	if (!Number.isSafeInteger(max) || max < 0) {
		throw new Error("maxMessages must be a non-negative safe integer.");
	}
	opts.signal?.throwIfAborted();
	if ((opts.sessionFile !== undefined) === (opts.sessionId !== undefined)) {
		throw new Error("Provide exactly one of sessionFile or sessionId.");
	}
	const selector = opts.sessionFile ?? opts.sessionId;
	if (typeof selector !== "string" || !selector.trim()) {
		throw new Error("sessionFile or sessionId must be a non-empty string.");
	}
	if (opts.tail !== undefined && typeof opts.tail !== "boolean") throw new Error("tail must be a boolean.");
	const modes = [opts.tail === true, opts.after !== undefined, opts.aroundEntryId !== undefined,
		opts.aroundTimestamp !== undefined].filter(Boolean).length;
	if (modes > 1) throw new Error("tail, after, aroundEntryId and aroundTimestamp are mutually exclusive.");
	for (const key of ["after", "aroundEntryId", "aroundTimestamp"] as const) {
		if (opts[key] !== undefined && (typeof opts[key] !== "string" || !opts[key]!.trim())) {
			throw new Error(`${key === "after" ? "after cursor" : key} must be a non-empty string.`);
		}
	}
	const target = opts.aroundTimestamp === undefined ? NaN : parseDateOrThrow(opts.aroundTimestamp, "aroundTimestamp");
	const previous = opts.after === undefined ? undefined : decodeCursor(opts.after);
	const root = getRoot();
	let resolvedRoot: string;
	let resolvedFile: string;
	try {
		resolvedRoot = await realpath(root);
	} catch {
		resolvedRoot = path.resolve(root);
	}
	const input = opts.sessionFile ?? await sessionFileById(selector, root, resolvedRoot, maxRecordBytes, opts.signal);
	const candidate = path.isAbsolute(input) ? input : path.join(root, input);
	try {
		resolvedFile = await realpath(candidate);
	} catch {
		resolvedFile = path.resolve(candidate);
	}
	if (!resolvedFile.startsWith(resolvedRoot + path.sep) && resolvedFile !== resolvedRoot) {
		throw new Error(`Refusing to read outside session root: ${resolvedRoot}`);
	}

	const relativeFile = path.relative(resolvedRoot, resolvedFile);
	// Reject FIFOs/devices before open("r"), which can block without observing
	// cancellation. Keep descriptor validation below; the same-user TOCTOU
	// boundary remains unchanged.
	const preflight = await stat(resolvedFile);
	if (!preflight.isFile()) throw new Error("Session path is not a regular file.");
	opts.signal?.throwIfAborted();
	const handle = await open(resolvedFile, "r");
	try {
		const st = await handle.stat();
		if (!st.isFile()) throw new Error("Session path is not a regular file.");
		if (previous && (previous.file !== relativeFile || previous.dev !== String(st.dev) ||
			previous.ino !== String(st.ino) || previous.birth !== st.birthtimeMs ||
			previous.offset > st.size || previous.cap !== maxRecordBytes ||
			previous.hash !== await prefixHash(handle, previous.offset, opts.signal))) {
			throw new Error("Stale read_session cursor: file identity or committed prefix changed.");
		}

		let header: { id?: unknown; cwd?: unknown; timestamp?: unknown } | undefined;
		let total = 0;
		let skippedRecords = 0;
		let nearest = 0;
		let anchorFound = false;
		let bestDiff = Infinity;
		let safeEnd = 0;
		let previousBoundaryFound = !previous || previous.offset === 0;
		for await (const item of positionedRecords(resolvedFile, st.size, maxRecordBytes, opts.signal, handle)) {
			const record = item.line === null ? undefined : parseRecord(item.line);
			// Do not commit incomplete trailing JSON (including an oversized tail).
			// Complete final JSON without LF remains compatible with older sessions.
			if (item.line === null) skippedRecords += 1;
			if (!item.terminated && (item.line === null || record === undefined)) break;
			safeEnd = item.end;
			if (record && typeof record === "object" && "type" in record && record.type === "session") {
				const h = record as { id?: unknown; cwd?: unknown; timestamp?: unknown };
				header = { id: h.id, cwd: h.cwd, timestamp: h.timestamp };
			}
			const entry = windowEntry(record);
			if (entry) {
				const diff = Math.abs(entry.ts - target);
				if (diff < bestDiff) { bestDiff = diff; nearest = total; }
				if (opts.aroundEntryId !== undefined && entry.entryId === opts.aroundEntryId && !anchorFound) {
					nearest = total; anchorFound = true;
				}
				total += 1;
			}
			if (previous && item.end === previous.offset) {
				previousBoundaryFound = total === previous.index;
			} else if (previous && item.start < previous.offset && previous.offset < item.end &&
				item.line !== null && record !== undefined && total === previous.index) {
				// A complete final JSON record may have been committed without LF.
				// Later appending its delimiter/whitespace moves the record end, not
				// its identity. Recheck the bounded old prefix as complete JSON.
				const prefix = Buffer.from(item.line).subarray(0, previous.offset - item.start).toString("utf8");
				previousBoundaryFound = parseRecord(prefix) !== undefined;
			}
		}
		if (previous && (!previousBoundaryFound || (previous.offset === 0 && previous.index !== 0))) {
			throw new Error("Stale read_session cursor: committed record boundary changed.");
		}
		if (opts.aroundEntryId !== undefined && !anchorFound) {
			throw new Error(`No eligible message with entry ID "${opts.aroundEntryId}".`);
		}

		let startIdx = previous?.index ?? 0;
		let endIdx = Math.min(total, startIdx + max);
		if (opts.tail) { startIdx = Math.max(0, total - max); endIdx = total; }
		else if ((Number.isFinite(target) || opts.aroundEntryId !== undefined) && total) {
			const lower = Math.max(0, nearest - ctx);
			const upper = Math.min(total, nearest + Math.min(ctx, total - nearest - 1) + 1);
			const count = Math.min(max, upper - lower);
			// Odd extra context goes before the anchor. At boundaries, redistribute
			// only within the requested radius; never enlarge context to fill max.
			startIdx = Math.max(lower, nearest - Math.ceil(Math.max(0, count - 1) / 2));
			endIdx = Math.min(upper, startIdx + count);
			startIdx = Math.max(lower, endIdx - count);
			if (endIdx - startIdx < count) endIdx = Math.min(upper, startIdx + count);
		}

		const entries: Array<{ entry: WindowEntry; index: number }> = [];
		let cursorOffset = previous?.offset ?? 0;
		let cursorIndex = previous?.index ?? 0;
		if (endIdx > startIdx) {
			let index = 0;
			for await (const item of positionedRecords(resolvedFile, safeEnd, maxRecordBytes, opts.signal, handle)) {
				const entry = item.line === null ? undefined : windowEntry(parseRecord(item.line));
				if (!entry) continue;
				if (index >= startIdx) {
					entries.push({ entry, index: index + 1 });
					cursorOffset = item.end; cursorIndex = index + 1;
				}
				index += 1;
				if (index >= endIdx) break;
			}
		}
		if (opts.tail || (max > 0 && cursorIndex === total)) {
			cursorOffset = safeEnd; cursorIndex = total;
		}
		const nextCursor = Buffer.from(JSON.stringify({ v: 1, file: relativeFile,
			dev: String(st.dev), ino: String(st.ino), birth: st.birthtimeMs,
			offset: cursorOffset, index: cursorIndex,
			hash: await prefixHash(handle, cursorOffset, opts.signal), cap: maxRecordBytes,
		} satisfies ReadCursor)).toString("base64url");
		const messages: ReadSessionMessage[] = entries.map(({ entry, index }) => ({ index,
			...(entry.entryId === undefined ? {} : { entryId: entry.entryId }),
			role: entry.role, timestamp: entry.timestamp }));
		const hasMore = cursorIndex < total;
		const out: string[] = [];
		if (header) out.push(`# Session ${header.id} — cwd: ${header.cwd} — started: ${header.timestamp}`);
		out.push(`# Showing messages ${startIdx + 1}–${endIdx} of ${total}`);
		if (skippedRecords) out.push(`# Incomplete coverage: skipped ${skippedRecords} oversized record${skippedRecords === 1 ? "" : "s"}.`);
		out.push("");
		for (const { entry, index } of entries) {
			out.push(`## ${entry.role} @ ${new Date(entry.ts).toISOString()} — message ${index}${entry.entryId === undefined ? "" : ` — entryId: ${JSON.stringify(entry.entryId)}`}`);
			out.push(entry.text, "");
		}
		out.push(`# Navigation ${JSON.stringify({ nextCursor, hasMore, skippedRecords })}`);
		return { text: out.join("\n"), messages, nextCursor, hasMore, skippedRecords };
	} finally {
		await handle.close();
	}
}

/** Compatibility renderer for existing programmatic callers. */
export async function readSessionWindow(opts: ReadSessionOptions): Promise<string> {
	return (await readSession(opts)).text;
}

export function formatHitsForCommand(result: SearchResult): string {
	const filtering = result.excludedGoalContinuations || result.duplicateHitsSuppressed
		? `Excluded ${result.excludedGoalContinuations} goal continuations; suppressed ${result.duplicateHitsSuppressed} copied hits in scanned records.`
		: "";
	const warning = !result.incompleteCoverage ? "" : result.skippedRecords || result.skippedFiles
		? `Incomplete coverage: skipped ${result.skippedRecords} oversized record${result.skippedRecords === 1 ? "" : "s"}, ${result.skippedFiles} files.`
		: "Incomplete coverage: search cancelled.";
	if (result.hits.length === 0) {
		return [
			`No matches. (scanned ${result.scannedFiles} files, skipped ${result.skippedFiles})`,
			filtering,
			warning,
		].filter(Boolean).join("\n");
	}
	const lines: string[] = [];
	lines.push(
		`${result.hits.length} hit${result.hits.length === 1 ? "" : "s"}${result.truncated ? " (truncated)" : ""}, scanned ${result.scannedFiles} files:`,
	);
	if (filtering) lines.push(filtering);
	if (result.sessionsAtLimit) {
		lines.push(`Per-session limit reached in ${result.sessionsAtLimit} file${result.sessionsAtLimit === 1 ? "" : "s"}; remaining records were not searched.`);
	}
	if (warning) lines.push(warning);
	for (const h of result.hits) {
		lines.push("");
		lines.push(`• ${h.timestamp}  [${h.role}]  ${h.sessionCwd}`);
		lines.push(`  ${h.sessionFile}`);
		const snippet = h.snippet.replace(/\s+/g, " ").slice(0, 280);
		lines.push(`  ${snippet}`);
	}
	return lines.join("\n");
}

/**
 * Parse `/find-sessions` arguments. Pure helper extracted so it can be unit-
 * tested without having to mock an ExtensionCommandContext. Returns either
 * a validated `query` (plus optional flags) or an `error` message.
 */
export interface ParsedFindArgs {
	query?: string;
	cwd?: string;
	role?: "user" | "assistant" | "any";
	since?: string;
	until?: string;
	max?: number;
	error?: string;
}

export function parseFindSessionsArgs(raw: string): ParsedFindArgs {
	const out: ParsedFindArgs = {};
	const rest: string[] = [];
	for (const tok of raw.trim().split(/\s+/)) {
		if (tok.startsWith("--cwd=")) out.cwd = tok.slice("--cwd=".length);
		else if (tok.startsWith("--role=")) {
			const v = tok.slice("--role=".length);
			if (v === "user" || v === "assistant" || v === "any") out.role = v;
			else return { error: `Invalid --role=${v}. Use user|assistant|any.` };
		} else if (tok.startsWith("--since=")) out.since = tok.slice("--since=".length);
		else if (tok.startsWith("--until=")) out.until = tok.slice("--until=".length);
		else if (tok.startsWith("--max=")) {
			const n = Number.parseInt(tok.slice("--max=".length), 10);
			if (Number.isFinite(n) && n > 0) out.max = n;
			else return { error: `Invalid --max=${tok.slice("--max=".length)}. Use a positive integer.` };
		} else rest.push(tok);
	}
	const query = rest.join(" ").trim();
	if (query) out.query = query;
	return out;
}

function getCurrentSessionId(ctx: ExtensionContext): string | undefined {
	try {
		const header = (ctx.sessionManager as { getHeader?: () => { id?: string } | null }).getHeader?.();
		return header?.id;
	} catch {
		return undefined;
	}
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "search_sessions",
		label: "Search prior pi sessions",
		description:
			"Search prior Pi session transcripts (~/.pi/agent/sessions) without resuming them. Use for prior discussions or decisions. Excludes whole user goal-continuation envelopes and collapses recorded message copies across files. Read-only.",
		promptSnippet: "Find prior pi sessions matching a query.",
		promptGuidelines: [
			"Use search_sessions with a focused query; narrow by cwd when the project is known.",
			"Treat search_sessions hits as candidates, not complete evidence: read promising hits with read_session and deduplicate hits from the same session or task.",
		],
		parameters: Type.Object({
			query: Type.String({
				description:
					"Plain substring (case-insensitive) or `/regex/flags` form. Regex flags `g` and `y` are stripped because they break the snippet/index logic; case-sensitivity in the regex form is honored (use `/Foo/i` for case-insensitive). Searches user/assistant message text.",
			}),
			cwd: Type.Optional(
				Type.String({
					description: "Filter sessions by working directory (substring match against the session's cwd, e.g. 'OneAdobe' or '/home/sesselma/workspace').",
				}),
			),
			since: Type.Optional(
				Type.String({ description: "ISO date/time; ignore sessions started before this (parsed from filename timestamp)." }),
			),
			until: Type.Optional(
				Type.String({ description: "ISO date/time; ignore sessions started after this (parsed from filename timestamp)." }),
			),
			role: Type.Optional(
				Type.Union([Type.Literal("user"), Type.Literal("assistant"), Type.Literal("any")], {
					description: "Restrict matches to user messages, assistant messages, or both. Default: any.",
				}),
			),
			includeToolCalls: Type.Optional(
				Type.Boolean({ description: "Also search assistant tool-call names/arguments; for past tool usage, query the exact tool name or distinctive argument. Default false." }),
			),
			maxResults: Type.Optional(
				Type.Integer({
					minimum: 1,
					maximum: MAX_RESULTS_HARD_CAP,
					description: `Maximum number of hits to return. Default ${DEFAULT_MAX_RESULTS}, hard cap ${MAX_RESULTS_HARD_CAP}.`,
				}),
			),
			maxResultsPerSession: Type.Optional(
				Type.Integer({
					minimum: 1,
					maximum: MAX_RESULTS_HARD_CAP,
					description: "Maximum retained hits per session file. Omit for no per-session limit; use 2–3 to compare sessions. Retains first-encountered matches, then moves to the next file. sessionsAtLimit counts files reaching this cap; truncated marks the total hit limit, and incompleteCoverage marks skipped records/files or cancellation.",
				}),
			),
			includeCurrentSession: Type.Optional(
				Type.Boolean({ description: "Include the current session in results. Default false." }),
			),
		}),
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			const query = String(params.query ?? "").trim();
			if (!query) {
				return {
					content: [{ type: "text", text: "Error: `query` is required." }],
					details: {},
					isError: true,
				};
			}
			const excludeSessionId = params.includeCurrentSession ? undefined : getCurrentSessionId(ctx);
			try {
				const result = await searchSessions({
					query,
					cwd: params.cwd as string | undefined,
					since: params.since as string | undefined,
					until: params.until as string | undefined,
					role: params.role as "user" | "assistant" | "any" | undefined,
					includeToolCalls: params.includeToolCalls as boolean | undefined,
					maxResults: params.maxResults as number | undefined,
					maxResultsPerSession: params.maxResultsPerSession as number | undefined,
					excludeSessionId,
					signal,
				});
				const details = {
					count: result.hits.length,
					truncated: result.truncated,
					sessionsAtLimit: result.sessionsAtLimit,
					skippedRecords: result.skippedRecords,
					excludedGoalContinuations: result.excludedGoalContinuations,
					duplicateHitsSuppressed: result.duplicateHitsSuppressed,
					incompleteCoverage: result.incompleteCoverage,
				};
				const payload = {
					...details,
					scannedFiles: result.scannedFiles,
					skippedFiles: result.skippedFiles,
					hits: result.hits,
				};
				return {
					content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
					details,
				};
			} catch (e) {
				return {
					content: [{ type: "text", text: `search_sessions failed: ${(e as Error).message}` }],
					details: {},
					isError: true,
				};
			}
		},
	});

	pi.registerTool({
		name: "read_session",
		label: "Read a window of a prior pi session",
		description:
			"Read prior Pi session messages in file order: start, tail, continuation, or centered context. Read-only.",
		promptSnippet: "Read a window from a prior pi session by file or session ID.",
		promptGuidelines: [
			"Use read_session with the returned sessionFile unchanged and a modest maxMessages.",
		],
		parameters: Type.Object({
			sessionFile: Type.Optional(Type.String({
				description: "Path to a session .jsonl file. Either absolute, or relative to the configured sessions root (as returned by search_sessions). Provide exactly one of sessionFile or sessionId.",
			})),
			sessionId: Type.Optional(Type.String({
				description: "Exact session header ID, resolved only within the configured sessions root. Use when a parent session path comes from a different machine or sandbox. Provide exactly one of sessionFile or sessionId.",
			})),
			tail: Type.Optional(Type.Boolean({
				description: "Return the last maxMessages eligible messages in file order. With maxMessages=0, select the safe EOF cursor. Default false.",
			})),
			after: Type.Optional(Type.String({
				description: "Opaque nextCursor from an earlier read of this file. Page or poll messages after its committed boundary; safe across appends, errors if its prefix changed or file was replaced. Cursors are returned even for empty reads; hasMore covers only the initial snapshot, not future appends. Mutually exclusive with tail=true and centered modes.",
			})),
			aroundEntryId: Type.Optional(Type.String({
				description: "Exact entryId from a search hit; center on the first eligible occurrence in file order. Errors if missing. Mutually exclusive with other selection modes.",
			})),
			aroundTimestamp: Type.Optional(
				Type.String({ description: "Center on the nearest message to a search hit's timestamp (ISO date/time; invalid dates rejected). Ties prefer the first message in file order. Mutually exclusive with other selection modes." }),
			),
			contextMessages: Type.Optional(
				Type.Integer({ minimum: 0, maximum: Number.MAX_SAFE_INTEGER, description: "Maximum context radius on each side of a centered target. Default 6. maxMessages shrinks symmetrically, always retaining the anchor when positive; extra context prefers preceding messages." }),
			),
			maxMessages: Type.Optional(
				Type.Integer({ minimum: 0, maximum: Number.MAX_SAFE_INTEGER, description: "Maximum returned eligible messages. Default 30. Zero returns none and does not advance the cursor, except tail=true selects safe EOF." }),
			),
		}),
		async execute(_toolCallId, params, signal) {
			try {
				const result = await readSession({
					sessionFile: params.sessionFile,
					sessionId: params.sessionId,
					tail: params.tail as boolean | undefined,
					after: params.after as string | undefined,
					aroundEntryId: params.aroundEntryId as string | undefined,
					aroundTimestamp: params.aroundTimestamp as string | undefined,
					contextMessages: params.contextMessages as number | undefined,
					maxMessages: params.maxMessages as number | undefined,
					signal,
				});
				const { text, ...details } = result;
				return { content: [{ type: "text", text }], details };
			} catch (e) {
				return {
					content: [{ type: "text", text: `read_session failed: ${(e as Error).message}` }],
					details: {},
					isError: true,
				};
			}
		},
	});

	pi.registerCommand("find-sessions", {
		description:
			"Search past pi sessions for a query string. Usage: /find-sessions [--cwd=substr] [--role=user|assistant] [--since=ISO] [--until=ISO] [--max=N] <query>",
		handler: async (rawArgs, ctx) => {
			const args = (rawArgs ?? "").trim();
			if (!args) {
				ctx.ui.notify("Usage: /find-sessions [--cwd=…] [--role=…] [--since=…] [--until=…] [--max=N] <query>", "warning");
				return;
			}
			const parsed = parseFindSessionsArgs(args);
			if (parsed.error) {
				ctx.ui.notify(parsed.error, "warning");
				return;
			}
			if (!parsed.query) {
				ctx.ui.notify("Missing query.", "warning");
				return;
			}
			ctx.ui.notify(`Searching prior sessions for: ${parsed.query}`, "info");
			const result = await searchSessions({
				query: parsed.query,
				cwd: parsed.cwd,
				role: parsed.role,
				since: parsed.since,
				until: parsed.until,
				maxResults: parsed.max,
				excludeSessionId: getCurrentSessionId(ctx),
			});
			pi.sendMessage(
				{
					customType: "session-search",
					content: formatHitsForCommand(result),
					display: true,
				},
				{ triggerTurn: false },
			);
		},
	});
}
