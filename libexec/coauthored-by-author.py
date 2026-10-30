# git-filter-repo --commit-callback body; `commit` is supplied by its caller.
import json
import os
import re
import subprocess

with open(os.environ["COAUTHORED_BY_AUTHOR_DATA"], encoding="utf-8") as data_file:
    data = json.load(data_file)
author = data["authors"].get(commit.original_id.decode("ascii"))
if author:
    message = commit.message
    if not data["keep-trailer"]:
        trailer_value = ("%s <%s>" % (author["name"], author["email"])).encode("utf-8")
        # Git's locale-independent whitespace is SPACE, TAB, CR, and LF.
        pattern = re.compile(
            rb"(?im)^Co-Authored-By:[ \t]*(?P<value>" + re.escape(trailer_value)
            + rb")(?P<space>[ \t\r]*)(?=\n|$)\n?"
        )
        marker = b"coauthored-by-author-marker"
        while any(prefix + marker in message for prefix in (b"A", b"B")):
            marker += b"-"
        parts = []
        end = 0
        for match in pattern.finditer(message):
            # Preserve the entire physical line prefix, including any configured
            # comment prefix. Git forbids newlines in core.commentString: a
            # longer prefix can newly match at most one of these A/B extensions.
            # Probe original bytes, since deletion can promote an earlier block.
            line_end = match.end("space")
            for prefix in (b"A", b"B"):
                extension = prefix + marker
                probe = message[:line_end] + extension + message[line_end:]
                parsed = subprocess.run(
                    ["git", "interpret-trailers", "--parse"], input=probe, stdout=subprocess.PIPE
                )
                parsed.check_returncode()
                fields = (line.partition(b":") for line in parsed.stdout.split(b"\n"))
                augmented_value = match.group("value") + match.group("space") + extension
                if any(key.lower() == b"co-authored-by" and value.lstrip(b" \t") == augmented_value
                       for key, _, value in fields):
                    parts.append(message[end:match.start()])
                    end = match.end()
                    break
        message = b"".join(parts) + message[end:]
        message = re.sub(rb"\n{3,}$", b"\n\n", message)
    commit.author_name = author["name"].encode("utf-8")
    commit.author_email = author["email"].encode("utf-8")
    commit.message = message
