#!/usr/bin/env node
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

import { readFileSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
	readSession,
	searchSessions,
	type ReadSessionOptions,
	type SearchOptions,
} from "./index.ts";

const PROGRAM = "pi-session-search";

const TOP_HELP = `Usage:
  ${PROGRAM} search [options] <query>
  ${PROGRAM} read (--file <path> | --id <session-id>) [options]

Commands:
  search  Search prior Pi and Codex sessions
  read    Read a prior Pi or Codex session

Options:
  --help     Show help
  --version  Show the package version
`;

const SEARCH_HELP = `Usage:
  ${PROGRAM} search [options] <query>

Options:
  --cwd <substring>
  --since <ISO date/time>
  --until <ISO date/time>
  --role <user|assistant|any>
  --include-tool-calls
  --max-results <1..1000>
  --max-results-per-session <1..1000>
  --exclude-session-id <session-id>
  --help
`;

const READ_HELP = `Usage:
  ${PROGRAM} read (--file <path> | --id <session-id>) [options]

Options:
  --file <path>
  --id <session-id>
  --tail
  --after <cursor>
  --around-entry-id <entry-id>
  --around-timestamp <ISO date/time>
  --context-messages <non-negative integer>
  --max-messages <non-negative integer>
  --help
`;

class UsageError extends Error {}

interface ParsedOptions {
	flags: Map<string, string | true>;
	positionals: string[];
}

function parseOptions(args: string[], valueOptions: Set<string>, booleanOptions: Set<string>): ParsedOptions {
	const flags = new Map<string, string | true>();
	const positionals: string[] = [];
	let positionalOnly = false;
	for (let index = 0; index < args.length; index += 1) {
		const arg = args[index];
		if (positionalOnly || !arg.startsWith("--")) {
			positionals.push(arg);
			continue;
		}
		if (arg === "--") {
			positionalOnly = true;
			continue;
		}
		if (arg.includes("=")) throw new UsageError(`unknown option syntax: ${arg}`);
		if (flags.has(arg)) throw new UsageError(`option may be provided only once: ${arg}`);
		if (booleanOptions.has(arg)) {
			flags.set(arg, true);
			continue;
		}
		if (!valueOptions.has(arg)) throw new UsageError(`unknown option: ${arg}`);
		const value = args[++index];
		if (value === undefined) throw new UsageError(`missing value for ${arg}`);
		flags.set(arg, value);
	}
	return { flags, positionals };
}

function option(flags: Map<string, string | true>, name: string): string | undefined {
	const value = flags.get(name);
	return typeof value === "string" ? value : undefined;
}

function integerOption(flags: Map<string, string | true>, name: string): number | undefined {
	const value = option(flags, name);
	if (value === undefined) return undefined;
	if (!/^(?:0|[1-9]\d*)$/.test(value)) throw new UsageError(`${name} requires a non-negative integer`);
	const parsed = Number(value);
	if (!Number.isSafeInteger(parsed)) throw new UsageError(`${name} requires a safe integer`);
	return parsed;
}

function parseSearch(args: string[]): SearchOptions | "help" {
	const parsed = parseOptions(
		args,
		new Set([
			"--cwd", "--since", "--until", "--role", "--max-results",
			"--max-results-per-session", "--exclude-session-id",
		]),
		new Set(["--include-tool-calls", "--help"]),
	);
	if (parsed.flags.has("--help")) return "help";
	if (parsed.positionals.length !== 1 || !parsed.positionals[0]) {
		throw new UsageError("search requires exactly one query argument");
	}
	const role = option(parsed.flags, "--role");
	if (role !== undefined && role !== "user" && role !== "assistant" && role !== "any") {
		throw new UsageError("--role must be user, assistant, or any");
	}
	return {
		query: parsed.positionals[0],
		cwd: option(parsed.flags, "--cwd"),
		since: option(parsed.flags, "--since"),
		until: option(parsed.flags, "--until"),
		role,
		includeToolCalls: parsed.flags.has("--include-tool-calls") || undefined,
		maxResults: integerOption(parsed.flags, "--max-results"),
		maxResultsPerSession: integerOption(parsed.flags, "--max-results-per-session"),
		excludeSessionId: option(parsed.flags, "--exclude-session-id"),
	};
}

function parseRead(args: string[]): ReadSessionOptions | "help" {
	const parsed = parseOptions(
		args,
		new Set([
			"--file", "--id", "--after", "--around-entry-id", "--around-timestamp",
			"--context-messages", "--max-messages",
		]),
		new Set(["--tail", "--help"]),
	);
	if (parsed.flags.has("--help")) return "help";
	if (parsed.positionals.length) throw new UsageError("read does not accept positional arguments");
	const sessionFile = option(parsed.flags, "--file");
	const sessionId = option(parsed.flags, "--id");
	if (Boolean(sessionFile) === Boolean(sessionId)) {
		throw new UsageError("read requires exactly one of --file or --id");
	}
	return {
		sessionFile,
		sessionId,
		tail: parsed.flags.has("--tail") || undefined,
		after: option(parsed.flags, "--after"),
		aroundEntryId: option(parsed.flags, "--around-entry-id"),
		aroundTimestamp: option(parsed.flags, "--around-timestamp"),
		contextMessages: integerOption(parsed.flags, "--context-messages"),
		maxMessages: integerOption(parsed.flags, "--max-messages"),
	};
}

function packageVersion(): string {
	const manifest = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as unknown;
	if (!manifest || typeof manifest !== "object" || !("version" in manifest) ||
		typeof manifest.version !== "string") {
		throw new Error("package.json does not contain a version");
	}
	return manifest.version;
}

interface CliWriter {
	write(value: string): unknown;
}

function writeJsonTo(output: CliWriter, value: unknown): void {
	output.write(JSON.stringify(value, null, 2) + "\n");
}

export async function runCli(
	args: string[],
	stdout: CliWriter,
	stderr: CliWriter,
	signal: AbortSignal,
): Promise<number> {
	try {
		if (!args.length || args[0] === "--help") {
			stdout.write(TOP_HELP);
			return 0;
		}
		if (args[0] === "--version") {
			stdout.write(packageVersion() + "\n");
			return 0;
		}

		const command = args[0];
		if (command !== "search" && command !== "read") throw new UsageError(`unknown command: ${command}`);
		if (command === "search") {
			const parsed = parseSearch(args.slice(1));
			if (parsed === "help") {
				stdout.write(SEARCH_HELP);
				return 0;
			}
			const result = await searchSessions({ ...parsed, signal });
			signal.throwIfAborted();
			writeJsonTo(stdout, result);
		} else {
			const parsed = parseRead(args.slice(1));
			if (parsed === "help") {
				stdout.write(READ_HELP);
				return 0;
			}
			const result = await readSession({ ...parsed, signal });
			signal.throwIfAborted();
			writeJsonTo(stdout, result);
		}
		return 0;
	} catch (error) {
		if (signal.aborted) {
			stderr.write(`${PROGRAM}: cancelled\n`);
			return 130;
		}
		stderr.write(`${PROGRAM}: ${error instanceof Error ? error.message : String(error)}\n`);
		return error instanceof UsageError ? 2 : 1;
	}
}

function isDirectInvocation(): boolean {
	if (!process.argv[1]) return false;
	try {
		return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
	} catch {
		return false;
	}
}

if (isDirectInvocation()) {
	const controller = new AbortController();
	const cancel = () => controller.abort();
	process.once("SIGINT", cancel);
	try {
		process.exitCode = await runCli(process.argv.slice(2), process.stdout, process.stderr, controller.signal);
	} finally {
		process.removeListener("SIGINT", cancel);
	}
}
