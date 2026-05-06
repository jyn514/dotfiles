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

import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import {
	compileQuery,
	decodeSessionDirName,
	extractText,
	extractToolCallText,
	parseDateOrThrow,
	parseFindSessionsArgs,
	parseSessionFileTimestamp,
	validateMaxResults,
} from "../index.ts";

describe("compileQuery", () => {
	it("escapes regex metacharacters in plain substring queries and is case-insensitive", () => {
		const re = compileQuery("a.b+c");
		assert.equal(re.test("a.b+c"), true);
		assert.equal(re.test("AaBbCc"), false);
		assert.equal(re.test("A.B+C"), true, "plain queries should be case-insensitive");
		assert.ok(re.flags.includes("i"));
	});

	it("respects user case-sensitivity in /pattern/flags form", () => {
		const reSensitive = compileQuery("/Foo/");
		assert.equal(reSensitive.test("Foo"), true);
		assert.equal(reSensitive.test("foo"), false, "no implicit `i` should be added");

		const reInsensitive = compileQuery("/Foo/i");
		assert.equal(reInsensitive.test("Foo"), true);
		assert.equal(reInsensitive.test("foo"), true);
	});

	it("strips the `g` flag (which would break .index-based snippets)", () => {
		const re = compileQuery("/foo/gi");
		assert.ok(!re.flags.includes("g"), `g should be stripped, got flags="${re.flags}"`);
		// match() must return an indexed match, not a no-index global array
		const m = "abc foo bar foo baz".match(re);
		assert.ok(m && typeof m.index === "number", "match must have .index");
	});

	it("strips the `y` (sticky) flag", () => {
		const re = compileQuery("/foo/y");
		assert.ok(!re.flags.includes("y"));
	});

	it("preserves `m`, `s`, `u` flags", () => {
		const re = compileQuery("/foo/msu");
		assert.ok(re.flags.includes("m"));
		assert.ok(re.flags.includes("s"));
		assert.ok(re.flags.includes("u"));
	});

	it("throws for an invalid regex", () => {
		assert.throws(() => compileQuery("/(/"), /Invalid query/);
	});
});

describe("validateMaxResults", () => {
	it("returns the default for undefined / null", () => {
		assert.equal(validateMaxResults(undefined), 20);
		assert.equal(validateMaxResults(null), 20);
	});

	it("throws for explicit zero, negative, NaN, Infinity", () => {
		assert.throws(() => validateMaxResults(0), /must be an integer in \[1, 1000\]/);
		assert.throws(() => validateMaxResults(-5), /must be an integer in \[1, 1000\]/);
		assert.throws(() => validateMaxResults(NaN), /must be an integer in/);
		assert.throws(() => validateMaxResults(Infinity), /must be an integer in/);
	});

	it("throws for fractional input (we don't silently floor)", () => {
		assert.throws(() => validateMaxResults(7.9), /must be an integer in/);
	});

	it("throws for above-cap input", () => {
		assert.throws(() => validateMaxResults(1_001), /must be an integer in/);
		assert.throws(() => validateMaxResults(1_000_000), /must be an integer in/);
	});

	it("throws for non-number input", () => {
		assert.throws(() => validateMaxResults("42" as unknown), /must be an integer in/);
	});

	it("returns the integer value within range", () => {
		assert.equal(validateMaxResults(50), 50);
		assert.equal(validateMaxResults(1), 1);
		assert.equal(validateMaxResults(1000), 1000);
	});
});

describe("parseDateOrThrow", () => {
	it("returns 0 for undefined / empty", () => {
		assert.equal(parseDateOrThrow(undefined, "x"), 0);
		assert.equal(parseDateOrThrow("", "x"), 0);
	});

	it("parses ISO-8601 datetimes", () => {
		const t = parseDateOrThrow("2026-04-23T06:48:02.781Z", "since");
		assert.equal(t, Date.parse("2026-04-23T06:48:02.781Z"));
	});

	it("throws for unparseable input", () => {
		assert.throws(() => parseDateOrThrow("not-a-date", "since"), /Invalid since/);
	});
});

describe("decodeSessionDirName", () => {
	it("strips wrapping `--` and converts `-` to `/`", () => {
		assert.equal(decodeSessionDirName("--home-foo-bar--"), "/home/foo/bar");
	});

	it("handles names without wrapping `--` (legacy)", () => {
		assert.equal(decodeSessionDirName("home-foo"), "/home/foo");
	});

	it("returns just `/` for empty input", () => {
		assert.equal(decodeSessionDirName("--"), "/");
	});
});

describe("parseSessionFileTimestamp", () => {
	it("parses the standard pi session filename", () => {
		const t = parseSessionFileTimestamp(
			"2026-04-23T06-48-02-781Z_abc-uuid.jsonl",
		);
		assert.equal(t, Date.parse("2026-04-23T06:48:02.781Z"));
	});

	it("returns 0 for filenames that don't match the prefix pattern", () => {
		assert.equal(parseSessionFileTimestamp("not-a-session.jsonl"), 0);
		assert.equal(parseSessionFileTimestamp("2026.jsonl"), 0);
	});
});

describe("extractText / extractToolCallText", () => {
	it("returns string content unchanged", () => {
		assert.equal(extractText("hello"), "hello");
	});

	it("joins text blocks from a content array", () => {
		const blocks = [
			{ type: "text", text: "hello" },
			{ type: "image", url: "..." },
			{ type: "text", text: "world" },
		];
		assert.equal(extractText(blocks), "hello\nworld");
	});

	it("returns empty string for unknown shapes", () => {
		assert.equal(extractText(undefined), "");
		assert.equal(extractText(null), "");
		assert.equal(extractText(42), "");
		assert.equal(extractText([{ type: "image" }]), "");
	});

	it("renders tool calls with their (truncated) JSON args", () => {
		const blocks = [
			{ type: "toolCall", name: "do_thing", arguments: { x: 1, y: "two" } },
			{ type: "text", text: "ignored here" },
		];
		const out = extractToolCallText(blocks);
		assert.match(out, /\[tool: do_thing/);
		assert.match(out, /"x":1/);
	});

	it("truncates very long tool args with an ellipsis", () => {
		const huge = "X".repeat(1000);
		const blocks = [{ type: "toolCall", name: "n", arguments: { huge } }];
		const out = extractToolCallText(blocks);
		assert.ok(out.length < 500);
		assert.ok(out.endsWith("\u2026]"), `expected ellipsis tail, got ${out.slice(-20)}`);
	});

	it("returns empty string for non-array inputs", () => {
		assert.equal(extractToolCallText("string"), "");
		assert.equal(extractToolCallText(undefined), "");
	});
});

describe("parseFindSessionsArgs", () => {
	it("parses a bare query", () => {
		const r = parseFindSessionsArgs("vault overseer");
		assert.equal(r.query, "vault overseer");
		assert.equal(r.error, undefined);
	});

	it("parses --cwd, --role, --since, --until, --max", () => {
		const r = parseFindSessionsArgs(
			"--cwd=OneAdobe --role=user --since=2026-04-01 --until=2026-04-30 --max=5 my query",
		);
		assert.equal(r.cwd, "OneAdobe");
		assert.equal(r.role, "user");
		assert.equal(r.since, "2026-04-01");
		assert.equal(r.until, "2026-04-30");
		assert.equal(r.max, 5);
		assert.equal(r.query, "my query");
	});

	it("rejects an invalid --role", () => {
		const r = parseFindSessionsArgs("--role=root anything");
		assert.match(r.error ?? "", /Invalid --role=root/);
		assert.equal(r.query, undefined);
	});

	it("rejects a non-positive --max", () => {
		const r = parseFindSessionsArgs("--max=0 anything");
		assert.match(r.error ?? "", /Invalid --max=0/);
	});

	it("returns no query when only flags are given", () => {
		const r = parseFindSessionsArgs("--cwd=foo");
		assert.equal(r.query, undefined);
	});
});
