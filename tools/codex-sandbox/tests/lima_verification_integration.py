"""Verification reuse and owned bind checks against an already provisioned Lima host."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lima.host import Host
from sandbox_runtime import Lima, verification_scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path.home() / '.local/state/codex-sandbox-lima')
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    verified = []
    original = Host.verify

    def verify(host, record, **kwargs):
        verified.append(record['instance'])
        return original(host, record, **kwargs)

    with patch.object(Host, 'verify', verify):
        if args.child:
            runtime = Lima(args.state)
            runtime.verify()
            runtime.host.check_bind(Path(__file__).resolve())
            assert not verified, 'child repeated full verification'
            return
        with verification_scope():
            runtime = Lima(args.state)
            start = time.monotonic()
            for _ in range(5):
                runtime.host.verify(runtime.record, quiet=True)
            full = (time.monotonic() - start) / 5
            verified.clear()
            start = time.monotonic()
            for _ in range(5):
                runtime.verify()
            reused = (time.monotonic() - start) / 5
            assert not verified, 'unchanged runtime repeated full verification'
            # Preflight, build inputs, and environment staging all use this
            # path; timing verify() alone would miss a full-check bypass here.
            sources = [Path(__file__).resolve(), Path(__file__).resolve().parent]
            start = time.monotonic()
            with patch.object(Host, 'verify_runtime', lambda host, record: original(host, record, quiet=True)):
                for source in sources:
                    runtime.host.check_bind(source)
            full_binds = time.monotonic() - start
            start = time.monotonic()
            for source in sources:
                runtime.host.check_bind(source)
            reused_binds = time.monotonic() - start
            assert not verified, 'bind preflight repeated full verification'
            with tempfile.TemporaryDirectory(dir=runtime.host.state / 'scratch') as temporary:
                directory = Path(temporary)
                file = directory / "literal ' $() name"
                file.write_text('batch content')
                bindings = runtime.host.check_binds([(directory, True), (file, False), (file, True)])
                assert [item['writable'] for item in bindings] == [True, False, True]
                # The host normally supplies matching hashes. Deliberately
                # send a wrong final hash to exercise failure in the real guest.
                source = (Path(__file__).resolve().parents[1] / 'lima/check-binds.py').read_text()
                request = [
                    {'source': str(directory), 'kind': 'directory', 'writable': True},
                    {'source': str(file), 'kind': 'file', 'writable': False,
                     'sha256': hashlib.sha256(b'different content').hexdigest()},
                ]
                try:
                    runtime.guest(['python3', '-c', source], input=json.dumps(request),
                        text=True, capture_output=True)
                except subprocess.CalledProcessError as error:
                    assert 'differs from the host' in error.stderr
                else:
                    raise AssertionError('guest accepted an invalid final bind')
            subprocess.run([sys.executable, str(Path(__file__).resolve()),
                '--state', str(args.state), '--child'], check=True)
            # New/nested launches discard the receipt inherited from a parent.
            with verification_scope():
                Lima(args.state)
            assert len(verified) == 1, 'new launch did not fully verify'
            runtime.verify()
            assert len(verified) == 1, 'nested launch lost parent verification'
        print(f'PASS: child reuse and fresh launch verification; '
              f'full mean {full:.3f}s, reused mean {reused:.3f}s (5 warm checks each); '
              f'two binds full {full_binds:.3f}s, reused {reused_binds:.3f}s')


if __name__ == '__main__':
    main()
