---
name: youtube-captions
description: Read YouTube captions or transcribe audio to understand, summarize, quote, discuss, or extract references from a linked video's spoken content. Use for requests to read a YouTube video or retrieve existing subtitles, including when the watch page is inaccessible or captions are absent. Prefer caption retrieval with youtube-transcript-api and yt-dlp; use local speech-to-text when understanding the video requires it. Not for video metadata alone, standalone media downloads, or inspecting visual content.
---

# YouTube captions

Retrieve readable text and read it before discussing a video's spoken content.
Prefer existing captions; a failed watch-page fetch does not establish that they are unavailable.
A request to understand a video can also use local audio transcription when captions are absent.
A request for existing subtitles alone should return those subtitles or report their absence, without substituting a new transcription.

## Use upstream tools

Start with the `youtube_transcript_api` CLI from the Python package `youtube-transcript-api`.
Use `yt-dlp` when the primary tool cannot retrieve an available track.
Check installed `--help` before adapting the commands below.
If a tool is missing, install it with the environment's existing package manager in disposable storage.
Use upstream retrieval and formatting before considering a new local helper.
Do not change host setup just to read one video.

See the upstream installation instructions for [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api#install) and [yt-dlp](https://github.com/yt-dlp/yt-dlp#installation).
For a Python-only environment without pip, the official `yt-dlp` zipapp can run as `python3 /path/to/yt-dlp`.
Keep a downloaded release in scratch storage and verify it against its published checksum before running it.

## Fetch a readable transcript

Extract `VIDEO_ID` from the supplied URL; `youtube_transcript_api` takes a video ID, not a whole URL.
Use an owned scratch directory for output.
List tracks to choose a language and see which are supplied or generated:

```sh
youtube_transcript_api 'VIDEO_ID' --list-transcripts
```

Choose the requested language, or the original spoken language when none is requested and you can read it.
Prefer supplied captions over automatic captions in that language.
Distinguish automatically translated tracks from original-language captions.
For English, retrieve timestamped segments with:

```sh
youtube_transcript_api 'VIDEO_ID' --languages en --format json > '/path/to/scratch/transcript.json'
```

Replace `en` with the selected language code.
The tool prefers supplied captions when both supplied and generated tracks match that language.
Use `--exclude-manually-created` only when the task specifically needs the generated track.
For a single video, JSON output contains one outer list whose element is the video's list of segments.
Each segment has `text`, `start`, and `duration`; times are in seconds.
Check the output contains nonempty transcript segments, not an error message or empty result.
Check their coverage against the requested interval.
For whole-video work, assess beginning and ending coverage and report any missing or unknown range before claiming completeness.
Keep the video URL, selected language, supplied/generated/translated status, and timestamps with your working evidence.

The tool returns text without VTT markup and decodes HTML entities.
It retrieves transcript segments rather than rolling VTT display cues.
Use those segments directly; do not add a deduplication pass merely because generated VTT can contain carry-over.
Use `--format text` when only readable text is needed; retain JSON when the answer needs timestamp citations.

## Fall back to yt-dlp

If the primary retrieval fails, try `yt-dlp` unless the failure requires stopping as described below.
Replace `YOUTUBE_URL` with the supplied video URL, retaining the quotes.
List available tracks:

```sh
yt-dlp --ignore-config --no-playlist --skip-download --list-subs 'YOUTUBE_URL'
```

Select one exact language code from the listing rather than downloading every language variant.
For example, if the listing includes `en`, fetch it with:

```sh
yt-dlp --ignore-config --no-playlist --skip-download \
  --write-subs --write-auto-subs --sub-langs 'en' --sub-format vtt \
  --paths '/path/to/scratch' --output '%(id)s.%(ext)s' 'YOUTUBE_URL'
```

Replace `en` when the selected track uses another code.
The two write options allow automatic captions when no supplied track exists for that code.
`--ignore-config` avoids user configuration adding unrelated downloads or postprocessing.
`--no-playlist` limits a video link containing playlist parameters to that video.
Check the subtitle file exists, contains timed text, and covers the requested section.
A successful exit without a subtitle file is not successful retrieval.

Read VTT directly when this fallback is needed.
Account for entities such as `&nbsp;`, inline timing tags, and text carried forward across successive automatic-caption cues.
Distinguish display carry-over from deliberate repeated speech; do not globally deduplicate sentences.
Keep the original VTT and its timestamps rather than silently rewriting the source.

## Read and answer

Read the whole transcript for a discussion of the whole video.
For a question about one passage, read that interval with enough surrounding context to understand it.
Use bounded reads for long files and continue from the last line actually returned.
State the unread range if you cannot finish it; search snippets do not substitute for the rest of the argument.

Ground the answer in the retrieved passage and give timestamps for consequential claims or short quotations.
Say whether you read captions or transcribed audio rather than watched the video.
Automatic captions can mishear names, negation, and technical terms; verify wording before relying on an uncertain exact quote.
Captions may omit on-screen quotations, diagrams, demonstrations, and nonverbal sequences.
Inspect the relevant frames through an available visual workflow when the question depends on them, or identify the specific missing evidence.
Do not infer what a silent interval shows.

For reference extraction, distinguish explicitly cited resources from incidental project mentions.
Label an inferred search match as a candidate until the destination is confirmed.

## Handle retrieval failures

Distinguish no caption track from a failed download, access restriction, or rate limit.
Report the actual error and selected language if neither tool retrieves the requested captions.
For extractor failures, check the installed version and the project's current troubleshooting guidance before retrying.
Do not add browser credentials or bypass access restrictions to repair a public-caption request.
For rate limits, stop requests rather than switching tools to continue them.
Retain any files already retrieved.
If no captions exist and the task is to understand the video, follow [Local audio transcription](references/audio-transcription.md).
Do not make the requester supply a transcript when local transcription can complete the task.
For an existing-subtitles-only request, report that no track exists.
The transcription route preserves the same access and rate-limit stopping conditions.

Missing yt-dlp JavaScript-runtime, impersonation, or media-format warnings do not by themselves establish caption failure.
Check the subtitle result before installing extra runtimes, FFmpeg, or browser tooling.
