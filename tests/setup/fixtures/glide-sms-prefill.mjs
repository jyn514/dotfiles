import assert from "node:assert/strict";
import { loadConfig } from "./glide-config.mjs";

const { registrations, glide, executed } = await loadConfig(process.argv[2]);
const sms = registrations.find(({ event, pattern }) => event === "UrlEnter" && pattern.hostname === "voice.google.com");
assert.ok(sms);
glide.content = { async execute(func, { args }) { return await func(...args); } };
let activeTab = 42;
glide.tabs = { async active() { return { id: activeTab }; } };

// Exercise the form flow with the two number labels observed in Google Voice.
// These fixtures don't establish that Google's Angular bindings accepted input.
const nativeTimeout = globalThis.setTimeout;
globalThis.setTimeout = (callback, milliseconds) => nativeTimeout(callback, milliseconds / 100);
const observers = new Set();
globalThis.MutationObserver = class {
  constructor(callback) { this.callback = callback; }
  observe() { observers.add(this); }
  disconnect() { observers.delete(this); }
};

async function scenario(number, displayed, {
  existingBody = "", expectedBody = "hello + café", lateBlur = false,
  userInteracts = false, explicitRecipients,
} = {}) {
  executed.length = 0;
  let stage = "compose";
  let selected = false;
  let inputEvents = 0;
  let blurHappened = false;
  const entered = [];
  const confirmed = [];
  const numbers = Array.isArray(number) ? number : [number];
  const notices = [];
  const base = { getClientRects: () => [{}], getAttribute: () => null, focus() { document.activeElement = this; } };
  const compose = { ...base, textContent: "Send new message", click() { stage = "recipient"; } };
  const recipient = {
    ...base, value: "",
    dispatchEvent(event) {
      assert.equal(event.type, "input");
      assert.equal(event.bubbles, true);
      entered.push(this.value);
      stage = "suggestion";
    },
  };
  const suggestion = {
    ...base, disabled: false,
    get textContent() {
      const label = Array.isArray(displayed) ? displayed[confirmed.length] : displayed;
      return "chat Send to " + label.replace(/\D/g, "").split("").join(" ") + " Send to " + label;
    },
    querySelector(selector) {
      assert.equal(selector, ".send-to-label");
      const label = Array.isArray(displayed) ? displayed[confirmed.length] : displayed;
      return { textContent: " Send to ‪" + label + "‬ " };
    },
    click() {
      selected = true;
      confirmed.push(recipient.value);
      recipient.value = "";
      stage = confirmed.length === numbers.length ? "body" : "recipient";
    },
  };
  const body = {
    ...base, value: existingBody, disabled: false, readOnly: false,
    closest() { return document.body; },
    dispatchEvent(event) {
      assert.equal(event.type, "input"); inputEvents++;
      if (lateBlur) nativeTimeout(() => {
        document.activeElement = recipient;
        blurHappened = true;
        document.dispatchEvent(new Event("focusin"));
        for (const observer of [...observers]) observer.callback([]);
        if (userInteracts) {
          const event = new Event("pointerdown");
          Object.defineProperty(event, "isTrusted", { value: true });
          document.dispatchEvent(event);
        }
      }, 2);
    },
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
  };
  const selectors = {
    "button, [role=button], a": () => stage === "compose" ? [compose] : [],
    "div.input-field > input": () => [recipient],
    "section#contact-list > button#send-to-button": () => stage === "suggestion" ? [suggestion] : [],
    "div.message-input-container > textarea.message-input": () => stage === "body" ? [body] : [],
  };
  globalThis.document = Object.assign(new EventTarget(), {
    querySelectorAll(selector) { assert.ok(selector in selectors, selector); return selectors[selector](); },
    body: { append(notice) { notices.push(notice.textContent); } },
    createElement() { return { style: {}, setAttribute() {}, addEventListener() {}, append() {} }; },
  });
  const draft = { number: numbers.length === 1 ? numbers[0] : "", body: expectedBody, copied: true };
  if (explicitRecipients !== undefined) draft.recipients = explicitRecipients;
  else if (Array.isArray(number)) draft.recipients = numbers.map(number => ({ address: number, number }));
  const url = "https://voice.google.com/u/0/messages#dotfiles-sms=" + encodeURIComponent(JSON.stringify(draft));
  globalThis.location = new URL(url);
  globalThis.history = { state: null, replaceState() { location.hash = ""; } };
  await sms.callback({ url, tab_id: 42 });
  const manual = explicitRecipients?.some(recipient => recipient.number === null);
  assert.deepEqual(entered, manual ? [] : numbers);
  return { selected, confirmed, body: body.value, inputEvents, notices,
    focused: document.activeElement === body, blurHappened,
    selection: [body.selectionStart, body.selectionEnd], commands: [...executed] };
}

for (const displayed of ["(555) 555-5555", "+1 (555) 555-5555"]) {
  const result = await scenario("+15555555555", displayed);
  assert.equal(result.selected, true);
  assert.equal(result.body, "hello + café");
  assert.equal(result.inputEvents, 1);
  assert.deepEqual(result.notices, []);
  assert.equal(result.focused, true);
  assert.deepEqual(result.selection, [result.body.length, result.body.length]);
  assert.deepEqual(result.commands, ["mode_change insert"]);
}
for (const [number, displayed] of [
  ["+15555555555", "(555) 555-5556"],
  ["+445555555555", "(555) 555-5555"],
]) {
  const result = await scenario(number, displayed);
  assert.equal(result.selected, false);
  assert.equal(result.body, "");
  assert.equal(result.inputEvents, 0);
  assert.deepEqual(result.commands, []);
  assert.match(result.notices[0], /couldn't find suggestion/);
}
const existing = await scenario("+15555555555", "(555) 555-5555", { existingBody: "keep this draft" });
assert.equal(existing.body, "keep this draft");
assert.equal(existing.inputEvents, 0);
assert.match(existing.notices[0], /already contains a draft/);
assert.deepEqual(existing.commands, []);

const delayed = await scenario("+15555555555", "(555) 555-5555", { lateBlur: true });
assert.equal(delayed.blurHappened, true, "fixture must move focus after input");
assert.equal(delayed.focused, true, "focus must happen after the delayed form update");
assert.deepEqual(delayed.commands, ["mode_change insert"]);
assert.equal(observers.size, 0, "settling must remove all observers");

const cancelled = await scenario("+15555555555", "(555) 555-5555", { lateBlur: true, userInteracts: true });
assert.equal(cancelled.focused, false, "user interaction must cancel delayed focus");
assert.deepEqual(cancelled.commands, []);
assert.equal(observers.size, 0);

const group = await scenario(["+15555555555", "+15555555556"], ["(555) 555-5555", "(555) 555-5556"]);
assert.deepEqual(group.confirmed, ["+15555555555", "+15555555556"]);
assert.equal(group.body, "hello + café");
assert.equal(group.focused, true);
assert.deepEqual(group.commands, ["mode_change insert"]);

const recipientless = await scenario([], [], { expectedBody: null });
assert.equal(recipientless.selected, false);
assert.deepEqual(recipientless.notices, []);
const manual = await scenario([], [], { explicitRecipients: [{ address: "7042;phone-context=example.com", number: null }] });
assert.equal(manual.selected, false);
assert.equal(manual.inputEvents, 0);
assert.match(manual.notices[0], /7042;phone-context=example.com/);

activeTab = 43;
const background = await scenario("+15555555555", "(555) 555-5555");
assert.equal(background.body, "hello + café");
assert.deepEqual(background.commands, [], "background prefill must not change another tab's mode");
