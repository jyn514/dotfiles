#!/usr/bin/env python3
"""Execute one framed read-only Zulip request with host credentials."""

from pathlib import Path
import json
import sys

import server


def main() -> None:
    try:
        endpoint, authorization = server.load_credentials(Path("~/.zuliprc").expanduser())
        request = server.read_frame(sys.stdin.buffer, server.MAX_REQUEST)
        response = server.process_request(request, endpoint, authorization)
    except (OSError, server.RequestError) as error:
        response = json.dumps({"version": 1, "error": str(error)}, separators=(",", ":")).encode()
    server.write_frame(sys.stdout.buffer, response)


if __name__ == "__main__":
    main()
