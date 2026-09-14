"""Installed Codex OAuth credential profile (not repository configurable)."""
from __future__ import annotations
import base64, fcntl, ipaddress, json, multiprocessing, os, socket, tempfile, threading, time
from http import HTTPStatus
from http.client import HTTPSConnection
from pathlib import Path
from urllib.parse import urlencode

AUTH = Path('/var/lib/codex-auth/auth.json')
CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann'
TOKEN_HOST = 'auth.openai.com'
TOKEN_PATH = '/oauth/token'
REFRESH_LOCK = threading.Lock()
MAX_TOKEN_RESPONSE = 1024 * 1024


def _resolve_in_child(writer) -> None:
    try:
        answers = socket.getaddrinfo(TOKEN_HOST, 443, type=socket.SOCK_STREAM)
        writer.send(('ok', answers))
    except BaseException as error:
        writer.send(('error', type(error).__name__, str(error)))
    finally:
        writer.close()


def _public_addresses(deadline: float) -> list[tuple]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Codex token refresh deadline exceeded')
    reader, writer = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.Process(target=_resolve_in_child, args=(writer,), daemon=True)
    started = False
    try:
        process.start(); started = True; writer.close()
        if not reader.poll(remaining):
            raise TimeoutError('OAuth host resolution deadline exceeded')
        result = reader.recv()
    finally:
        reader.close(); writer.close()
        if started:
            if process.is_alive():
                process.kill()
            process.join()
    if (not isinstance(result, tuple) or not result):
        raise OSError('OAuth host resolution returned malformed data')
    if result[0] == 'error' and len(result) == 3 and all(isinstance(x, str) for x in result[1:]):
        raise OSError(f'OAuth host resolution failed ({result[1]}): {result[2]}')
    if result[0] != 'ok' or len(result) != 2 or not isinstance(result[1], list):
        raise OSError('OAuth host resolution returned malformed data')
    answers = result[1]
    for answer in answers:
        if (not isinstance(answer, tuple) or len(answer) != 5
                or answer[0] not in (socket.AF_INET, socket.AF_INET6)
                or answer[1] != socket.SOCK_STREAM or not isinstance(answer[2], int)
                or not isinstance(answer[4], tuple) or len(answer[4]) < 2
                or not isinstance(answer[4][0], str) or answer[4][1] != 443):
            raise OSError('OAuth host resolution returned malformed data')
    if not answers:
        raise OSError('OAuth host has no addresses')
    if any(not ipaddress.ip_address(answer[4][0]).is_global for answer in answers):
        raise RuntimeError('OAuth host resolved to a private or special address')
    return answers


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, timeout: float, deadline: float):
        super().__init__(TOKEN_HOST, 443, timeout=timeout)
        self._answers = _public_addresses(deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Codex token refresh deadline exceeded')
        self.timeout = min(self.timeout, remaining)

    def connect(self) -> None:
        error = None
        for family, socktype, proto, _, sockaddr in self._answers:
            raw = socket.socket(family, socktype, proto)
            raw.settimeout(self.timeout)
            try:
                raw.connect(sockaddr)
                self.sock = self._context.wrap_socket(raw, server_hostname=TOKEN_HOST)
                return
            except OSError as caught:
                error = caught
                raw.close()
        raise error or OSError('OAuth host is unreachable')


def _post_token(body: bytes, deadline: float) -> tuple[int, bytes]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Codex token refresh deadline exceeded')
    connection = _PinnedHTTPSConnection(min(30, remaining), deadline)
    try:
        connection.request('POST', TOKEN_PATH, body, {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Content-Length': str(len(body)),
        })
        response = connection.getresponse()
        declared = response.getheader('Content-Length')
        if declared is not None:
            if not declared.isascii() or not declared.isdecimal():
                raise RuntimeError('Codex token refresh response framing is malformed')
            if int(declared) > MAX_TOKEN_RESPONSE:
                raise RuntimeError('Codex token refresh response too large')
        payload = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Codex token refresh deadline exceeded')
            if connection.sock is not None:
                connection.sock.settimeout(min(30, remaining))
            chunk = response.read(min(64 * 1024, MAX_TOKEN_RESPONSE + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_TOKEN_RESPONSE:
                raise RuntimeError('Codex token refresh response too large')
        return response.status, bytes(payload)
    finally:
        connection.close()

def jwt_payload(token):
    fields = token.split('.')
    if len(fields) != 3: raise ValueError('malformed access token')
    part = fields[1] + '=' * (-len(fields[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(part))

def read_auth():
    data = json.loads(AUTH.read_text(encoding='utf-8'))
    tokens = data.get('tokens')
    if not isinstance(tokens, dict) or any(
        not isinstance(tokens.get(name), str) or not tokens.get(name)
        for name in ('access_token', 'refresh_token')
    ):
        raise RuntimeError('Codex authentication is missing OAuth tokens')
    if 'id_token' in tokens and not isinstance(tokens['id_token'], str):
        raise RuntimeError('Codex id token is malformed')
    return data

def atomic_auth(data):
    descriptor, name = tempfile.mkstemp(prefix='.auth.', dir=AUTH.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, separators=(',', ':')); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, 0o600); os.replace(temporary, AUTH)
        directory = os.open(AUTH.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally: temporary.unlink(missing_ok=True)

def credentials(*, deadline=None):
    deadline = time.monotonic() + 30 if deadline is None else deadline
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not REFRESH_LOCK.acquire(timeout=remaining):
        raise TimeoutError('Codex credential deadline exceeded')
    try:
      with (AUTH.parent / 'refresh.lock').open('a+b') as lock:
        os.chmod(lock.name, 0o600)
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise TimeoutError('Codex credential deadline exceeded')
                time.sleep(min(.05, max(0, deadline-time.monotonic())))
        if time.monotonic() >= deadline: raise TimeoutError('Codex credential deadline exceeded')
        data = read_auth(); tokens = data['tokens']; access = tokens['access_token']
        try: expires = int(jwt_payload(access)['exp'])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError): expires = 0
        if expires <= time.time() + 60:
            body = urlencode({'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_id':CLIENT_ID}).encode()
            status, payload = _post_token(body, deadline)
            if status != HTTPStatus.OK: raise RuntimeError(f'Codex token refresh failed ({status})')
            if len(payload) > 1024 * 1024: raise RuntimeError('Codex token refresh response too large')
            refreshed = json.loads(payload)
            access_value, refresh_value = refreshed.get('access_token'), refreshed.get('refresh_token')
            if not isinstance(access_value, str) or not access_value or not isinstance(refresh_value, str) or not refresh_value:
                raise RuntimeError('Codex token refresh response is incomplete')
            if 'id_token' in refreshed and not isinstance(refreshed['id_token'], str):
                raise RuntimeError('Codex token refresh id token is malformed')
            claims = jwt_payload(access_value)
            if not isinstance(claims.get('exp'), (int, float)):
                raise RuntimeError('Codex access token expiry is malformed')
            auth_claim = claims.get('https://api.openai.com/auth')
            claimed_account = auth_claim.get('chatgpt_account_id') if isinstance(auth_claim, dict) else None
            existing_account = tokens.get('account_id')
            if existing_account is not None and (not isinstance(existing_account, str) or not existing_account):
                raise RuntimeError('Codex account is malformed')
            if existing_account and claimed_account != existing_account:
                raise RuntimeError('Codex token refresh changed account identity')
            if not existing_account and (not isinstance(claimed_account, str) or not claimed_account):
                raise RuntimeError('Codex access token account is malformed')
            # Mutate and publish only after the complete response validates.
            access = access_value; replacement = dict(tokens)
            replacement.update(access_token=access, refresh_token=refresh_value)
            if refreshed.get('id_token'): replacement['id_token'] = refreshed['id_token']
            data = dict(data); data['tokens'] = replacement
            data['last_refresh'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            atomic_auth(data); tokens = replacement
        claims = jwt_payload(access)
        if not isinstance(claims.get('exp'), (int, float)):
            raise RuntimeError('Codex access token expiry is malformed')
        account = tokens.get('account_id')
        if account is None:
            auth_claim = claims.get('https://api.openai.com/auth')
            account = auth_claim.get('chatgpt_account_id') if isinstance(auth_claim, dict) else None
        if not isinstance(account, str) or not account:
            raise RuntimeError('Codex account is malformed')
        if time.monotonic() >= deadline: raise TimeoutError('Codex credential deadline exceeded')
        return access, account
    finally:
        REFRESH_LOCK.release()
