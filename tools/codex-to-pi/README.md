# Convert Codex and ChatGPT conversations to Pi

[`codex-to-pi`](../../bin/codex-to-pi) converts Codex history, ChatGPT share URLs, and ChatGPT account exports to Pi v3 JSONL.

It requires Python 3; local history conversion also requires Babashka (`bb`) on PATH.
Session-ID conversion additionally requires Node and an installed Codex with `thread/turns/list` support.
Share URLs require network access and the [share-page extractor](../extract-chat-share/README.md).
Conversion writes a new Pi session file; it does not resume a session or replay tools.

```sh
codex-to-pi SESSION_ID -o conversation.jsonl
codex-to-pi SESSION_ID --branches -o branches.jsonl
```

For Codex history and share URLs, choose an output path that is safe to replace.
Account-export imports refuse to replace existing sessions or attachment directories.

## Import a ChatGPT account export

Account exports need only Python 3, with no network access or Babashka dependency.
Pass the ZIP directly, an extracted export directory, or a `conversations.json` / `conversations-NNN.json` file.
ZIP and directory inputs read all conversation shards; a JSON input reads only that file.

```sh
codex-to-pi export.zip --list
codex-to-pi export.zip --cwd ~/src --conversation CONVERSATION_ID -o conversation.jsonl
codex-to-pi export.zip --cwd ~/src --branches --output-dir imported-chats
```

`--list` prints IDs and JSON-quoted titles without writing anything.
Imports include every conversation by default; use `--conversation ID` to import only one.
`--output-dir` chooses a directory for separate session files; `-o` chooses a single file and requires exactly one selected conversation.
Imports require `--cwd DIR`, including imports with an explicit output destination.
This sets the working directory recorded in every imported session; relative paths resolve from the command's current directory.
Without an output option, imports go into Pi's session directory for that explicit working directory, where `/resume` can find them.
`--list` requires no working directory and does not import anything.

Imports preserve titles, conversation creation times, message times when available, and per-message model names.
A missing message time falls back to the conversation creation time; a missing conversation time uses the import time.
The default follows parent links from `current_node`, not the order of JSON object keys.
`--branches` includes alternate paths in the same Pi tree and selects the exported `current_node` when opened.
Null nodes do not become conversation messages.
Parent-linked tool results and named assistant calls with JSON-object arguments become Pi tool calls and results when every imported continuation supplies a matching result.
If an alternate branch or selected tip leaves a call unanswered, that call and its results use the archival representation instead.
Calls with code or other non-object arguments, unmatched results, and other message roles become visible archival messages with their original source records retained in metadata.
Archived system and developer messages do not become active system-role instructions.

Reasoning thoughts and recaps become Pi `thinking` blocks.
Thought summaries and body text are retained, with chunks used when body text is absent.
Audio transcriptions become text.
Supported user and tool-result images (PNG, JPEG, GIF, WebP) embed their bytes in the session.
Other attachments, including assistant images and image formats Pi cannot display, appear as saved-file references.
Files are saved beside each session in `<session-filename-without-.jsonl>.assets/`, with original filenames sanitized under separate asset directories.
File references use absolute paths; moving the import requires updating those references.
Embedded images remain usable without the sidecar directory.

The importer resolves asset pointers, `.dat` files, original-filename indexes, and library file IDs locally.
Missing file data produces visible references and warnings rather than invented content.
Warnings identify the conversation title and ID, message ID, attachment name, and source reference.
The count measures unresolved references per message, not bytes or unique files; duplicate references within one message count once.
Unknown content is retained as marked JSON text and reported in warnings.
Imports do not recover reasoning or files absent from the export, fetch remote assets, or replay tools.

All selected destinations and parent chains are checked before batch writing.
Each completed session is published only after its attachments are written.
If a later conversation fails, earlier completed imports remain and the command reports their count.
Reruns refuse existing destinations; choose a fresh output directory.

## Message selection

Session-ID conversion uses the same [history reader](../../libexec/chat-history.clj) as `extract-chat`.
It starts an owned Codex app-server, reads thread metadata, and pages full turn items in conversation order without resuming the thread or starting a turn.
Both active and archived sessions use Codex's displayed conversation, which can differ from its retained model context after imports or compaction.
User and assistant text, repeated occurrences, and assistant phases are preserved; tools and other non-message items are omitted.
Unsupported user content or unknown history item types fail before writing the destination.
Recorded turn times are used when available; these are not original per-message timestamps.

Explicit file paths and `--branches` retain the offline rollout reader, including ancestor cutoffs and superseded rollouts that the ID-based API cannot select.
Directory scans in `extract-chat` also remain offline.
The offline reader omits injected skill instructions while preserving skill invocations and discussion.
An API failure does not silently fall back to parsing message records.

## Output and path options

Use `codex-to-pi SESSION -o FILE` to choose the destination; otherwise it writes to Pi's session directory.
`--archived` searches archived sessions; `--normalize` rewrites macOS paths for sandbox sessions.

## Import a conversation tree

`codex-to-pi SESSION --branches -o FILE` imports related forks and superseded rollouts into one Pi tree; use `/tree` to navigate it.
Discovery includes active and archived history, ancestors, sibling forks, and descendants, while excluding spawned subagent sessions.
Branch endpoints carry Codex thread and rollout labels, and the requested rollout is selected when Pi opens the file.
Shared source records appear once; repeated messages from different records remain distinct.
Codex branch import requires local paginated history and all referenced ancestors; legacy Codex sessions and share URLs are rejected.
Without `--branches`, conversion and Markdown extraction follow only the selected thread.
