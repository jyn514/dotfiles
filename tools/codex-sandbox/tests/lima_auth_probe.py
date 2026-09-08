"""Exercise sidecar authentication without sending any upstream request."""

import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


url = os.environ["CODEX_SIDECAR_URL"]
assert not Path("/var/lib/codex-auth/auth.json").exists()
with urlopen(url + "/health", timeout=10) as response:
    assert response.read() == b"ok\n"
for key, expected in (("wrong-key", 401), (os.environ["CODEX_SIDECAR_KEY"], 413)):
    # Rejection happens before reading credentials or contacting the upstream.
    request = Request(url + "/codex/responses", data=b"",
                      headers={"Authorization": "Bearer " + key, "Content-Length": "999999999"})
    try:
        urlopen(request, timeout=10)
    except HTTPError as error:
        assert error.code == expected, error.code
    else:
        raise AssertionError("sidecar accepted the invalid request")
print("Isolated Codex sidecar authenticated without an upstream request.")
