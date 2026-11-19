# Local audio transcription

Use this route when a request requires understanding a video's spoken content and neither caption tool finds a track.
For example, extracting references from an uncaptained interview still requires reading the interview; reporting missing captions does not supply the references.
Keep downloads, models, and intermediate transcripts in owned disposable storage.
Use local transcription rather than sending the audio to an external transcription service without authorization.
Stop on access restrictions or rate limits rather than using audio retrieval to get around them.

## Choose a compatible tool

Check the available tools and platform before selecting a speech-to-text package.
Prefer an installed compatible tool or a package available through the environment's existing package manager.
If a Python package has no compatible wheels, consider a native tool such as whisper.cpp instead of repeatedly trying package versions.
Install missing tools only in the disposable environment; do not change host setup for a video-reading task.

[whisper.cpp](https://github.com/ggml-org/whisper.cpp) provides a local CPU transcription route.
Check the installed `whisper-cli --help` and `ffmpeg -h` before adapting the examples below.
Obtain a compatible model using the [upstream model instructions](https://github.com/ggml-org/whisper.cpp/tree/master/models).
Choose a model for the spoken language and required accuracy; `base.en` is an English-only example, not a multilingual default.
For a long recording, try a short representative passage before the full run to check recognition and processing speed.
Do not turn model tuning into a prerequisite for producing a useful transcript.

## Retrieve and transcribe audio

Select an audio-only format using `yt-dlp` and keep the download scoped to the supplied video:

```sh
yt-dlp --ignore-config --no-playlist -f bestaudio \
  --paths '/path/to/scratch' --output 'audio.%(ext)s' 'YOUTUBE_URL'
```

Use the actual downloaded filename in subsequent commands.
For a livestream replay that needs retrieval from the beginning, use `--live-from-start` where supported.
Without it, a live download can start at the current position and omit earlier references.

Convert the recovered audio to a format accepted by the transcription tool:

```sh
ffmpeg -nostdin -i '/path/to/scratch/audio.m4a' \
  -ar 16000 -ac 1 -c:a pcm_s16le '/path/to/scratch/audio.wav'

whisper-cli -m '/path/to/model/ggml-base.en.bin' \
  -f '/path/to/scratch/audio.wav' -ng -otxt -osrt \
  -of '/path/to/scratch/transcript'
```

Keep timestamped output as well as readable text.
Check that both contain recognized speech before reading the transcript for the requested result.
Treat names, URLs, titles, and quotations as recognition hypotheses until checked.
Re-transcribe uncertain passages with a more accurate model or verify the destination directly when the task depends on exact wording.
When the task permits descriptions of unresolved references, retain the uncertainty rather than inventing a URL.

## Establish the recovered coverage

A live-status field describes the platform's reported state, not the completeness of the recovered recording.
A stream can remain marked live after the spoken conversation ends.
A download stopped by a timeout can also produce a playable file containing only the beginning.

Inspect the recovered audio's duration, first speech, and last speech against the requested interval.
For example, an interview that reaches a closing goodbye supplies evidence of its conversational ending even if metadata still reports `is_live`.
A file ending in the middle of an answer needs further retrieval before claiming whole-interview coverage.
Check downloader warnings and any reported missing fragments for gaps in the requested material.
A successful process exit or a readable transcript alone does not establish full coverage.

For a genuinely ongoing stream, use the requested interval; if none is specified, report the recovered cutoff instead of waiting indefinitely.
State any missing beginning, ending, or internal interval that limits the result.
Preserve the source URL, recovered coverage, and transcription method with the requested output.
Then return to [Read and answer](../SKILL.md#read-and-answer) in the main workflow.
