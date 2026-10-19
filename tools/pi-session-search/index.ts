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

type SessionSource = "pi" | "codex";
interface SessionRoot { source: SessionSource; root: string }

function sessionRoots(): SessionRoot[] {
	return [
		{ source: "pi", root: getRoot() },
		{ source: "codex", root: process.env.PI_SESSION_SEARCH_CODEX_ROOT ||
			path.join(process.env.CODEX_HOME || path.join(homedir(), ".codex"), "sessions") },
	];
}

function contained(root: string, file: string): boolean {
	return file === root || file.startsWith(root + path.sep);
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
	// Pi paths are relative to its configured root; Codex paths are absolute so
	// callers can pass either source's search hit unchanged to read_session.
	sessionFile: string;
	source?: SessionSource;
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

interface SessionCandidate {
	file: string;
	cwd: string;
}

// Pi owns one directory level; Codex uses date directories. Check containment
// before descending and deduplicate resolved directories to avoid alias cycles.
async function* sessionCandidates(
	config: SessionRoot, signal?: AbortSignal, skipped: () => void = () => {},
): AsyncGenerator<SessionCandidate> {
	let resolvedRoot: string;
	try { resolvedRoot = await realpath(config.root); }
	catch { return; } // A missing optional history root is normal.
	const visited = new Set<string>();
	const pending = [{ dir: path.resolve(config.root), depth: 0, cwd: "" }];
	while (pending.length) {
		signal?.throwIfAborted();
		const current = pending.pop()!;
		let dir: string;
		try { dir = await realpath(current.dir); }
		catch { skipped(); continue; }
		if (!contained(resolvedRoot, dir)) { skipped(); continue; }
		if (visited.has(dir)) continue;
		visited.add(dir);
		let entries;
		try { entries = await readdir(current.dir, { withFileTypes: true }); }
		catch { skipped(); continue; }
		for (const entry of entries) {
			signal?.throwIfAborted();
			const file = path.join(current.dir, entry.name);
			if (entry.isDirectory()) {
				if (config.source === "codex" || current.depth === 0) {
					pending.push({ dir: file, depth: current.depth + 1,
						cwd: config.source === "pi" ? decodeSessionDirName(entry.name) : "" });
				}
				continue;
			}
			if (!entry.name.endsWith(".jsonl") || (config.source === "pi" && current.depth !== 1)) continue;
			try {
				const resolved = await realpath(file);
				if (!contained(resolvedRoot, resolved)) { skipped(); continue; }
				if (!(await stat(resolved)).isFile()) { skipped(); continue; }
				yield { file, cwd: current.cwd };
			} catch { skipped(); }
		}
	}
}

interface SessionHeader {
	id: string;
	cwd: string;
	timestamp: string;
	base?: unknown;
	historyMode?: unknown;
}

function object(value: unknown): Record<string, unknown> | undefined {
	return value !== null && typeof value === "object" && !Array.isArray(value)
		? value as Record<string, unknown> : undefined;
}

function sessionHeader(record: unknown, source: SessionSource): SessionHeader | undefined {
	const obj = object(record);
	const header = source === "pi" ? (obj?.type === "session" ? obj : undefined)
		: obj?.type === "session_meta" ? object(obj.payload) : undefined;
	if (!header || typeof header.id !== "string" || !header.id) return;
	return { id: header.id, cwd: typeof header.cwd === "string" ? header.cwd : "",
		timestamp: typeof header.timestamp === "string" ? header.timestamp : "", historyMode: header.history_mode,
		...(header.history_base != null ? { base: header.history_base } : {}) };
}

async function firstHeader(file: string, source: SessionSource, cap: number, signal?: AbortSignal): Promise<SessionHeader | undefined> {
	const info = await stat(file);
	if (!info.isFile()) return;
	for await (const line of sessionRecords(file, info.size, cap, signal)) {
		return sessionHeader(line === null ? undefined : parseRecord(line), source);
	}
}

// Normalize only conversation items. Event records duplicate response items;
// developer instructions, reasoning and tool results are not conversation text.
function conversationRecord(record: unknown, source: SessionSource): Record<string, unknown> | undefined {
	const obj = object(record);
	if (!obj) return;
	if (source === "pi") return obj.type === "message" ? obj : undefined;
	if (obj.type !== "response_item") return;
	const payload = object(obj.payload);
	if (!payload) return;
	let message: { role: string; content: unknown };
	if (payload.type === "message" && (payload.role === "user" || payload.role === "assistant")) {
		const kinds = object(payload.internal_chat_message_metadata_passthrough)?.content_item_kinds;
		const content = Array.isArray(payload.content) ? payload.content : [];
		const classified = Array.isArray(kinds) && kinds.length === content.length && kinds.every(k => typeof k === "string");
		message = { role: payload.role, content: content.flatMap((part: unknown, i: number) => {
			const block = object(part);
			if (!block || (block.type !== "input_text" && block.type !== "output_text") || typeof block.text !== "string") return [];
			if (payload.role === "user" && classified && kinds[i] && kinds[i] !== "unknown" && !kinds[i].startsWith("user.")) return [];
			return [{ type: "text", text: block.text }];
		}) };
	} else if ((payload.type === "function_call" || payload.type === "custom_tool_call") && typeof payload.name === "string") {
		message = { role: "assistant", content: [{ type: "toolCall", name: payload.name,
			arguments: payload.type === "function_call" ? payload.arguments : payload.input }] };
	} else return;
	return { type: "message", id: payload.id, timestamp: obj.timestamp, message };
}

export async function searchSessions(opts: SearchOptions): Promise<SearchResult> {
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
	const retainedCopies = new Map<string, string>();

	try {
		outer: for (const config of sessionRoots()) {
			for await (const candidate of sessionCandidates(config, opts.signal, () => { skippedFiles += 1; })) {
				if (opts.signal?.aborted) break outer;
				const full = candidate.file;
				if (config.source === "pi" && opts.cwd && !candidate.cwd.includes(opts.cwd) &&
					!path.basename(path.dirname(full)).includes(opts.cwd)) continue;
				try {
					const info = await stat(full);
					let header: SessionHeader | undefined;
					let startMs: number;
					if (config.source === "codex") {
						header = await firstHeader(full, config.source, maxRecordBytes, opts.signal);
						if (!header) { skippedFiles += 1; continue; }
						startMs = Date.parse(header.timestamp);
						if (!Number.isFinite(startMs)) { skippedFiles += 1; continue; }
						if (opts.cwd && !header.cwd.includes(opts.cwd)) continue;
					} else startMs = parseSessionFileTimestamp(path.basename(full)) || info.mtimeMs;
					if (sinceMs && startMs < sinceMs) continue;
					if (untilMs && startMs > untilMs) continue;
					let sessionId = header?.id ?? "";
					let headerCwd = header?.cwd || candidate.cwd;
					if (opts.excludeSessionId && sessionId === opts.excludeSessionId) continue;
					scannedFiles += 1;
					let fileHits = 0;
					records: for await (const line of sessionRecords(full, info.size, maxRecordBytes, opts.signal)) {
						if (line === null) { skippedRecords += 1; continue; }
						if (!line) continue;
						const record = parseRecord(line);
						const h = sessionHeader(record, config.source);
						if (h) {
							sessionId = h.id;
							if (h.cwd) headerCwd = h.cwd;
							if (opts.excludeSessionId && sessionId === opts.excludeSessionId) break;
							continue;
						}
						const obj = conversationRecord(record, config.source);
						const msg = object(obj?.message);
						if (!obj || !msg) continue;
						const role = msg.role;
						if (roleFilter !== "any" && role !== roleFilter) continue;
						if (role !== "user" && role !== "assistant") continue;
						if (config.source === "pi" && role === "user" && isGoalContinuation(msg.content)) {
							excludedGoalContinuations += 1;
							continue;
						}
						const haystacks: Array<{ kind: string; text: string }> = [];
						const text = extractText(msg.content);
						if (text) haystacks.push({ kind: role, text });
						if (opts.includeToolCalls && role === "assistant") {
							const tools = extractToolCallText(msg.content);
							if (tools) haystacks.push({ kind: "toolCall", text: tools });
						}
						for (const h of haystacks) {
							const haystack = h.text.slice(0, MAX_HAYSTACK_BYTES);
							const match = haystack.match(re);
							if (!match) continue;
							const identityMessage = config.source === "codex" ? object(object(record)?.payload)! : msg;
							const fingerprint = copiedHitFingerprint(obj.id, obj.timestamp, identityMessage, h.kind);
							const identity = fingerprint && `${config.source}:${fingerprint}`;
							if (identity) {
								const previous = retainedCopies.get(identity);
								if (previous !== undefined && previous !== full) { duplicateHitsSuppressed += 1; continue; }
								retainedCopies.set(identity, full);
							}
							const idx = match.index ?? 0;
							hits.push({ sessionFile: config.source === "codex" ? path.resolve(full) : path.relative(config.root, full) || full,
								...(config.source === "codex" ? { source: "codex" as const } : {}), sessionId,
								...(typeof obj.id === "string" && obj.id ? { entryId: obj.id } : {}),
								sessionCwd: headerCwd, timestamp: String(obj.timestamp ?? ""), role: h.kind,
								snippet: haystack.slice(Math.max(0, idx - before), idx + after).trim() });
							fileHits += 1;
							const atSessionLimit = fileHits === perSessionMax;
							if (atSessionLimit) sessionsAtLimit += 1;
							if (hits.length >= max) { truncated = true; break outer; }
							if (atSessionLimit) break records;
						}
					}
				} catch {
					if (opts.signal?.aborted) break outer;
					skippedFiles += 1;
				}
			}
		}
	} catch (error) {
		if (!opts.signal?.aborted) throw error;
	}
	hits.sort((a, b) => (Date.parse(b.timestamp) || 0) - (Date.parse(a.timestamp) || 0));
	return { hits, scannedFiles, skippedFiles, truncated, sessionsAtLimit, skippedRecords, excludedGoalContinuations,
		duplicateHitsSuppressed, incompleteCoverage: skippedRecords > 0 || skippedFiles > 0 || !!opts.signal?.aborted };
}

type ReadMessageOrigin = { role: "user" | "assistant" } | { role: "custom"; customType: string };

type WindowEntry = ReadMessageOrigin & {
	ts: number;
	timestamp: string;
	entryId?: string;
	text: string;
};

function windowEntry(record: unknown, source: SessionSource = "pi"): WindowEntry | undefined {
	const raw = object(record);
	const custom = source === "pi" && raw?.type === "custom_message";
	const obj = custom ? raw : conversationRecord(record, source);
	if (!obj) return;
	const msg = custom ? obj : object(obj.message);
	if (!msg) return;
	let origin: ReadMessageOrigin;
	if (custom) {
		if (typeof msg.customType !== "string") return;
		origin = { role: "custom", customType: msg.customType };
	} else {
		if (msg.role !== "user" && msg.role !== "assistant") return;
		origin = { role: msg.role };
	}
	const text = extractText(msg.content);
	const tools = origin.role === "assistant" ? extractToolCallText(msg.content) : "";
	const combined = [text, tools].filter(Boolean).join("\n");
	if (!combined) return;
	return { ts: Date.parse(String(obj.timestamp ?? "")) || 0,
		timestamp: String(obj.timestamp ?? ""),
		...(typeof obj.id === "string" && obj.id ? { entryId: obj.id } : {}),
		...origin, text: combined };
}

function parseRecord(line: string): unknown {
	try {
		return JSON.parse(line);
	} catch {
		return undefined;
	}
}

export interface SessionVersion {
	index: number;
	source: SessionSource;
	sessionFile: string;
	sessionId: string;
	timestamp: string;
	sessionCwd: string;
	preview: string;
}

interface SelectedSession {
	config: SessionRoot;
	file: string;
	header?: SessionHeader;
}

async function resolveSession(opts: ReadSessionOptions, cap: number): Promise<SelectedSession | SessionVersion[]> {
	const roots = sessionRoots();
	if (opts.sessionFile !== undefined) {
		const candidate = path.isAbsolute(opts.sessionFile) ? opts.sessionFile : path.join(getRoot(), opts.sessionFile);
		let file: string;
		try { file = await realpath(candidate); }
		catch { file = path.resolve(candidate); }
		const permitted: SessionRoot[] = [];
		for (const config of roots) {
			let root: string;
			try { root = await realpath(config.root); }
			catch { root = path.resolve(config.root); }
			if (contained(root, file)) permitted.push({ ...config, root });
		}
		if (!permitted.length) throw new Error("Refusing to read outside session roots configured for Pi and Codex.");
		permitted.sort((a, b) => b.root.length - a.root.length);
		// Roots may overlap. Header format, not the first matching path prefix,
		// selects the decoder when both roots authorize this file.
		if (permitted.length > 1) {
			for (const config of permitted) {
				const header = await firstHeader(file, config.source, cap, opts.signal);
				if (header) return { config, file, header };
			}
		}
		return { config: permitted[0], file };
	}
	const matches: SelectedSession[] = [];
	const seen = new Set<string>();
	for (const config of roots) {
		for await (const candidate of sessionCandidates(config, opts.signal)) {
			opts.signal?.throwIfAborted();
			let file: string;
			let header: SessionHeader | undefined;
			try {
				file = await realpath(candidate.file);
				if (seen.has(file)) continue;
				header = await firstHeader(file, config.source, cap, opts.signal);
				if (header) seen.add(file);
			} catch (error) {
				if (opts.signal?.aborted) throw error;
				continue;
			}
			if (header?.id === opts.sessionId) matches.push({ config, file, header });
		}
	}
	opts.signal?.throwIfAborted();
	if (!matches.length) throw new Error(`No readable session with ID "${opts.sessionId}" under the configured session roots.`);
	if (matches.length === 1) {
		const match = matches[0];
		return { ...match, config: { ...match.config, root: await realpath(match.config.root) } };
	}
	if (matches.every(m => m.config.source === "pi")) {
		throw new Error(`Multiple session files have ID "${opts.sessionId}"; use sessionFile instead.`);
	}
	// An ID names a thread, not one immutable Codex history. Show choices rather
	// than guessing the active version or combining reverted conversations.
	matches.sort((a, b) => (Date.parse(b.header!.timestamp) || 0) - (Date.parse(a.header!.timestamp) || 0) || a.file.localeCompare(b.file));
	const versions: SessionVersion[] = [];
	for (const [i, match] of matches.entries()) {
		let preview = "";
		const size = (await stat(match.file)).size;
		for await (const line of sessionRecords(match.file, size, cap, opts.signal)) {
			const entry = line === null ? undefined : windowEntry(parseRecord(line), match.config.source);
			if (!entry || entry.role !== "user") continue;
			preview = entry.text.slice(0, 240).replace(/\s+/g, " ");
			break;
		}
		versions.push({ index: i + 1, source: match.config.source, sessionFile: match.file,
			sessionId: match.header!.id, timestamp: match.header!.timestamp,
			sessionCwd: match.header!.cwd, preview });
	}
	return versions;
}

interface HistorySegment {
	file: string;
	relativeFile: string;
	handle: FileHandle;
	identity: { dev: string; ino: string; birth: number };
	size: number;
	limit: number;
	header?: SessionHeader;
	safeEnd: number;
	ordinalEnd?: number;
}

interface HistoryBase { thread_id: string; end_ordinal_exclusive: number; end_byte_offset: number }

function historyBase(value: unknown): HistoryBase {
	const base = object(value);
	if (!base || typeof base.thread_id !== "string" || !base.thread_id ||
		!Number.isSafeInteger(base.end_ordinal_exclusive) || (base.end_ordinal_exclusive as number) < 1 ||
		!Number.isSafeInteger(base.end_byte_offset) || (base.end_byte_offset as number) < 0) {
		throw new Error("Invalid Codex history_base reference.");
	}
	return base as unknown as HistoryBase;
}

// Codex's canonical basename is the serialized rollout identity. Header IDs
// identify threads and remain unchanged on revert. Never use the basename as
// the authoritative thread ID.
function rolloutId(file: string): string | undefined {
	const match = path.basename(file).match(/^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-([0-9a-f-]{36})(?:_([0-9a-f-]{36}))?\.jsonl$/i);
	return match?.[2] ?? match?.[1];
}

async function openHistory(selected: SelectedSession, cap: number, signal?: AbortSignal): Promise<HistorySegment[]> {
	const segments: HistorySegment[] = [];
	const seen = new Set<string>();
	const config = selected.config;
	let file = selected.file;
	let base: HistoryBase | undefined;
	try {
		while (true) {
			signal?.throwIfAborted();
			file = await realpath(file);
			if (!contained(config.root, file)) throw new Error("Refusing Codex history outside configured session root.");
			if (seen.has(file)) throw new Error("Cyclic Codex history_base reference.");
			seen.add(file);
			if (!(await stat(file)).isFile()) throw new Error("Session path is not a regular file.");
			const handle = await open(file, "r");
			let st;
			try { st = await handle.stat(); }
			catch (error) { await handle.close(); throw error; }
			const segment: HistorySegment = { file, relativeFile: path.relative(config.root, file), handle,
				identity: { dev: String(st.dev), ino: String(st.ino), birth: st.birthtimeMs },
				size: st.size, limit: base?.end_byte_offset ?? st.size, safeEnd: 0, ordinalEnd: base?.end_ordinal_exclusive };
			segments.unshift(segment);
			if (!st.isFile()) throw new Error("Session path is not a regular file.");
			if (segment.limit > st.size) throw new Error("Codex history prefix is truncated.");
			let finalEnd = 0;
			let first = true;
			for await (const item of positionedRecords(file, segment.limit, cap, signal, handle)) {
				const record = item.line === null ? undefined : parseRecord(item.line);
				if (first) { segment.header = sessionHeader(record, config.source); first = false; }
				if (base) {
					if (!item.terminated) throw new Error("Invalid Codex inherited history byte boundary.");
					finalEnd = item.end;
				} else break;
			}
			if (config.source === "codex" && !segment.header) throw new Error("Missing or oversized Codex session metadata.");
			if (base && finalEnd !== base.end_byte_offset) throw new Error("Invalid Codex inherited history byte boundary.");
			if ((base || segment.header?.base !== undefined) && segment.header?.historyMode !== "paginated") {
				throw new Error("Codex history ancestors must declare paginated history mode.");
			}
			if (config.source !== "codex" || segment.header?.base === undefined) break;
			base = historyBase(segment.header.base);
			let match: string | undefined;
			for await (const candidate of sessionCandidates(config, signal)) {
				if (rolloutId(candidate.file) !== base.thread_id) continue;
				const resolved = await realpath(candidate.file);
				if (match && match !== resolved) throw new Error(`Ambiguous Codex history reference: ${base.thread_id}`);
				match = resolved;
			}
			if (!match) throw new Error(`Missing Codex history reference: ${base.thread_id}`);
			file = match;
		}
		return segments;
	} catch (error) {
		await Promise.all(segments.map(s => s.handle.close()));
		throw error;
	}
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

export type ReadSessionMessage = ReadMessageOrigin & {
	/** 1-based eligible position in the selected history, not timestamp order. */
	index: number;
	entryId?: string;
	timestamp: string;
};

export interface ReadSessionResult {
	text: string;
	/** Resolved absolute realpath of the selected transcript; absent for version lists. */
	sessionFile?: string;
	messages: ReadSessionMessage[];
	nextCursor?: string;
	hasMore: boolean;
	skippedRecords: number;
	/** Present instead of a transcript when a Codex thread ID has several versions. */
	versions?: SessionVersion[];
}

interface ReadCursor {
	/** v1 counted only user/assistant messages; v3 also counts Pi custom messages. */
	v: 1 | 3;
	file: string;
	dev: string;
	ino: string;
	birth: number;
	offset: number;
	index: number;
	hash: string;
	cap: number;
}

interface CodexReadCursor extends Omit<ReadCursor, "v"> {
	v: 2;
	at: string;
}

type SessionCursor = ReadCursor | CodexReadCursor;

function cursorPath(value: unknown): value is string {
	return typeof value === "string" && value.length > 0 && value.length <= 8192 &&
		!path.isAbsolute(value) && !value.split(path.sep).some(p => !p || p === "." || p === "..");
}

function decodeCursor(raw: string): SessionCursor {
	// Bound before decoding/JSON parsing; opaque cursors never supply read paths.
	if (raw.length > 32768 || !/^[A-Za-z0-9_-]+$/.test(raw)) throw new Error("Invalid read_session cursor.");
	let value: unknown;
	try { value = JSON.parse(Buffer.from(raw, "base64url").toString("utf8")); }
	catch { throw new Error("Invalid read_session cursor."); }
	if (!value || typeof value !== "object") throw new Error("Invalid read_session cursor.");
	const c = value as SessionCursor;
	if ((c.v !== 1 && c.v !== 2 && c.v !== 3) || !cursorPath(c.file) || (c.v === 2 && !cursorPath(c.at)) ||
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

function historyEntry(record: unknown, source: SessionSource, segment: HistorySegment): WindowEntry | undefined {
	const entry = windowEntry(record, source);
	if (!entry || source !== "codex" || segment.header?.historyMode !== "paginated") return entry;
	const ordinal = object(record)?.ordinal;
	if (typeof ordinal !== "number" || !Number.isSafeInteger(ordinal) || ordinal < 0) {
		throw new Error("Invalid Codex paginated message ordinal.");
	}
	const start = segment.header.base === undefined ? 1 : historyBase(segment.header.base).end_ordinal_exclusive + 1;
	if (ordinal < start || (segment.ordinalEnd !== undefined && ordinal >= segment.ordinalEnd)) return;
	return entry;
}

// Hash only the committed logical prefix. The manifest binds each consumed
// range to its physical file; bytes after an inherited cutoff are not consumed.
// Keep the cursor constant-size even when a history has many ancestors.
async function historyPrefixHash(
	segments: HistorySegment[], at: number, offset: number, signal?: AbortSignal,
): Promise<string> {
	const hash = createHash("sha256");
	for (let i = 0; i <= at; i += 1) {
		const segment = segments[i];
		const end = i === at ? offset : segment.limit;
		hash.update(JSON.stringify([segment.relativeFile, segment.identity, end]) + "\n");
		for await (const bytes of snapshotChunks(segment.handle, end, signal)) hash.update(bytes);
	}
	return hash.digest("hex");
}

/** Read a bounded snapshot of the selected version's logical conversation. */
export async function readSession(opts: ReadSessionOptions): Promise<ReadSessionResult> {
	const maxRecordBytes = getMaxBytes();
	const ctx = opts.contextMessages ?? 6;
	const max = opts.maxMessages ?? 30;
	if (!Number.isSafeInteger(ctx) || ctx < 0) throw new Error("contextMessages must be a non-negative safe integer.");
	if (!Number.isSafeInteger(max) || max < 0) throw new Error("maxMessages must be a non-negative safe integer.");
	opts.signal?.throwIfAborted();
	if ((opts.sessionFile !== undefined) === (opts.sessionId !== undefined)) throw new Error("Provide exactly one of sessionFile or sessionId.");
	const selector = opts.sessionFile ?? opts.sessionId;
	if (typeof selector !== "string" || !selector.trim()) throw new Error("sessionFile or sessionId must be a non-empty string.");
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
	const selected = await resolveSession(opts, maxRecordBytes);
	if (Array.isArray(selected)) {
		const lines = [`# Session ${opts.sessionId}: ${selected.length} versions`,
			"Choose a sessionFile below and call read_session again; these histories are not concatenated.", ""];
		for (const version of selected) {
			lines.push(`${version.index}. ${version.timestamp} — cwd: ${version.sessionCwd}`,
				`   sessionFile: ${JSON.stringify(version.sessionFile)}`, `   ${version.preview || "(no local user message)"}`, "");
		}
		return { text: lines.join("\n"), versions: selected, messages: [], hasMore: false, skippedRecords: 0 };
	}
	const source = selected.config.source;
	const segments = await openHistory(selected, maxRecordBytes, opts.signal);
	try {
		const last = segments[segments.length - 1];
		const previousAt = previous ? (previous.v === 2
			? segments.findIndex(s => s.relativeFile === previous.at) : 0) : 0;
		if (previous) {
			if (previous.file !== last.relativeFile || previous.dev !== last.identity.dev || previous.ino !== last.identity.ino ||
				previous.birth !== last.identity.birth || previous.cap !== maxRecordBytes ||
				(source === "codex" ? previous.v !== 2 : previous.v === 2) || previousAt < 0 ||
				previous.offset > segments[previousAt].limit) {
				throw new Error("Stale read_session cursor: file identity or history changed.");
			}
			const hash = source === "pi" ? await prefixHash(last.handle, previous.offset, opts.signal)
				: await historyPrefixHash(segments, previousAt, previous.offset, opts.signal);
			if (hash !== previous.hash) throw new Error("Stale read_session cursor: committed prefix changed.");
		}

		let total = 0;
		let ordinaryTotal = 0;
		let previousIndex = previous?.index ?? 0;
		let skippedRecords = 0;
		let nearest = 0;
		let anchorFound = false;
		let bestDiff = Infinity;
		let previousBoundaryFound = !previous;
		for (const [segmentIndex, segment] of segments.entries()) {
			if (previous && segmentIndex === previousAt && previous.offset === 0) previousBoundaryFound = total === previous.index;
			for await (const item of positionedRecords(segment.file, segment.limit, maxRecordBytes, opts.signal, segment.handle)) {
				const record = item.line === null ? undefined : parseRecord(item.line);
				if (item.line === null) skippedRecords += 1;
				if (!item.terminated && (item.line === null || record === undefined)) break;
				segment.safeEnd = item.end;
				const entry = historyEntry(record, source, segment);
				if (entry) {
					const diff = Math.abs(entry.ts - target);
					if (diff < bestDiff) { bestDiff = diff; nearest = total; }
					if (opts.aroundEntryId !== undefined && entry.entryId === opts.aroundEntryId && !anchorFound) {
						nearest = total; anchorFound = true;
					}
					total += 1;
					if (entry.role !== "custom") ordinaryTotal += 1;
				}
				if (previous && segmentIndex === previousAt) {
					// Validate old receipts in their original count, then translate the
					// position without moving the committed byte boundary.
					const committedCount = previous.v === 1 ? ordinaryTotal : total;
					if (item.end === previous.offset) {
						previousBoundaryFound = committedCount === previous.index;
						previousIndex = total;
					} else if (item.start < previous.offset && previous.offset < item.end &&
						item.line !== null && record !== undefined && committedCount === previous.index) {
						// A complete final JSON record may later acquire its LF.
						const prefix = Buffer.from(item.line).subarray(0, previous.offset - item.start).toString("utf8");
						previousBoundaryFound = parseRecord(prefix) !== undefined;
						previousIndex = total;
					}
				}
			}
		}
		if (previous && !previousBoundaryFound) throw new Error("Stale read_session cursor: committed record boundary changed.");
		if (opts.aroundEntryId !== undefined && !anchorFound) throw new Error(`No eligible message with entry ID "${opts.aroundEntryId}".`);

		let startIdx = previousIndex;
		let endIdx = Math.min(total, startIdx + max);
		if (opts.tail) { startIdx = Math.max(0, total - max); endIdx = total; }
		else if ((Number.isFinite(target) || opts.aroundEntryId !== undefined) && total) {
			const lower = Math.max(0, nearest - ctx);
			const upper = Math.min(total, nearest + Math.min(ctx, total - nearest - 1) + 1);
			const count = Math.min(max, upper - lower);
			startIdx = Math.max(lower, nearest - Math.ceil(Math.max(0, count - 1) / 2));
			endIdx = Math.min(upper, startIdx + count);
			startIdx = Math.max(lower, endIdx - count);
			if (endIdx - startIdx < count) endIdx = Math.min(upper, startIdx + count);
		}
		const entries: Array<{ entry: WindowEntry; index: number }> = [];
		let cursorOffset = previous?.offset ?? 0;
		let cursorIndex = previousIndex;
		let cursorAt = previousAt;
		if (endIdx > startIdx) {
			let index = 0;
			window: for (const [segmentIndex, segment] of segments.entries()) {
				for await (const item of positionedRecords(segment.file, segment.safeEnd, maxRecordBytes, opts.signal, segment.handle)) {
					const entry = item.line === null ? undefined : historyEntry(parseRecord(item.line), source, segment);
					if (!entry) continue;
					if (index >= startIdx) {
						entries.push({ entry, index: index + 1 });
						cursorAt = segmentIndex; cursorOffset = item.end; cursorIndex = index + 1;
					}
					index += 1;
					if (index >= endIdx) break window;
				}
			}
		}
		if (opts.tail || (max > 0 && cursorIndex === total)) {
			cursorAt = segments.length - 1; cursorOffset = last.safeEnd; cursorIndex = total;
		}
		const common = { file: last.relativeFile, ...last.identity, offset: cursorOffset, index: cursorIndex, cap: maxRecordBytes };
		const cursor: SessionCursor = source === "pi"
			? { v: 3, ...common, hash: await prefixHash(last.handle, cursorOffset, opts.signal) }
			: { v: 2, ...common, at: segments[cursorAt].relativeFile,
				hash: await historyPrefixHash(segments, cursorAt, cursorOffset, opts.signal) };
		const nextCursor = Buffer.from(JSON.stringify(cursor)).toString("base64url");
		const messages: ReadSessionMessage[] = entries.map(({ entry, index }) => {
			const origin: ReadMessageOrigin = entry.role === "custom"
				? { role: entry.role, customType: entry.customType } : { role: entry.role };
			return { index, ...(entry.entryId === undefined ? {} : { entryId: entry.entryId }), ...origin, timestamp: entry.timestamp };
		});
		const hasMore = cursorIndex < total;
		const out: string[] = [];
		if (last.header) out.push(`# Session ${last.header.id} — cwd: ${last.header.cwd} — started: ${last.header.timestamp}`);
		out.push(`# Showing messages ${startIdx + 1}–${endIdx} of ${total}`);
		if (skippedRecords) out.push(`# Incomplete coverage: skipped ${skippedRecords} oversized record${skippedRecords === 1 ? "" : "s"}.`);
		out.push("");
		for (const { entry, index } of entries) {
			const label = entry.role === "custom" ? `custom ${JSON.stringify(entry.customType)}` : entry.role;
			out.push(`## ${label} @ ${new Date(entry.ts).toISOString()} — message ${index}${entry.entryId === undefined ? "" : ` — entryId: ${JSON.stringify(entry.entryId)}`}`);
			out.push(entry.text, "");
		}
		out.push(`# Navigation ${JSON.stringify({ nextCursor, hasMore, skippedRecords })}`);
		return { text: out.join("\n"), sessionFile: last.file, messages, nextCursor, hasMore, skippedRecords };
	} finally {
		await Promise.all(segments.map(s => s.handle.close()));
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
		label: "Search prior Pi and Codex sessions",
		description:
			"Search prior Pi and Codex session transcripts without resuming them. Use for prior discussions or decisions. Searches retained Codex versions, excludes classified injected Codex context and whole Pi goal-continuation envelopes, and collapses recorded copies within each source. Read-only.",
		promptSnippet: "Find prior Pi and Codex sessions matching a query.",
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
				Type.String({ description: "ISO date/time; ignore sessions started before this (Pi filename timestamp; Codex metadata timestamp)." }),
			),
			until: Type.Optional(
				Type.String({ description: "ISO date/time; ignore sessions started after this (Pi filename timestamp; Codex metadata timestamp)." }),
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
		label: "Read a prior Pi or Codex session",
		description:
			"Read prior Pi or Codex session messages: start, tail, continuation, or centered context. A Codex file selects that version and reconstructs its inherited history. An ambiguous Codex sessionId returns an indexed version list with previews and sessionFile paths, not full transcripts or a tool error. Read-only.",
		promptSnippet: "Read prior Pi or Codex history by file or session ID; list versions when a Codex ID is ambiguous.",
		promptGuidelines: [
			"Use read_session with the returned sessionFile unchanged and a modest maxMessages.",
		],
		parameters: Type.Object({
			sessionFile: Type.Optional(Type.String({
				description: "Path to a session .jsonl file, as returned by search_sessions or a version list. Pi paths may be relative to the Pi root; Codex paths are absolute and select one version. Provide exactly one of sessionFile or sessionId.",
			})),
			sessionId: Type.Optional(Type.String({
				description: "Exact session header ID, resolved within configured Pi and Codex roots. Multiple Codex versions return an indexed preview list; choose a returned sessionFile to read one. Use when a parent session path comes from another machine or sandbox. Provide exactly one of sessionFile or sessionId.",
			})),
			tail: Type.Optional(Type.Boolean({
				description: "Return the last maxMessages eligible messages in file order. With maxMessages=0, select the safe EOF cursor. Default false.",
			})),
			after: Type.Optional(Type.String({
				description: "Opaque nextCursor from an earlier transcript read. Continue the same file/version after its committed boundary; safe across appends, errors if consumed history changed or a file was replaced. Transcript reads return cursors even when empty; version lists do not. hasMore covers only the initial snapshot. Mutually exclusive with tail=true and centered modes.",
			})),
			aroundEntryId: Type.Optional(Type.String({
				description: "Exact entry ID, including Pi custom-message IDs; center on the first eligible occurrence in file order. Errors if missing. Mutually exclusive with other selection modes.",
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
			"Search past Pi and Codex sessions. Usage: /find-sessions [--cwd=substr] [--role=user|assistant] [--since=ISO] [--until=ISO] [--max=N] <query>",
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
