"""Disposable actual-socat proof, NOT a provider probe or a passing regression.

Exit 1 means no tested option set preserves BOTH strict delayed response EOF and
quiet post-request-EOF cancellation. Never treat reset as successful response EOF.
"""
from contextlib import contextmanager
import json
import os
import signal
import socket
import struct
import subprocess
import threading
import time


def wire(value):
    data = json.dumps(value).encode()
    return len(data).to_bytes(4, 'big') + data


def read_exact(connection, size):
    data = bytearray()
    while len(data) < size:
        part = connection.recv(size - len(data))
        if not part:
            raise EOFError(f'EOF after {len(data)} of {size} bytes')
        data.extend(part)
    return bytes(data)


def strict_frame(connection):
    size = int.from_bytes(read_exact(connection, 4), 'big')
    if size > 32 * 1024 * 1024:
        raise ValueError('oversize frame')
    body = read_exact(connection, size)
    if connection.recv(1) != b'':
        raise ValueError('trailing response bytes')
    return json.loads(body)


@contextmanager
def relay(target, close_wait, linger):
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    socket_option = ',linger=0' if linger else ''
    argv = ['socat', '-T', '45', *close_wait,
        f'TCP4-LISTEN:{port},bind=127.0.0.1,reuseaddr,fork{socket_option}',
        f'TCP4:127.0.0.1:{target[1]}{socket_option}']
    process = subprocess.Popen(argv, stderr=subprocess.PIPE, start_new_session=True)
    try:
        until = time.monotonic() + 3
        while True:
            try:
                client = socket.create_connection(('127.0.0.1', port), timeout=5)
                break
            except ConnectionRefusedError:
                if time.monotonic() >= until:
                    raise
                time.sleep(0.01)
        with client:
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            yield client, argv
    finally:
        # This group is a live, exclusively owned disposable socat + fork worker.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()


REQUEST = dict(token='owned-probe-token', request=dict(version=1, command='tic', argv=['list'], stdin=''))
RESPONSE = dict(version=1, exit=0, stdout='x' * (256 * 1024), stderr='')


def delayed_strict_response(close_wait, linger):
    errors = []
    seen_eof = threading.Event()
    with socket.socket() as target:
        target.bind(('127.0.0.1', 0))
        target.listen(5)
        with relay(target.getsockname(), close_wait, linger) as (client, argv):
            def respond():
                try:
                    with target.accept()[0] as upstream:
                        upstream.settimeout(5)
                        assert strict_frame(upstream) == REQUEST
                        seen_eof.set()
                        time.sleep(1.25)  # Explicitly exceeds one second AFTER request EOF.
                        upstream.sendall(wire(RESPONSE))
                        upstream.shutdown(socket.SHUT_WR)
                except BaseException as error:
                    errors.append(repr(error))
            worker = threading.Thread(target=respond)
            worker.start()
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
            client.sendall(wire(REQUEST))
            client.shutdown(socket.SHUT_WR)
            if not seen_eof.wait(timeout=3):
                raise AssertionError('socat did not preserve strict request EOF')
            # Legal bounded receive backpressure: unacknowledged final response
            # bytes must not be discarded by an unconditional abortive close.
            time.sleep(1.6)
            result = dict(argv=argv, kind='delayed_strict_frame_and_eof', response_delay=1.25)
            try:
                response = strict_frame(client)
                result['passed'] = response == RESPONSE
            except BaseException as error:
                result.update(passed=False, downstream_error=repr(error))
            worker.join(timeout=6)
            if worker.is_alive():
                raise AssertionError('owned responder did not finish')
            result['upstream_errors'] = errors
            return result


def quiet_abort(close_wait, linger):
    with socket.socket() as target:
        target.bind(('127.0.0.1', 0))
        target.listen(5)
        with relay(target.getsockname(), close_wait, linger) as (client, argv):
            with target.accept()[0] as upstream:
                upstream.settimeout(3)
                client.sendall(wire(REQUEST))
                client.shutdown(socket.SHUT_WR)
                assert strict_frame(upstream) == REQUEST
                time.sleep(1.25)
                before = upstream.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                client.close()
                after = 0
                until = time.monotonic() + 3
                while not after and time.monotonic() < until:
                    after = upstream.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    time.sleep(0.01)
                return dict(argv=argv, kind='quiet_abort_after_strict_request_eof',
                    error_before_abort=before, error_after_abort=after,
                    passed=not before and bool(after))


def observed_default_close_wait():
    with socket.socket() as target:
        target.bind(('127.0.0.1', 0))
        target.listen(5)
        with relay(target.getsockname(), [], False) as (client, argv):
            with target.accept()[0] as upstream:
                upstream.settimeout(3)
                client.sendall(wire(REQUEST))
                start = time.monotonic()
                client.shutdown(socket.SHUT_WR)
                assert strict_frame(upstream) == REQUEST
                assert client.recv(1) == b''
                return dict(kind='observed_default_first_eof_close_wait',
                            elapsed_seconds=time.monotonic() - start, argv=argv)


print(subprocess.check_output(['socat', '-V'], text=True).splitlines()[1], flush=True)
print(json.dumps(observed_default_close_wait()), flush=True)
help_lines = subprocess.check_output(['socat', '-h'], text=True).splitlines()
print(json.dumps({'installed_help': [line.strip() for line in help_lines if '-t<timeout>' in line or '-T<timeout>' in line]}), flush=True)
results = []
for close_wait, linger in [([], False), ([], True), (['-t', '45'], False), (['-t', '45'], True)]:
    delayed = delayed_strict_response(close_wait, linger)
    print(json.dumps(delayed), flush=True)
    aborted = quiet_abort(close_wait, linger)
    print(json.dumps(aborted), flush=True)
    results.append(delayed['passed'] and aborted['passed'])
print(json.dumps({'required_semantics_proven_by_any_tested_option_set': any(results)}), flush=True)
raise SystemExit(0 if any(results) else 1)
