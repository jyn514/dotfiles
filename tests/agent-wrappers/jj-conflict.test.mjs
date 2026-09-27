import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { compose, parseConflicts } from "../../libexec/agent-wrappers/jj-conflict";
import test from "node:test";

const execFileAsync = promisify(execFile);
const jj = process.env.JJ_TEST_BIN ?? process.env.JJ_REAL ?? "/opt/agent-tools/libexec/jj";
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

test("composes selected edits and keeps unselected snapshots", () => {
	assert.equal(compose(fixture, [1], resolveBase), `before
one
new
three
after
alpha
beta
`);
	assert.equal(compose(fixture, [2], resolveBase), `before
one
old
three
after
alpha
gamma
`);
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

test("rejects ambiguous edits", () => {
	const ambiguous = `<<<<<<< conflict 1 of 1
+++++++ base
same
same
%%%%%%% diff from: base
\\\\\\        to: side
 same
-old
+new
>>>>>>> conflict 1 of 1 ends\n`;
	assert.throws(() => compose(ambiguous, [1], () => ["same", "same"]), /does not apply/);
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
side-c
>>>>>>> conflict 1 of 1 ends\n`;
	const conflicts = parseConflicts(multiSided);
	assert.equal(conflicts[0].diffs.length, 2);
	assert.equal(compose(multiSided, ["1:2"], () => ["base"]), "side-b\n");
	assert.equal(compose(multiSided, [], () => ["base"]), "side-c\n");
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

		const { stdout: textOutput } = await execFileAsync(helper, ["inspect", path]);
		assert.match(textOutput, /\n    -old\n    \+new\n/);
	} finally {
		await rm(directory, { recursive: true, force: true });
	}
});

test("resolves a real three-parent jj conflict", async () => {
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
		const { stdout: resolved } = await execFileAsync(helper, ["apply", `${repo}/file.txt`, "--edit", "1:2", "--stdout"], {
			cwd: repo,
			env: { ...env, JJ_BIN: jj },
		});
		assert.equal(resolved, "side-b\n");
	} finally {
		await rm(repo, { recursive: true, force: true });
	}
});
