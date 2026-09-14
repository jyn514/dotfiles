"""Installed Codex OAuth credential profile (not repository configurable)."""
from __future__ import annotations
import base64, fcntl, json, os, tempfile, threading, time
from http import HTTPStatus
from http.client import HTTPSConnection
from pathlib import Path
from urllib.parse import urlencode
import importlib.util, sys
_spec = importlib.util.spec_from_file_location('broker', Path(__file__).with_name('broker.py'))
broker = sys.modules.get('broker')
if broker is None:
    broker = importlib.util.module_from_spec(_spec); sys.modules['broker'] = broker; _spec.loader.exec_module(broker)

AUTH = Path('/var/lib/codex-auth/auth.json')
CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann'
TOKEN_HOST = 'auth.openai.com'
TOKEN_PATH = '/oauth/token'
REFRESH_LOCK = threading.Lock()

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

def credentials():
    with REFRESH_LOCK, (AUTH.parent / 'refresh.lock').open('a+b') as lock:
        os.chmod(lock.name, 0o600); fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_auth(); tokens = data['tokens']; access = tokens['access_token']
        try: expires = int(jwt_payload(access)['exp'])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError): expires = 0
        if expires <= time.time() + 60:
            body = urlencode({'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_id':CLIENT_ID}).encode()
            refresh_route = broker.Route('codex-refresh', TOKEN_HOST, TOKEN_PATH, TOKEN_PATH,
                                         frozenset({'POST'}), frozenset(), frozenset(), timeout=30,
                                         request_timeout=30, response_timeout=30)
            deadline = time.monotonic() + 30
            connection = broker.open_upstream(refresh_route)
            try:
                remaining=deadline-time.monotonic()
                if remaining <= 0: raise TimeoutError('Codex token refresh deadline exceeded')
                connection.timeout=min(connection.timeout,remaining)
                connection.connect()
                if getattr(connection, 'sock', None) is not None:
                    connection.sock.settimeout(min(30, deadline-time.monotonic()))
                connection.request('POST', TOKEN_PATH, body, {'Content-Type':'application/x-www-form-urlencoded','Content-Length':str(len(body))})
                if deadline-time.monotonic() <= 0: raise TimeoutError('Codex token refresh deadline exceeded')
                if getattr(connection, 'sock', None) is not None:
                    connection.sock.settimeout(min(30, deadline-time.monotonic()))
                response = connection.getresponse(); chunks=[]; size=0
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining <= 0: raise TimeoutError('Codex token refresh deadline exceeded')
                    if getattr(connection, 'sock', None) is not None: connection.sock.settimeout(min(30,remaining))
                    one_shot=False
                    try: chunk=response.read(min(64*1024,1024*1024+1-size))
                    except TypeError: chunk=response.read(); one_shot=True # simple test doubles
                    if not chunk: break
                    chunks.append(chunk); size += len(chunk)
                    if one_shot or size > 1024*1024: break
                payload=b''.join(chunks)
            finally: connection.close()
            if response.status != HTTPStatus.OK: raise RuntimeError(f'Codex token refresh failed ({response.status})')
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
        return access, account
