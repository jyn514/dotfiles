import assert from "node:assert/strict";
import { compose, parseConflicts } from "../../libexec/agent-wrappers/jj-conflict";
import test from "node:test";

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
