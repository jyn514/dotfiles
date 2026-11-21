import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmod, copyFile, mkdir, mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { parseOptions } from "../src/cli.ts";

for (const [name, args, expected] of [
  ["no arguments preserves gallery", [], { mode: "gallery" }],
  ["one term searches all likes", ["education"], { mode: "search", terms: ["education"], json: false }],
  ["multiple terms retain argument boundaries", ["higher education", "AI"], { mode: "search", terms: ["higher education", "AI"], json: false }],
  ["JSON output", ["--json", "education"], { mode: "search", terms: ["education"], json: true }],
  ["JSON without terms exports all likes", ["--json"], { mode: "search", terms: [], json: true }],
  ["profile without terms lists liked posts by that author", ["--profile", "writer.example"], { mode: "search", terms: [], json: false, profile: "writer.example" }],
  ["profile accepts an at-prefixed handle", ["--profile", "@writer.example", "art"], { mode: "search", terms: ["art"], json: false, profile: "writer.example" }],
  ["profile accepts a DID", ["--profile", "did:plc:writer"], { mode: "search", terms: [], json: false, profile: "did:plc:writer" }],
  ["media filter without terms lists liked media", ["--media-only"], { mode: "search", terms: [], json: false, mediaOnly: true }],
  ["filters combine with JSON and search terms", ["--profile", "writer.example", "--media-only", "--json", "art"], { mode: "search", terms: ["art"], json: true, profile: "writer.example", mediaOnly: true }],
  ["option-like literal term", ["--", "--education"], { mode: "search", terms: ["--education"], json: false }],
  ["help", ["--help"], "help"],
  ["short help", ["-h"], "help"],
]) {
  test(name, () => assert.deepEqual(parseOptions(args), expected));
}
for (const args of [["--unknown"], [""], ["   "], ["--profile"], ["--profile", ""], ["--profile", "@"], ["--profile", "   "], ["--media-only=true"]]) {
  test(`invalid arguments are rejected: ${JSON.stringify(args)}`, () => {
    assert.throws(() => parseOptions(args));
  });
}

test("the invoked wrapper shows help and rejects invalid input without dependencies or state", async () => {
  const root = await mkdtemp(join(tmpdir(), "bsky-cli-"));
  try {
    const bin = join(root, "bin");
    const src = join(root, "tools", "search-bsky-likes", "src");
    const home = join(root, "home");
    await Promise.all([mkdir(bin), mkdir(src, { recursive: true }), mkdir(home)]);
    const wrapper = join(bin, "search-bsky-likes");
    await copyFile(new URL("../../../bin/search-bsky-likes", import.meta.url), wrapper);
    await chmod(wrapper, 0o755);
    await copyFile(new URL("../src/cli.ts", import.meta.url), join(src, "cli.ts"));
    const env = { ...process.env, HOME: home, XDG_STATE_HOME: join(home, "state") };
    for (const flag of ["--help", "-h"]) {
      const result = spawnSync(wrapper, [flag], { env, encoding: "utf8", timeout: 10_000 });
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, /Search all posts liked by jyn.dev/);
      assert.match(result.stdout, /--json/);
      assert.match(result.stdout, /--profile HANDLE\|DID/);
      assert.match(result.stdout, /--media-only/);
      assert.equal(result.stderr, "");
    }
    const result = spawnSync(wrapper, ["--unknown"], { env, encoding: "utf8", timeout: 10_000 });
    assert.equal(result.status, 1);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /--unknown/);
    assert.doesNotMatch(result.stderr, /ERR_MODULE_NOT_FOUND/);
    assert.deepEqual(await readdir(home), []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
