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
        # Raw envelopes only: Git owns continuation unfolding and membership.
        # Do not include blank separator lines in a possible removal span.
        pattern = re.compile(
            rb"(?im)^Co-Authored-By[^\n]*(?:\n[ \t\r]+(?=[^ \t\r\n])[^\n]*)*\n?"
        )
        identity = re.compile(
            re.escape(author["name"].encode("utf-8")) + rb"[ \t\r]*<"
            + re.escape(author["email"].encode("utf-8")) + rb">", re.I
        )
        marker = b"coauthored-by-author-marker"
        while any(prefix + marker in message for prefix in (b"A", b"B")):
            marker += b"-"
        parts = []
        end = 0
        for match in pattern.finditer(message):
            # Preserve complete physical prefixes, including comment strings.
            # First/last markers must belong to one native logical field. Since
            # commentString cannot contain LF, a newly colliding prefix cannot
            # match both A/B extensions (nor both a token and an indented line).
            # Always probe original bytes: deletion can promote an earlier block.
            first_end = message.find(b"\n", match.start(), match.end())
            if first_end < 0:
                first_end = match.end()
            last_end = match.end() - (message[match.end() - 1:match.end()] == b"\n")
            for prefix in (b"A", b"B"):
                start_marker = prefix + marker + b"-start"
                end_marker = prefix + marker + b"-end"
                probe = (message[:first_end] + start_marker + message[first_end:last_end]
                         + end_marker + message[last_end:])
                parsed = subprocess.run(
                    ["git", "interpret-trailers", "--parse"], input=probe, stdout=subprocess.PIPE
                )
                parsed.check_returncode()
                admitted = False
                for field in parsed.stdout.split(b"\n"):
                    key, _, value = field.partition(b":")
                    if key.lower() != b"co-authored-by" or start_marker not in value or end_marker not in value:
                        continue
                    # Markers can expose whitespace Git originally trimmed at
                    # the logical value's edges; its whitespace table is ASCII.
                    value = value.replace(start_marker, b"").replace(end_marker, b"").strip(b" \t\r")
                    if identity.fullmatch(value):
                        admitted = True
                        break
                if admitted:
                    parts.append(message[end:match.start()])
                    end = match.end()
                    break
        message = b"".join(parts) + message[end:]
        message = re.sub(rb"\n{3,}$", b"\n\n", message)
    commit.author_name = author["name"].encode("utf-8")
    commit.author_email = author["email"].encode("utf-8")
    commit.message = message
