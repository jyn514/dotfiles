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

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { Type } from "typebox";
import { readdir, readFile, realpath, stat } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";

const DEFAULT_ROOT = path.join(homedir(), ".pi/agent/sessions");
const DEFAULT_MAX_BYTES = 5 * 1024 * 1024; // 5 MB per session file
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
	const v = Number.parseInt(process.env.PI_SESSION_SEARCH_MAX_BYTES || "", 10);
	return Number.isFinite(v) && v > 0 ? v : DEFAULT_MAX_BYTES;
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
	if (
		typeof raw !== "number" ||
		!Number.isFinite(raw) ||
		!Number.isInteger(raw) ||
		raw < 1 ||
		raw > MAX_RESULTS_HARD_CAP
	) {
		throw new Error(
			`maxResults must be an integer in [1, ${MAX_RESULTS_HARD_CAP}]; got ${String(raw)}`,
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
}

export async function searchSessions(opts: SearchOptions): Promise<SearchResult> {
	const root = getRoot();
	const maxBytes = getMaxBytes();
	const re = compileQuery(opts.query);
	const sinceMs = parseDateOrThrow(opts.since, "since");
	const untilMs = parseDateOrThrow(opts.until, "until");
	const roleFilter = opts.role ?? "any";
	const max = validateMaxResults(opts.maxResults);
	const before = opts.snippetBefore ?? DEFAULT_SNIPPET_BEFORE;
	const after = opts.snippetAfter ?? DEFAULT_SNIPPET_AFTER;

	const hits: Hit[] = [];
	let scannedFiles = 0;
	let skippedFiles = 0;
	let truncated = false;

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
		return { hits, scannedFiles, skippedFiles, truncated };
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
			// sessions root would otherwise be silently followed by readFile()
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
			if (st.size > maxBytes) {
				skippedFiles += 1;
				continue;
			}

			let raw: string;
			try {
				raw = await readFile(resolvedFile, "utf8");
			} catch {
				continue;
			}
			scannedFiles += 1;

			let sessionId = "";
			let headerCwd = sessionCwd;
			for (const line of raw.split("\n")) {
				if (!line) continue;
				let obj: any;
				try {
					obj = JSON.parse(line);
				} catch {
					continue;
				}

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
				const msg = obj.message;
				if (!msg) continue;
				const role = msg.role;
				if (roleFilter !== "any" && role !== roleFilter) continue;
				if (role !== "user" && role !== "assistant") continue;

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
					const idx = m.index ?? 0;
					const snippet = haystack.slice(Math.max(0, idx - before), idx + after).trim();
					hits.push({
						// Display path is the original (non-realpath) location so it round-trips
						// through read_session's relative-path acceptance and matches what the
						// user sees in their sessions directory.
						sessionFile: path.relative(root, full) || full,
						sessionId,
						sessionCwd: headerCwd,
						timestamp: String(obj.timestamp ?? ""),
						role: h.kind,
						snippet,
					});
					if (hits.length >= max) {
						truncated = true;
						break outer;
					}
				}
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
	return { hits, scannedFiles, skippedFiles, truncated };
}

export async function readSessionWindow(opts: {
	sessionFile: string;
	aroundTimestamp?: string;
	contextMessages?: number;
	maxMessages?: number;
}): Promise<string> {
	const input = opts.sessionFile;
	const root = getRoot();
	// Accept either an absolute path or a path relative to the configured
	// sessions root (search_sessions returns the latter).
	const candidate = path.isAbsolute(input) ? input : path.join(root, input);
	// Resolve symlinks on both sides before the prefix check so a symlink placed
	// inside the sessions root cannot point this tool at arbitrary files.
	let resolvedRoot: string;
	let resolvedFile: string;
	try {
		resolvedRoot = await realpath(root);
	} catch {
		resolvedRoot = path.resolve(root);
	}
	try {
		resolvedFile = await realpath(candidate);
	} catch {
		// File doesn't exist or isn't accessible; fall back to lexical resolution
		// so we still produce a clear error below rather than leaking an ENOENT.
		resolvedFile = path.resolve(candidate);
	}
	if (!resolvedFile.startsWith(resolvedRoot + path.sep) && resolvedFile !== resolvedRoot) {
		throw new Error(`Refusing to read outside session root: ${resolvedRoot}`);
	}

	// Stat-then-cap so a pathological multi-GB session file doesn't OOM the
	// pi process. Same MAX_BYTES policy as search_sessions — if the file is
	// too big to be searched it's also too big to be window-read.
	const maxBytes = getMaxBytes();
	let st;
	try {
		st = await stat(resolvedFile);
	} catch (e) {
		throw new Error(`Could not stat session file: ${(e as Error).message}`);
	}
	if (st.size > maxBytes) {
		throw new Error(
			`Refusing to read session file: size ${st.size} exceeds PI_SESSION_SEARCH_MAX_BYTES (${maxBytes}). ` +
				`Raise the env var to read this file (memory permitting), or trim the session manually.`,
		);
	}

	const raw = await readFile(resolvedFile, "utf8");
	const lines = raw.split("\n").filter(Boolean);
	const entries: Array<{ ts: number; role: string; text: string }> = [];
	let header: any = null;

	for (const line of lines) {
		let obj: any;
		try {
			obj = JSON.parse(line);
		} catch {
			continue;
		}
		if (obj.type === "session") {
			header = obj;
			continue;
		}
		if (obj.type !== "message") continue;
		const msg = obj.message;
		const role = msg?.role;
		if (role !== "user" && role !== "assistant") continue;
		const text = extractText(msg?.content);
		const tools = role === "assistant" ? extractToolCallText(msg?.content) : "";
		const combined = [text, tools].filter(Boolean).join("\n");
		if (!combined) continue;
		entries.push({
			ts: Date.parse(String(obj.timestamp ?? "")) || 0,
			role,
			text: combined,
		});
	}

	let startIdx = 0;
	let endIdx = entries.length;
	const ctx = opts.contextMessages ?? 6;
	const max = opts.maxMessages ?? 30;

	if (opts.aroundTimestamp) {
		const target = Date.parse(opts.aroundTimestamp);
		if (Number.isFinite(target)) {
			let nearest = 0;
			let bestDiff = Infinity;
			for (let i = 0; i < entries.length; i++) {
				const diff = Math.abs(entries[i].ts - target);
				if (diff < bestDiff) {
					bestDiff = diff;
					nearest = i;
				}
			}
			startIdx = Math.max(0, nearest - ctx);
			endIdx = Math.min(entries.length, nearest + ctx + 1);
		}
	}

	if (endIdx - startIdx > max) endIdx = startIdx + max;

	const out: string[] = [];
	if (header) {
		out.push(`# Session ${header.id} — cwd: ${header.cwd} — started: ${header.timestamp}`);
	}
	out.push(`# Showing messages ${startIdx + 1}–${endIdx} of ${entries.length}`);
	out.push("");
	for (let i = startIdx; i < endIdx; i++) {
		const e = entries[i];
		out.push(`## ${e.role} @ ${new Date(e.ts).toISOString()}`);
		out.push(e.text);
		out.push("");
	}
	return out.join("\n");
}

export function formatHitsForCommand(result: SearchResult): string {
	if (result.hits.length === 0) {
		return `No matches. (scanned ${result.scannedFiles} files, skipped ${result.skippedFiles})`;
	}
	const lines: string[] = [];
	lines.push(
		`${result.hits.length} hit${result.hits.length === 1 ? "" : "s"}${result.truncated ? " (truncated)" : ""}, scanned ${result.scannedFiles} files:`,
	);
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
			"Search past pi session transcripts (~/.pi/agent/sessions) for a topic. Use when the user asks 'have we discussed X before?', 'what did we decide about Y?', or wants to find a prior session without resuming it. Read-only.",
		promptSnippet: "Find prior pi sessions matching a query.",
		promptGuidelines: [
			"Use search_sessions when the user references prior conversations or asks if a topic was discussed before.",
			"Pass a focused `query` (substring or `/regex/flags`). Narrow with `cwd` if you know which project.",
			"After a promising hit, call read_session with the returned `sessionFile` (and optionally `aroundTimestamp`) to pull more context.",
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
				Type.Boolean({ description: "Also search assistant tool-call names/arguments. Default false." }),
			),
			maxResults: Type.Optional(
				Type.Integer({
					minimum: 1,
					maximum: MAX_RESULTS_HARD_CAP,
					description: `Maximum number of hits to return. Default ${DEFAULT_MAX_RESULTS}, hard cap ${MAX_RESULTS_HARD_CAP}.`,
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
					excludeSessionId,
					signal,
				});
				return {
					content: [
						{
							type: "text",
							text: JSON.stringify(
								{
									count: result.hits.length,
									truncated: result.truncated,
									scannedFiles: result.scannedFiles,
									skippedFiles: result.skippedFiles,
									hits: result.hits,
								},
								null,
								2,
							),
						},
					],
					details: { count: result.hits.length, truncated: result.truncated },
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
			"Read a slice of a prior pi session transcript. Use after search_sessions returns a promising hit to pull surrounding context. Read-only.",
		promptSnippet: "Read a window from a prior pi session JSONL file.",
		promptGuidelines: [
			"Pass `sessionFile` exactly as returned by search_sessions.",
			"If you have a hit's `timestamp`, pass it as `aroundTimestamp` to center the window on it.",
			"Keep `maxMessages` modest — these transcripts can be huge.",
		],
		parameters: Type.Object({
			sessionFile: Type.String({
				description: "Path to a session .jsonl file. Either absolute, or relative to the configured sessions root (as returned by search_sessions).",
			}),
			aroundTimestamp: Type.Optional(
				Type.String({ description: "ISO timestamp to center the window on (e.g. a hit's timestamp)." }),
			),
			contextMessages: Type.Optional(
				Type.Number({ description: "Messages of context on each side of the target. Default 6." }),
			),
			maxMessages: Type.Optional(
				Type.Number({ description: "Hard cap on returned messages. Default 30." }),
			),
		}),
		async execute(_toolCallId, params) {
			try {
				const text = await readSessionWindow({
					sessionFile: String(params.sessionFile),
					aroundTimestamp: params.aroundTimestamp as string | undefined,
					contextMessages: params.contextMessages as number | undefined,
					maxMessages: params.maxMessages as number | undefined,
				});
				return { content: [{ type: "text", text }], details: {} };
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
