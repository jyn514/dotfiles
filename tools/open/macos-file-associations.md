# macOS file associations

macOS does not choose an application from a filename extension alone. It first classifies a file with a Uniform Type Identifier (UTI), then asks Launch Services for an application that handles that UTI in the required role.

This distinction matters for source files. An extension can map to an unexpected system UTI, a third-party application can introduce a more specific type, and a concrete UTI can have a different default from its parent.

## Classification and dispatch

For an ordinary file, the effective path is:

```text
path and metadata
    → concrete UTI
    → UTI conformance tree
    → application declarations and user defaults
    → role-specific Launch Services selection
    → application
```

A UTI has an identifier such as `public.swift-source` and can conform to broader types such as `public.source-code`, `public.plain-text`, and `public.data`. Applications declare supported UTIs in `CFBundleDocumentTypes`, with a role such as Editor or Viewer. Launch Services combines those declarations with user defaults.

A default for a parent is only a fallback. Registering nvim for `public.source-code` does not override a separate default for the more specific `public.swift-source` or `public.shell-script` type.

Extensions are not globally unambiguous. Two examples observed in this repository are:

| Extension | macOS classification without repository policy | Consequence |
| --- | --- | --- |
| `.ts` | `public.mpeg-2-transport-stream` | TypeScript opens in a video player. |
| `.edn` | `com.adobe.edn` | Clojure EDN inherits an unrelated third-party association. |

Dynamic UTIs beginning with `dyn.` appear when no installed declaration owns an extension. They often conform only to `public.data`, even when the file contains text. Extensionless Dockerfiles and shell configuration have the same problem.

## Why inspection commands disagree

Each inspection command answers a different question:

| Command or API | Question answered |
| --- | --- |
| `mdls -name kMDItemContentType -name kMDItemContentTypeTree FILE` | What UTI and conformance tree does metadata assign to this existing file? |
| `duti -x EXTENSION` | What application does duti find from this extension? |
| `duti -d UTI` | What bundle is stored as the default for this UTI? |
| `NSWorkspace.urlForApplication(toOpen:)` | What application would Launch Services choose for this actual file now? |
| `open FILE` | What does the repository wrapper choose, possibly before Launch Services? |

`duti -x` is not a final oracle. A generated private UTI can change the classification of a real file, so extension-only lookup may disagree with `NSWorkspace`. The setup therefore creates disposable files and asks `NSWorkspace` which application would open each one.

## Repository policy

[`lib/mimetypes.json`](../../lib/mimetypes.json) is the authoritative policy. Its macOS fields have separate purposes:

| Field | Ownership |
| --- | --- |
| `editor_utis` | Narrow parent UTIs that nvim owns, currently plain text and source code. |
| `editor_extensions` | Complete set of extensions owned by nvim. |
| `editor_ambiguous_extensions` | Extensions whose native UTI must not be claimed; `.ts` must not seize real MPEG transport streams. |
| `json_handler` | JSON policy owned by fx rather than nvim. |

The policy deliberately excludes broad `public.text`, `public.data`, `public.unix-executable`, and HTML ownership. Claiming those types would capture web documents, binary data, runnable programs, or other applications' files.

## Generated applications

[`setup_mimetypes.py`](../../libexec/setup/setup_mimetypes.py) builds two lightweight applications under `~/Applications`:

| Application | Bundle identifier | Command |
| --- | --- | --- |
| `nvim.app` | `dev.jyn.nvim` | `bin/hx-hax FILE` |
| `fx.app` | `dev.jyn.fx` | `REAL_EDITOR=fx bin/hx-hax FILE` |

Each application contains the native launcher from [`file-handler.swift`](../../libexec/setup/file-handler.swift). Launch Services starts that launcher, which forwards each selected path to the configured terminal command and exits.

For every editor extension, nvim.app exports a private UTI named `dev.jyn.nvim.document.EXTENSION` that conforms to `public.plain-text`. Exporting means the generated application owns the type; this gives unregistered and misleading extensions a narrow text identity without claiming their broad parent type.

For most extensions, the application also declares and assigns the concrete native or dynamic UTI found on the current machine. TypeScript is excluded from that step because its native UTI means MPEG video; only the private TypeScript UTI and extension association are used.

## Setup lifecycle

`./setup mimetypes` performs these phases:

1. Export current Launch Services preferences for inspection.
2. Compile the Swift classifier/launcher in a temporary directory.
3. Resolve native extension UTIs and relevant registered source UTIs.
4. Create disposable files and query their actual `NSWorkspace` application.
5. Compare actual defaults with policy; handler-list membership alone is insufficient.
6. Rebuild and register nvim.app and fx.app.
7. Write only missing UTI and extension defaults through duti.
8. Re-export preferences and remove stale roles owned by the managed bundles.

Cleanup occurs after all duti writes. Launch Services keeps an in-memory cache; cleaning an earlier export and then invoking duti can cause the daemon to write stale roles back.

`--dry-run` performs classification and default queries but does not rebuild applications or write preferences. A converged second dry-run prints `(none)` for every removal and registration group.

## Command-wrapper boundary

[`tools/open/open`](open) delegates normal suffixed files to Launch Services so JSON, HTML, images, media, and native formats retain their configured applications.

On macOS, a single extensionless local file is sent directly to the terminal editor.

The file must be a regular file whose first 8 KiB are valid UTF-8 and contain no NUL byte. Directories, URLs, multiple-argument desktop operations, suffixed files outside the wrapper list, and probable binaries remain delegated.

This interception prevents `open Dockerfile` from choosing TextEdit and prevents `open SCRIPT` from asking Terminal to execute an extensionless executable.

## Troubleshooting

First preview repository-owned drift:

```sh
python3 libexec/setup/setup_mimetypes.py --dry-run
```

Inspect an actual file's classification:

```sh
mdls -name kMDItemContentType -name kMDItemContentTypeTree PATH
```

Inspect extension and UTI records, remembering that neither substitutes for actual-file resolution:

```sh
duti -x edn
duti -d com.adobe.edn
duti -l com.adobe.edn
```

Apply policy and verify convergence:

```sh
./setup mimetypes
python3 libexec/setup/setup_mimetypes.py --dry-run
```

Launch Services may take tens of seconds to settle after an application rebuild. Do not reset the entire Launch Services database merely because the first verification is slow; that would discard unrelated user defaults.

## Safety invariants

- Setup is the sole writer of repository-managed desktop defaults.
- The JSON viewer remains fx.
- HTML and broad web types remain outside editor ownership.
- Real MPEG transport streams are never associated with nvim to repair TypeScript.
- `public.data` and `public.unix-executable` are never globally associated with nvim.
- The wrapper reads only enough file content to reject probable binaries; it never executes the inspected file.
