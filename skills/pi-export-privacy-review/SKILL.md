---
name: pi-export-privacy-review
description: >-
  Review Pi session exports for credentials, personal information, private project material, cross-session disclosure, and internal agent data.
  Use for sensitivity, privacy, secret, or publication-safety audits of Pi HTML or JSONL exports.
  Not for ordinary session summaries, arbitrary repository secret scans, or sanitizing an export unless the user also requests changes.
---

# Pi export privacy review

Determine what a Pi export discloses and whether that disclosure matters to its intended audience.

## Establish scope

Review the named export and any session payloads embedded in it.
Treat review as read-only; it does not authorize rewriting, deleting, or publishing the export.
If the audience is unstated, assess sharing with an untrusted public recipient and state that assumption.
Ask about the audience only when it would materially change the conclusion.

Inspect the complete file rather than only visible rendered messages.
Run `node <skill-dir>/scripts/audit.mjs <export>` to parse the complete HTML or JSONL export and produce a bounded structural inventory.
The script reports masked candidate values, JSON paths, counts, imported-session operations, and unexamined categories.
It does not write decoded data to disk.
Treat its output as leads for the contextual inspection below, not as findings or proof that unreported data is safe.
For HTML exports, it locates the `script#session-data` payload, decodes its base64 text, and parses the resulting JSON.
For JSONL exports, it parses every non-empty record using the export's actual schema.
Treat base64 as encoding, not redaction.
If decoding or parsing fails, report the exact unexamined scope and stop claims that depend on it.

Use a private temporary file only when streaming inspection is impractical.
Remove that owned temporary copy after the review.
Do not place decoded session data in the repository or command output merely to make it searchable.

## Inventory the disclosure surface

Inspect both the outer export and the decoded session structure, including:

- session headers, working directories, parent-session paths, timestamps, ids, titles, and model metadata;
- user, assistant, system, custom, and compaction messages;
- tool calls, arguments, results, errors, command output, file reads, patches, and attachments;
- thinking text, `thinkingSignature`, `textSignature`, and other opaque provider fields;
- session-search and session-read results, which can disclose material from sessions other than the exported one;
- cached or pre-rendered HTML that duplicates or expands data beyond the visible transcript.

Count and identify each imported session separately.
Inspect the returned excerpts themselves; a failed read exposes only its request and error unless another field contains the session content.

## Classify findings from context

Check for these consequences:

- usable credentials or authentication material: private keys, API tokens, cookies, and authorization headers;
- credential-bearing signed URLs, commands, and secret environment values;
- direct personal information: private email addresses, phone numbers, postal addresses, legal identifiers, and account names that link to a person;
- machine and account details: home-directory names, private hostnames, and internal addresses;
- filesystem layout, session roots, and stable session identifiers;
- confidential work: unpublished source, patches, reports, issue contents, plans, customer data, private links, and repository history;
- conversation spillover: imported session text, user messages, internal instructions, summaries, or decisions outside the intended transcript;
- internal agent data: system prompts, hidden reasoning summaries, tool schemas, and opaque signatures.

Do not label a value sensitive solely because it matches a pattern.
Inspect its JSON field, surrounding text, source entry, and apparent use.
Distinguish real values from documentation examples, placeholders, source-code literals, truncated output, and encoded data.
Strip ANSI control sequences before interpreting values; do not turn a color prefix into part of an email address or token.
Deduplicate repeated values and distinguish one disclosure repeated many times from many distinct disclosures.

Do not call an opaque signature a credential without evidence that it grants access.
Report it as signed internal provider data and state that reuse risk is unverified.
Recommend removing it from public exports when it serves no reader need.
Check actual exposure and the intended audience before treating a public path, commit email, or URL as confidential.

## Handle secrets safely

Never reproduce a complete suspected credential in tool output or the report.
Show a short prefix or hash only when needed to distinguish findings.
An exact ordinary email or path may be shown when the user needs identification and disclosure in the review itself is acceptable.
When that is unclear, report its field and location first and ask before revealing it.

Searches provide candidates, not findings.
Use structure-aware queries where possible and confirm every reported secret in context.
State which common credential families were checked and which were not.

## Report the result

Lead with whether the export is suitable for the stated audience as-is.
For each material finding, give:

- the disclosed category and concrete consequence;
- the outer file and line, plus decoded JSON path or entry index when the payload occupies one line;
- whether the value is unique or repeated;
- the smallest useful action: keep, redact, remove a field class, or regenerate a safer export.

Separate definite sensitivity from audience-dependent exposure and low-confidence candidates.
Report meaningful negative checks, especially the absence of common credentials, without implying that pattern scans prove safety.
State inspected, skipped, failed, and unavailable surfaces so silence cannot imply completeness.

If sanitization is requested, preserve the original and write an explicitly named sanitized copy.
Re-parse that copy and inspect the consumer-visible export to confirm the targeted data is absent and the remaining transcript still works.

## Completion checks

Complete the review only after decoding the full export container or reporting its gap.
Account for every imported-session result and verify candidate matches in context.
Derive the recommendation from the intended audience.

This skill must trigger for “review this Pi HTML export for sensitive information before I publish it.”
It must not trigger for “summarize this Pi session” or “scan this repository for committed secrets.”
