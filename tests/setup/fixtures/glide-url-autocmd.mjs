import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const config = readFileSync(process.argv[2], "utf8");
const registrations = [];
const deleted = [];
runInNewContext(
  config.slice(config.indexOf("async function disable_shortcuts"), config.indexOf("// pin tab")),
  {
    URL,
    glide: {
      autocmds: {
        create(event, pattern, callback) {
          assert.equal(event, "UrlEnter");
          registrations.push({ pattern, callback });
        },
      },
      excmds: { async execute() {} },
      buf: {
        keymaps: {
          del(mode, key) { deleted.push([mode, key]); },
          set() {},
        },
      },
    },
  },
);

const zulipKeys = ["d", "e", "r", "t", "U", ":"].map(key => ["normal", key]);
const longTail = "a".repeat(1_000_000);
const cases = [
  ["https://rust-lang.zulipchat.com/", true],
  ["https://rust-lang.zulipchat.com/#narrow/channel/1", true],
  ["https://sub.team.zulipchat.com:8443/", true],
  ["https://user:password@rust-lang.zulipchat.com/", true],
  ["https://rust-lang.zulipchat.com/" + longTail, true],
  ["https://example.com/" + longTail, false],
  ["data:text/plain," + longTail, false],
  ["about:blank", false],
  ["file:///tmp/team.zulipchat.com", false],
  ["https://example.com/team.zulipchat.com", false],
  ["https://example.com/?next=https://team.zulipchat.com", false],
  ["https://team.zulipchat.com.evil.example/", false],
  ["https://team.zulipchatXcom/", false],
  ["https://team.zulipchat.com:password@evil.example/", false],
  ["https://zulipchat.com/", false],
];

for (const [url, expected] of cases) {
  deleted.length = 0;
  for (const { pattern, callback } of registrations) {
    // Glide matches regex patterns against the whole URL, not the hostname.
    const matches = "test" in pattern
      ? pattern.test(url)
      : pattern.hostname === undefined || new URL(url).hostname === pattern.hostname;
    if (matches) await callback({ url, tab_id: 1 });
  }
  assert.deepEqual(deleted, expected ? zulipKeys : [], url.slice(0, 100));
}
