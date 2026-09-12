"""Per-launch Flower R2 capability. Secrets never enter relay diagnostics."""

import json
import os
import secrets
import select
import signal
import socket
import struct
import subprocess
import threading
import time


REQUEST_SECONDS = 5
READ_SECONDS = 120
SEND_SECONDS = 5
OVERALL_SECONDS = 250
MAX_CREDENTIAL = 4096
UNAVAILABLE = {'version': 1, 'status': 'unavailable'}


class Unavailable(Exception):
    """A terminal request failure with no credential-bearing detail."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unavailable()
        result[key] = value
    return result


class HostKeychainBridge:
    def __init__(self):
        self.token = secrets.token_hex(32)
        self.port = None
        self.listener = None
        self.thread = None
        self.worker = None
        self.stopping = threading.Event()
        self.peer_lock = threading.Lock()
        self.peers = frozenset()

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Like HostEditorBridge, the host bind must work across VM runtimes.
            # Peers and a separate capability authenticate this wildcard bind.
            listener.bind(('0.0.0.0', 0))
            listener.listen(1)
            listener.settimeout(.05)
        except BaseException:
            listener.close()
            raise
        self.listener = listener
        self.port = listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, name='host-keychain-accept')
        self.thread.start()

    def allow_peers(self, peers):
        with self.peer_lock:
            self.peers = frozenset(peers)

    def stop(self):
        self.stopping.set()
        if self.listener is not None:
            self.listener.close()
        if self.thread is not None:
            self.thread.join()
        if self.worker is not None:
            self.worker.join()
        self.token = ''

    def _serve(self):
        while not self.stopping.is_set():
            try:
                connection, address = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with self.peer_lock:
                allowed = address[0] in self.peers
            if (not allowed or self.stopping.is_set() or
                    (self.worker is not None and self.worker.is_alive())):
                connection.close()
                continue
            if self.worker is not None:
                self.worker.join()
            self.worker = threading.Thread(target=self._handle, args=(connection,),
                                           name='host-keychain-request')
            self.worker.start()

    def _check(self, deadline):
        if self.stopping.is_set() or time.monotonic() >= deadline:
            raise Unavailable()

    def _receive(self, connection, size, deadline):
        data = bytearray()
        while len(data) < size:
            self._check(deadline)
            readable, _, _ = select.select([connection], [], [], .05)
            if readable:
                part = connection.recv(size - len(data))
                if not part:
                    raise Unavailable()
                data.extend(part)
        return data

    def _connected(self, connection, deadline):
        self._check(deadline)
        # No further guest bytes are legal. Both EOF and unexpected data abort.
        if select.select([connection], [], [], 0)[0]:
            raise Unavailable()

    @staticmethod
    def _kill_group(child, signum):
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass

    def _read(self, account, connection, overall):
        self._connected(connection, overall)
        deadline = min(overall - 2, time.monotonic() + READ_SECONDS)
        self._check(deadline)
        child = subprocess.Popen([
            '/usr/bin/security', 'find-generic-password', '-s', 'dev.jyn.flower.r2',
            '-a', account, '-w'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env={'PATH': '/usr/bin:/bin'}, start_new_session=True)
        output = bytearray()
        try:
            os.set_blocking(child.stdout.fileno(), False)
            eof = False
            while not eof or child.poll() is None:
                self._connected(connection, deadline)
                readable, _, _ = select.select([child.stdout] if not eof else [], [], [], .05)
                if readable:
                    part = os.read(child.stdout.fileno(), MAX_CREDENTIAL + 3)
                    if not part:
                        eof = True
                    output.extend(part)
                    if len(output) > MAX_CREDENTIAL + 2:
                        raise Unavailable()
            if child.returncode != 0:
                raise Unavailable()
            if output.endswith(b'\r\n'):
                del output[-2:]
            elif output.endswith(b'\n'):
                del output[-1:]
            if not 1 <= len(output) <= MAX_CREDENTIAL or b'\0' in output:
                raise Unavailable()
            return output.decode('utf-8')
        finally:
            # Own the entire group, including descendants left after parent exit.
            self._kill_group(child, signal.SIGTERM)
            try:
                child.wait(timeout=max(0, min(2, overall - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
            self._kill_group(child, signal.SIGKILL)
            child.wait()
            child.stdout.close()
            output[:] = b'\0' * len(output)

    def _handle(self, connection):
        overall = time.monotonic() + OVERALL_SECONDS
        response = UNAVAILABLE
        with connection:
            try:
                deadline = min(overall, time.monotonic() + REQUEST_SECONDS)
                length = struct.unpack('>I', self._receive(connection, 4, deadline))[0]
                if not 0 < length <= 4096:
                    raise Unavailable()
                request = json.loads(self._receive(connection, length, deadline).decode('utf-8'),
                                     object_pairs_hook=unique_object)
                if (not isinstance(request, dict) or set(request) != {'version', 'token', 'operation'}
                        or type(request['version']) is not int or request['version'] != 1
                        or request['operation'] != 'flower-r2/read'
                        or not isinstance(request['token'], str)
                        or not secrets.compare_digest(request['token'].encode(), self.token.encode())):
                    raise Unavailable()
                access = self._read('access-key', connection, overall)
                secret = self._read('secret-key', connection, overall)
                self._connected(connection, overall)
                response = {'version': 1, 'status': 'ok', 'access_key': access, 'secret_key': secret}
            except (Unavailable, OSError, ValueError, RecursionError, struct.error):
                # Exception text and security output never cross this boundary.
                response = UNAVAILABLE
            try:
                payload = json.dumps(response, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                if len(payload) > 12288:
                    payload = json.dumps(UNAVAILABLE).encode()
                pending = memoryview(struct.pack('>I', len(payload)) + payload)
                deadline = min(overall, time.monotonic() + SEND_SECONDS)
                connection.setblocking(False)
                while pending:
                    self._check(deadline)
                    if select.select([], [connection], [], .05)[1]:
                        sent = connection.send(pending)
                        if not sent:
                            break
                        pending = pending[sent:]
            except (Unavailable, OSError):
                pass
