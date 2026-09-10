"""Measure configured sandbox TUI initialization without a model request."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import selectors
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runs', type=int, default=3)
parser.add_argument('--timeout', type=float, default=30, help='seconds per run, excluding cleanup')
args = parser.parse_args()
if args.runs < 1 or args.timeout <= 0:
    parser.error('runs and timeout must be positive')
logs = Path(tempfile.mkdtemp(prefix='pi-interactive-'))
fixture = Path(__file__).resolve().parent / 'fixtures' / 'interactive-launcher.py'
print(f'Logs: {logs}', flush=True)

for index in range(args.runs):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
    started = time.monotonic()
    process = subprocess.Popen([sys.executable, str(fixture), '--no-session'],
        stdin=slave, stdout=slave, stderr=slave,
        env={**os.environ, 'CODEX_SANDBOX_TIMING': '1'})
    os.close(slave)
    pending = b''
    lines = b''
    boundaries = []
    ready = False
    try:
        with (logs / f'{index}.log').open('wb') as log, selectors.DefaultSelector() as selector:
            selector.register(master, selectors.EVENT_READ)
            while time.monotonic() - started < args.timeout:
                if not selector.select(0.5):
                    if process.poll() is not None:
                        break
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                log.write(chunk)
                log.flush()
                pending += chunk
                lines += chunk
                while b'\n' in lines:
                    line, lines = lines.split(b'\n', 1)
                    if line.startswith(b'Startup boundary: '):
                        label = line.decode().strip().split(': ', 1)[1]
                        stamp = time.monotonic()
                        clock = 'host receipt'
                        if ' @ ' in label:
                            label, emitted = label.rsplit(' @ ', 1)
                            stamp = float(emitted)
                            clock = 'host emission'
                        boundaries.append({'label': label, 'seconds': stamp - started, 'clock': clock})
                if not ready and b'interactiveMode.init:' in pending:
                    ready = True
                    elapsed = time.monotonic() - started
                    boundaries.append({'label': 'Pi ready', 'seconds': elapsed})
                    (logs / f'{index}.json').write_text(json.dumps(boundaries, indent=2) + '\n')
                    previous = 0
                    for boundary in boundaries:
                        print(f"  {boundary['seconds']:.3f}s (+{boundary['seconds'] - previous:.3f}s) "
                              f"{boundary['label']}", flush=True)
                        previous = boundary['seconds']
                    print(f'Run {index + 1}: observed readiness {elapsed:.3f}s; '
                          f'Pi terminal-drain pause 0.150s; '
                          f'estimate excluding pause {elapsed - 0.150:.3f}s', flush=True)
            assert ready, f'interactive benchmark did not finish; inspect {logs / f"{index}.log"}'
        assert process.wait(timeout=10) == 0
    finally:
        (logs / f'{index}.json').write_text(json.dumps(boundaries, indent=2) + '\n')
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            print('Waiting for launcher cleanup; draining output into the run log.', flush=True)
            # Image builders may still be running. Keep their PTY writable while
            # the launcher joins its workers and removes its owned resources.
            with (logs / f'{index}.log').open('ab') as log, selectors.DefaultSelector() as selector:
                selector.register(master, selectors.EVENT_READ)
                while process.poll() is None:
                    if selector.select(0.5):
                        try:
                            chunk = os.read(master, 65536)
                        except OSError:
                            break
                        if not chunk:
                            break
                        log.write(chunk)
                        log.flush()
                process.wait()
        os.close(master)
