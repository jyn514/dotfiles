import assert from "node:assert/strict";
import { loadConfig } from "./glide-config.mjs";

const { registrations, deleted, executed, glide } = await loadConfig(process.argv[2]);

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
  for (const { event, pattern, callback } of registrations) {
    if (event !== "UrlEnter") continue;
    // Glide matches regex patterns against the whole URL, not the hostname.
    const matches = "test" in pattern
      ? pattern.test(url)
      : pattern.hostname === undefined || new URL(url).hostname === pattern.hostname;
    if (matches) await callback({ url, tab_id: 1 });
  }
  assert.deepEqual(deleted, expected ? zulipKeys : [], url.slice(0, 100));
}

for (const hostname of ["configure.zsa.io", "linear.app", "kumo.io"]) {
  executed.length = 0;
  const registration = registrations.find(({ event, pattern }) => event === "UrlEnter" && pattern.hostname === hostname);
  assert.ok(registration, `missing disabled site: ${hostname}`);
  const cleanup = await registration.callback({ url: `https://${hostname}/`, tab_id: 1 });
  assert.deepEqual(executed, ["mode_change ignore"]);
  await cleanup();
  assert.deepEqual(executed, ["mode_change ignore", "mode_change normal"]);
}

assert.equal(typeof glide.o.hint_label_generator, "function");
const labels = await glide.o.hint_label_generator({
  content: { async map(callback) { return [{ textContent: "Settings", ariaLabel: null }].map(callback); } },
});
assert.deepEqual(labels, ["s"]);

const sms = registrations.find(({ event, pattern }) => event === "UrlEnter" && pattern.hostname === "voice.google.com");
assert.ok(sms, "missing Google Voice handler");
const injections = [];
glide.content = { async execute(func, options) { injections.push({ func, options }); } };
const draft = { number: "+15551234567", body: "hello + café\n& # %", copied: true };
const smsUrl = "https://voice.google.com/u/0/messages#dotfiles-sms=" + encodeURIComponent(JSON.stringify(draft));
await sms.callback({ url: smsUrl, tab_id: 42 });
assert.equal(injections.length, 1);
assert.equal(typeof injections[0].func, "function");
assert.deepEqual(injections[0].options, { tab_id: 42, args: [draft] });
for (const url of ["https://voice.google.com/u/0/messages", smsUrl.replace("https:", "http:"),
                   smsUrl.replace("/messages", "/calls")]) {
  await sms.callback({ url, tab_id: 43 });
}
assert.equal(injections.length, 1, "ordinary navigation must not prefill");
await assert.rejects(() => sms.callback({
  url: smsUrl.replace(encodeURIComponent(draft.number), "not-a-number"), tab_id: 44,
}));
assert.equal(injections.length, 1, "invalid input must not reach a page");
