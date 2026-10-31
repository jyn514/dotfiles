# Extract a shared conversation

[`extract-chat-share`](../../bin/extract-chat-share) converts public ChatGPT or Claude share pages to Markdown. Claude extraction requires Safari automation on macOS; remote formats may change.

It reads an HTML file or a share URL and writes user/assistant turns to stdout.
It requires Node.js; Claude URL extraction uses Safari automation and requires JavaScript from Apple Events to be enabled.
Fetching a URL accesses the network and Claude extraction automates the browser.

```sh
extract-chat-share saved-chat.html
extract-chat-share --json saved-chat.html
```

For Markdown output, `--user-heading TEXT` and `--assistant-heading TEXT` customize the role headings.

## Structured output

`--json` emits an ordered array of `{role, text}` turns for machine consumers such as `codex-to-pi`, without Markdown framing or heading customization.
It uses the same readable-text selection as Markdown: empty and whitespace-only turns are omitted; retained text is not trimmed or escaped as Markdown.
