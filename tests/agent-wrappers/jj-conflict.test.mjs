import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { compose, parseConflicts } from "../../libexec/agent-wrappers/jj-conflict";
import test from "node:test";

const execFileAsync = promisify(execFile);
const jj = process.env.JJ_TEST_BIN || process.env.DOTFILES_TEST_JJ_REAL || process.env.JJ_REAL
	|| (existsSync("/opt/agent-tools/libexec/jj") ? "/opt/agent-tools/libexec/jj" : "jj");
const helper = fileURLToPath(new URL("../../libexec/agent-wrappers/jj-conflict", import.meta.url));

const fixture = `before
<<<<<<< conflict 1 of 2
%%%%%%% diff from: base abc
\\\\\\        to: side def
 one
-old
+new
 three
+++++++ side ghi
one
old
three
>>>>>>> conflict 1 of 2 ends
after
<<<<<<< conflict 2 of 2
+++++++ side jkl
alpha
beta
%%%%%%% diff from: base ghi
\\\\\\        to: side mno
 alpha
-beta
+gamma
>>>>>>> conflict 2 of 2 ends
`;

const bases = new Map([
	["base abc", ["one", "old", "three"]],
	["base ghi", ["alpha", "beta"]],
]);
const resolveBase = (source) => bases.get(source);

test("parses snapshot and destination metadata", () => {
	const conflicts = parseConflicts(fixture);
	assert.equal(conflicts.length, 2);
	assert.equal(conflicts[0].diffSource, "base abc");
	assert.equal(conflicts[0].diffDestination, "side def");
	assert.deepEqual(conflicts[0].snapshot, ["one", "old", "three"]);
});

test("composes only selected edits and preserves unselected marker blocks", () => {
	const conflicts = parseConflicts(fixture);
	const lines = fixture.split("\n");
	const first = lines.slice(conflicts[0].startLine - 1, conflicts[0].endLine).join("\n");
	const second = lines.slice(conflicts[1].startLine - 1, conflicts[1].endLine).join("\n");
	assert.equal(compose(fixture, [1], resolveBase), fixture.replace(first, "one\nnew\nthree"));
	assert.equal(compose(fixture, [2], resolveBase), fixture.replace(second, "alpha\ngamma"));
	assert.equal(compose(fixture, [], resolveBase), fixture);
});

test("preserves upstream-only output schema outside the selected diff", () => {
	const withSchema = fixture.replace("+++++++ side ghi\none", "+++++++ side ghi\noutputSchema: schema,\none");
	assert.match(compose(withSchema, [1], resolveBase), /outputSchema: schema,\none\nnew\nthree/);
});

test("refuses to restore historical keybinding context over a destination change", () => {
	const changedContext = fixture.replaceAll("one", "ctrl+end: bufferEnd")
		.replace("+++++++ side ghi\nctrl+end: bufferEnd", "+++++++ side ghi\nctrl+end: lineEnd");
	assert.throws(
		() => compose(changedContext, [1], () => ["ctrl+end: bufferEnd", "old", "three"]),
		/does not apply to its destination snapshot.*resolve it manually/,
	);
});

test("preserves CRLF outside the selected conflict, including unselected markers", () => {
	const crlf = fixture.replaceAll("\n", "\r\n");
	assert.equal(compose(crlf, [], resolveBase), crlf);
	const resolved = compose(crlf, [1, 2], resolveBase);
	assert.equal(resolved, "before\r\none\r\nnew\r\nthree\r\nafter\r\nalpha\r\ngamma\r\n");
});

test("preserves mixed line endings in unchanged snapshot context and surrounding text", () => {
	const mixed = fixture.replace("+++++++ side ghi\none\nold\nthree\n", "+++++++ side ghi\none\r\nold\nthree\r\n");
	const first = mixed.slice(mixed.indexOf("<<<<<<<"), mixed.indexOf("after\n"));
	assert.equal(compose(mixed, [1], resolveBase), mixed.replace(first, "one\r\nnew\nthree\r\n"));
});

test("rejects unsupported newline annotations rather than silently ignoring them", () => {
	const annotated = fixture.replace("+new\n", "+new\n\\ No newline at end of file\n");
	assert.throws(() => compose(annotated, [1], resolveBase), /newline annotation.*resolve it manually/);
});

test("rejects native terminating-newline changes instead of adding a second newline", () => {
	for (const delta of ["-a\n+b\n+", " a\n+"]) {
		const newlineChange = `<<<<<<< conflict 1 of 1
%%%%%%% diff from: source abcdef12 (no terminating newline)
\\\\\\        to: incoming fedcba98
${delta}
+++++++ snapshot 12345678
prefix
a

>>>>>>> conflict 1 of 1 ends`;
		assert.throws(() => compose(newlineChange, [1], () => ["a"]), /terminating-newline states.*resolve it manually/);
	}
});

test("rejects destination newline changes even when the incoming delta leaves EOF alone", () => {
	const changedSnapshot = fixture.replace("+++++++ side ghi", "+++++++ side ghi (no terminating newline)");
	assert.throws(() => compose(changedSnapshot, [1], resolveBase), /terminating-newline states.*resolve it manually/);
});

test("accepts long markers and CRLF input", () => {
	const longMarkers = fixture
		.replaceAll("<<<<<<<", "<<<<<<<<<<<<<<<")
		.replaceAll("%%%%%%%", "%%%%%%%%%%%%%%")
		.replaceAll("\\\\\\", "\\\\\\\\\\\\\\")
		.replaceAll(">>>>>>>", ">>>>>>>>>>>>>>>")
		.replaceAll("\n", "\r\n");
	assert.equal(parseConflicts(longMarkers).length, 2);
});

test("apply uses the embedded commit hash when the source change ID is unresolved", async () => {
	const repo = await mkdtemp(`${tmpdir()}/jj-conflict-source-revision-`);
	const env = { ...process.env };
	delete env.JJ_AGENT;
	delete env.JJ_PROXY_REPO;
	delete env.JJ_REAL;
	try {
		const runJj = (args) => execFileAsync(jj, args, { cwd: repo, env });
		await runJj(["git", "init", "--colocate"]);
		await writeFile(`${repo}/file.txt`, "before\nold\nafter\n");
		await runJj(["commit", "-m", "base"]);
		const { stdout: baseOutput } = await runJj(["log", "-r", "@", "--no-graph", "-T", "commit_id"]);
		const baseCommit = baseOutput.trim();
		const conflict = `<<<<<<< conflict 1 of 1
%%%%%%% diff from: spumopow ${baseCommit} (rebased revision)
\\\\\\        to: destination 12345678
 before
-old
+new
 after
+++++++ snapshot 87654321
upstream-only
before
old
after
>>>>>>> conflict 1 of 1 ends\n`;
		const unselected = fixture.slice(fixture.indexOf("<<<<<<< conflict 2"));
		const input = conflict + unselected;
		const path = `${repo}/file.txt`;
		const options = { cwd: repo, env: { ...env, JJ_BIN: jj } };
		await writeFile(path, input);
		const { stdout: preview, stderr: previewStatus } = await execFileAsync(helper, ["apply", path, "--edit", "1", "--preview"], options);
		assert.equal(preview, `--- snapshot: ${path} (conflict 1)
+++ resolution: ${path} (conflict 1)
@@ -1,4 +1,4 @@
 upstream-only
 before
-old
+new
 after
`);
		assert.match(previewStatus, /1 unresolved.*not written/);
		assert.equal(await readFile(path, "utf8"), input);
		await assert.rejects(execFileAsync(helper, ["apply", path, "--edit", "1", "--stdout", "--preview"], options), /cannot combine/);
		assert.equal(await readFile(path, "utf8"), input);
		const { stdout: resolved } = await execFileAsync(helper, ["apply", path, "--edit", "1", "--stdout"], options);
		assert.equal(resolved, "upstream-only\nbefore\nnew\nafter\n" + unselected);
		assert.equal(await readFile(path, "utf8"), input);
		await execFileAsync(helper, ["apply", path, "--edit", "1"], options);
		assert.equal(await readFile(path, "utf8"), resolved);
		await assert.rejects(execFileAsync(helper, ["check", path], options), /1 unresolved conflict/);

		const history = Array.from({ length: 1000 }, (_, index) => `history-${index}`).join("\n");
		const large = conflict.replace("upstream-only\n", `${history}\nupstream-only\n`);
		await writeFile(path, large);
		const { stdout: concise } = await execFileAsync(helper, ["apply", path, "--edit", "1", "--preview"], options);
		assert.match(concise, /@@ -1000,5 \+1000,5 @@/);
		assert.match(concise, / history-999\n upstream-only/);
		assert.doesNotMatch(concise, /history-0\n/);
		assert.ok(concise.split("\n").length < 15);
		assert.equal(await readFile(path, "utf8"), large);

		const overlap = conflict.replace("before\nold\nafter\n", "before\nother\nafter\n");
		const partlyApplicable = conflict + overlap;
		await writeFile(path, partlyApplicable);
		await assert.rejects(execFileAsync(helper, ["apply", path, "--edit", "1,2"], options), /destination snapshot.*resolve it manually/);
		assert.equal(await readFile(path, "utf8"), partlyApplicable);

		// Fetch a real CRLF source file rather than supplying normalized unit-test data.
		await writeFile(path, "before\r\nold\r\nafter\r\n");
		await runJj(["commit", "-m", "CRLF source"]);
		const { stdout: crlfBase } = await runJj(["log", "-r", "@", "--no-graph", "-T", "commit_id"]);
		const crlfConflict = conflict.replace(baseCommit, crlfBase.trim()).replaceAll("\n", "\r\n");
		await writeFile(path, crlfConflict);
		const { stdout: crlfResolved } = await execFileAsync(helper, ["apply", path, "--edit", "1", "--stdout"], options);
		assert.equal(crlfResolved, "upstream-only\r\nbefore\r\nnew\r\nafter\r\n");

		await writeFile(path, "");
		await runJj(["commit", "-m", "empty source"]);
		const { stdout: emptyBase } = await runJj(["log", "-r", "@", "--no-graph", "-T", "commit_id"]);
		const insertion = `<<<<<<< conflict 1 of 1
+++++++ empty snapshot
%%%%%%% diff from: source ${emptyBase.trim()}
\\\\\\        to: incoming
+added
>>>>>>> conflict 1 of 1 ends
`;
		await writeFile(path, insertion);
		const { stdout: inserted } = await execFileAsync(helper, ["apply", path, "--edit", "1", "--stdout"], options);
		assert.equal(inserted, "added\n");
		const { stdout: insertedPreview } = await execFileAsync(helper, ["apply", path, "--edit", "1", "--preview"], options);
		assert.match(insertedPreview, /@@ -0,0 \+1,1 @@\n\+added\n/);
	} finally {
		await rm(repo, { recursive: true, force: true });
	}
});

test("rejects repeated diff context", () => {
	const ambiguous = `<<<<<<< conflict 1 of 1
+++++++ base
same
old
same
old
%%%%%%% diff from: base
\\\\\\        to: side
 same
-old
+new
>>>>>>> conflict 1 of 1 ends\n`;
	assert.throws(() => compose(ambiguous, [1], () => ["same", "old", "same", "old"]), /context occurs more than once/);
});

test("rejects ambiguous destination context even when the historical source is unique", () => {
	const repeated = fixture.replace("+++++++ side ghi\none\nold\nthree", "+++++++ side ghi\none\nold\nthree\none\nold\nthree");
	assert.throws(() => compose(repeated, [1], resolveBase), /context occurs more than once in the destination snapshot/);
});

test("checks historical provenance even when the destination text matches", () => {
	assert.throws(() => compose(fixture, [1], () => ["unrelated"]), /does not apply to its base snapshot/);
});

test("preserves a missing final newline and removes a wholly deleted snapshot", () => {
	const single = fixture.slice(0, fixture.indexOf("after\n<<<<<<<"));
	assert.equal(compose(single.trimEnd(), [1], resolveBase), "before\none\nnew\nthree");
	const noNewline = single.trimEnd()
		.replace("base abc", "base abc (no terminating newline)")
		.replace("side def", "side def (no terminating newline)")
		.replace("side ghi", "side ghi (no terminating newline)");
	assert.equal(compose(noNewline, [1], () => ["one", "old", "three"]), "before\none\nnew\nthree");
	const deletion = single.replace(/ one\n-old\n\+new\n three/, "-one\n-old\n-three");
	assert.equal(compose(deletion, [1], resolveBase), "before\n");
});

test("rejects context-free insertions into nonempty bases with manual-resolution guidance", () => {
	const contextFree = `<<<<<<< conflict 1 of 1
+++++++ snapshot
base
%%%%%%% diff from: source 74526c22
\\\\\\        to: side
+added
>>>>>>> conflict 1 of 1 ends\n`;
	assert.throws(
		() => compose(contextFree, [1], () => ["before", "after"]),
		/no context to locate its insertion.*resolve it manually/,
	);
});

test("selects a specific alternative from a multi-sided conflict", () => {
	const multiSided = `<<<<<<< conflict 1 of 1
%%%%%%% diff from: base
\\\\\\        to: side-a
-base
+side-a
%%%%%%% diff from: base
\\\\\\        to: side-b
-base
+side-b
+++++++ side-c
base
upstream-only
>>>>>>> conflict 1 of 1 ends\n`;
	const conflicts = parseConflicts(multiSided);
	assert.equal(conflicts[0].diffs.length, 2);
	assert.equal(compose(multiSided, ["1:2"], () => ["base"]), "side-b\nupstream-only\n");
	assert.equal(compose(multiSided, [], () => ["base"]), multiSided);
	assert.throws(() => compose(multiSided, ["1:3"], () => ["base"]), /does not identify/);
});

test("inspect preserves added and removed line markers", async () => {
	const directory = await mkdtemp(`${tmpdir()}/jj-conflict-inspect-`);
	const path = `${directory}/file.txt`;
	try {
		await writeFile(path, fixture);
		const { stdout: jsonOutput } = await execFileAsync(helper, ["inspect", path, "--json"]);
		const report = JSON.parse(jsonOutput);
		assert.deepEqual(report.conflicts[0].alternatives[0].changes, ["-old", "+new"]);
		assert.deepEqual(report.conflicts[0].snapshot, ["one", "old", "three"]);

		const { stdout: textOutput } = await execFileAsync(helper, ["inspect", path]);
		assert.match(textOutput, /snapshot side ghi:\n    one\n    old\n    three\n/);
		assert.match(textOutput, /\n    -old\n    \+new\n/);
	} finally {
		await rm(directory, { recursive: true, force: true });
	}
});

test("rejects overlapping changes in a real three-parent jj conflict without writing", async () => {
	const repo = await mkdtemp(`${tmpdir()}/jj-conflict-real-`);
	const env = { ...process.env };
	delete env.JJ_AGENT;
	delete env.JJ_PROXY_REPO;
	delete env.JJ_REAL;
	try {
		const runJj = (args) => execFileAsync(jj, args, { cwd: repo, env });
		await runJj(["git", "init", "--colocate"]);
		await writeFile(`${repo}/file.txt`, "base\n");
		await runJj(["commit", "-m", "base"]);
		const { stdout: baseOutput } = await runJj(["log", "-r", "@", "--no-graph", "-T", "commit_id"]);
		const base = baseOutput.trim();
		await runJj(["new", "-m", "side-a"]);
		await writeFile(`${repo}/file.txt`, "side-a\n");
		await runJj(["commit", "-m", "side-a"]);
		const { stdout: aOutput } = await runJj(["log", "-r", "@", "--no-graph", "-T", "commit_id"]);
		await runJj(["new", base, "-m", "side-b"]);
		await writeFile(`${repo}/file.txt`, "side-b\n");
		await runJj(["commit", "-m", "side-b"]);
		const { stdout: bOutput } = await runJj(["log", "-r", "@", "--no-graph", "-T", "commit_id"]);
		await runJj(["new", base, "-m", "side-c"]);
		await writeFile(`${repo}/file.txt`, "side-c\n");
		await runJj(["commit", "-m", "side-c"]);
		const { stdout: cOutput } = await runJj(["log", "-r", "@", "--no-graph", "-T", "commit_id"]);
		await runJj(["new", aOutput.trim(), bOutput.trim(), cOutput.trim(), "-m", "merge"]);
		const conflict = await readFile(`${repo}/file.txt`, "utf8");
		assert.equal(parseConflicts(conflict)[0].diffs.length, 2);
		const { stdout: report } = await execFileAsync(helper, ["inspect", `${repo}/file.txt`, "--json"], { cwd: repo, env });
		assert.equal(JSON.parse(report).conflicts[0].alternatives.length, 2);
		await assert.rejects(
			execFileAsync(helper, ["apply", `${repo}/file.txt`, "--edit", "1:2"], {
				cwd: repo,
				env: { ...env, JJ_BIN: jj },
			}),
			/does not apply to its destination snapshot.*resolve it manually/,
		);
		assert.equal(await readFile(`${repo}/file.txt`, "utf8"), conflict);
	} finally {
		await rm(repo, { recursive: true, force: true });
	}
});
