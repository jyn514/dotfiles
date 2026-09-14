"""Generic, fail-closed machinery for authenticated fixed-origin HTTP routes."""
from __future__ import annotations

from dataclasses import dataclass
from http.client import HTTPSConnection
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import unquote, urlsplit

CHUNK = 64 * 1024
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")

class PolicyError(ValueError): pass
class LimitError(Exception): pass

@dataclass(frozen=True)
class Route:
    name: str
    host: str
    upstream_path: str
    local_path: str
    methods: frozenset[str]
    request_headers: frozenset[str]
    response_headers: frozenset[str]
    max_request_body: int = 32 * 1024 * 1024
    max_response_body: int = 64 * 1024 * 1024
    max_headers: int = 64 * 1024
    timeout: float = 30  # idle I/O timeout
    request_timeout: float = 300
    response_timeout: float = 300
    allow_query: bool = False


def parse_target(target: str, route: Route) -> tuple[str, str]:
    """Parse an origin-form target exactly once and return fixed upstream path/query."""
    if not target.startswith('/') or target.startswith('//') or '#' in target:
        raise PolicyError('malformed request target')
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or parts.fragment:
        raise PolicyError('malformed request target')
    lower = parts.path.lower()
    if re.search(r'%(?![0-9a-fA-F]{2})', parts.path):
        raise PolicyError('malformed path encoding')
    if any(code in lower for code in ('%2f', '%5c', '%00')):
        raise PolicyError('encoded separator')
    try:
        decoded = unquote(parts.path, errors='strict')
    except (UnicodeError, ValueError) as error:
        raise PolicyError('malformed path encoding') from error
    if '\\' in decoded or any(piece in ('.', '..') for piece in decoded.split('/')):
        raise PolicyError('path traversal')
    if decoded != route.local_path:
        raise PolicyError('route not found')
    if '?' in target and not route.allow_query:
        raise PolicyError('query not permitted')
    return route.upstream_path, parts.query


def validate_method(method: str, route: Route) -> None:
    if method not in route.methods:
        raise PolicyError('method not permitted')


def single_header(headers, name: str, *, required: bool = False) -> str | None:
    values = headers.get_all(name, []) if hasattr(headers, 'get_all') else (
        [headers[name]] if name in headers else [])
    if len(values) > 1:
        raise PolicyError('duplicate critical header')
    if required and not values:
        raise PolicyError('missing critical header')
    value = values[0] if values else None
    if value is not None and ('\r' in value or '\n' in value or '\x00' in value):
        raise PolicyError('malformed critical header')
    return value


def request_length(headers, limit: int) -> int:
    transfer = single_header(headers, 'Transfer-Encoding')
    raw = single_header(headers, 'Content-Length', required=True)
    if transfer is not None:
        raise PolicyError('transfer encoding is not accepted')
    try:
        if raw is None or not raw.isascii() or not raw.isdigit(): raise ValueError
        length = int(raw)
    except ValueError as error:
        raise PolicyError('malformed content length') from error
    if length > limit: raise LimitError('request body too large')
    return length


def validate_header(name: str, value: str) -> None:
    if (not isinstance(name, str) or _HEADER_NAME.fullmatch(name) is None
            or not isinstance(value, str)
            or any(character in value for character in ('\r', '\n', '\x00'))):
        raise PolicyError('malformed header')


def filter_request_headers(headers, route: Route) -> dict[str, str]:
    forbidden = {'authorization','proxy-authorization','host','forwarded','via','connection',
                 'transfer-encoding','upgrade','te','trailer','keep-alive'}
    result = {}
    total = 0
    seen: set[str] = set()
    for key, value in headers.items():
        validate_header(key, value)
        lower = key.lower()
        total += len(key) + len(value) + 4
        if total > route.max_headers:
            raise LimitError('request headers too large')
        if lower in forbidden or lower.startswith('x-forwarded-'):
            # Admission, authority, forwarding, and hop-by-hop fields are consumed.
            continue
        if lower not in route.request_headers and lower not in {'content-length'}:
            raise PolicyError('request header not permitted')
        if lower in seen: raise PolicyError('duplicate singleton request header')
        seen.add(lower); result[key] = value
    return result


def public_addresses(host: str, port: int = 443) -> list[tuple]:
    """Resolve once and reject the complete answer if any address is non-global."""
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not answers:
        raise OSError('upstream name has no addresses')
    for answer in answers:
        address = ipaddress.ip_address(answer[4][0])
        if not address.is_global:
            raise PolicyError('upstream resolved to a private or special address')
    return answers


class ResolvedHTTPSConnection(HTTPSConnection):
    """TLS connection pinned to a previously policy-checked DNS answer."""
    def __init__(self, host: str, answers: list[tuple], timeout: float):
        super().__init__(host, timeout=timeout)
        self._answers = answers
    def connect(self):
        error = None
        for family, socktype, proto, _, sockaddr in self._answers:
            raw = socket.socket(family, socktype, proto)
            raw.settimeout(self.timeout)
            try:
                raw.connect(sockaddr)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except OSError as caught:
                error = caught
                raw.close()
        raise error or OSError('connection failed')


def open_upstream(route: Route):
    return ResolvedHTTPSConnection(route.host, public_addresses(route.host), route.timeout)


def response_framing(status: int, headers: list[tuple[str, str]], route: Route) -> tuple[int | None, bool]:
    grouped: dict[str, list[str]] = {}
    for key, value in headers:
        validate_header(key, value)
        grouped.setdefault(key.lower(), []).append(value)
    for name in route.response_headers | {'content-length', 'transfer-encoding'}:
        if len(grouped.get(name, ())) > 1: raise PolicyError('duplicate singleton response header')
    lengths, transfers = grouped.get('content-length', []), grouped.get('transfer-encoding', [])
    if lengths and transfers: raise PolicyError('ambiguous upstream framing')
    if transfers and transfers[0].strip().lower() != 'chunked':
        raise PolicyError('unsupported upstream transfer encoding')
    length = None
    if lengths:
        if not lengths[0].isascii() or not lengths[0].isdigit(): raise PolicyError('malformed upstream content length')
        length = int(lengths[0])
        if length > route.max_response_body: raise LimitError('response body too large')
    no_body = 100 <= status < 200 or status in (204, 205, 304)
    if status == 101: raise PolicyError('protocol upgrade rejected')
    if no_body and (transfers or (length is not None and length != 0)):
        raise PolicyError('payload framing forbidden for response status')
    return length, no_body


def stream_request(connection, method: str, path: str, headers: dict[str,str], source, length: int,
                   limit: int, deadline: float | None = None, downstream_socket=None) -> int:
    """Send exactly length bytes. Once any byte is sent, callers must never retry."""
    if length < 0 or length > limit:
        raise LimitError('invalid request size')
    connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for key, value in headers.items(): connection.putheader(key, value)
    connection.endheaders()
    sent = 0
    while sent < length:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError('total request deadline exceeded')
            if getattr(connection, 'sock', None) is not None:
                connection.sock.settimeout(min(connection.timeout, remaining))
            if downstream_socket is not None:
                downstream_socket.settimeout(min(connection.timeout, remaining))
        chunk = source.read(min(CHUNK, length - sent))
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError('total request deadline exceeded')
        if not chunk:
            raise EOFError('premature request body EOF')
        connection.send(chunk)
        sent += len(chunk)
    return sent
