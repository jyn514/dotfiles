"""Admission envelope for typed authenticated broker protocols."""
from __future__ import annotations

import hmac
import json
from typing import Any


class AdmissionError(ValueError):
    pass


def wrap(token: str, request: bytes) -> bytes:
    """Wrap an already validated typed request without broadening its authority."""
    value = {"token": token, "request": json.loads(request)}
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def unwrap(body: bytes, expected_token: str, *, object_pairs_hook=None) -> bytes:
    try:
        value: Any = json.loads(body, object_pairs_hook=object_pairs_hook)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdmissionError("invalid broker admission envelope") from error
    if not isinstance(value, dict) or set(value) != {"token", "request"}:
        raise AdmissionError("invalid broker admission envelope")
    token = value["token"]
    if not isinstance(token, str) or not hmac.compare_digest(token, expected_token):
        raise AdmissionError("unauthorized broker request")
    return json.dumps(value["request"], ensure_ascii=False, separators=(",", ":")).encode()
