"""Exercise host API supervision with disposable Docker containers."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docker_runtime import Docker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--image')
    parser.add_argument('--monitor')
    args = parser.parse_args()
    runtime = Docker(args.state)
    if args.monitor:
        return runtime.monitor(json.loads(args.monitor))
    image = runtime.inspect_image(args.image)
    for outcome in ('agent', 'proxy', 'cancel', 'lost-monitor'):
        prefix = 'docker-monitor-test-' + uuid.uuid4().hex[:12]
        containers = [('agent', prefix + '-agent'), ('proxy', prefix + '-proxy')]
        process = None
        try:
            for _, name in containers:
                runtime.run(['run', '-d', '--name', name, '--network', 'none',
                             '--entrypoint', 'sleep', image.config, '300'], stdout=subprocess.DEVNULL)
            process = subprocess.Popen([sys.executable, __file__, '--state', str(args.state),
                                        '--monitor', json.dumps(containers)], start_new_session=True)
            # Wait for both host API wait clients before triggering the event.
            deadline = time.monotonic() + 20
            while True:
                listing = subprocess.run(['ps', '-axo', 'pgid=,command='], check=True,
                                         capture_output=True, text=True).stdout.splitlines()
                owned = [line for line in listing if line.split(None, 1)[0] == str(process.pid)]
                if all(any(' wait ' + name in line for line in owned) for _, name in containers):
                    break
                assert process.poll() is None
                assert time.monotonic() < deadline, 'monitor did not register waits'
                time.sleep(0.1)
            if outcome == 'cancel':
                process.terminate()
            elif outcome == 'lost-monitor':
                process.kill()
                process.wait(timeout=10)
                os.killpg(process.pid, signal.SIGTERM)
            else:
                runtime.run(['kill', containers[0 if outcome == 'agent' else 1][1]], stdout=subprocess.DEVNULL)
            assert process.wait(timeout=30) == {'agent': 0, 'proxy': 1, 'cancel': 143, 'lost-monitor': -9}[outcome]
            deadline = time.monotonic() + 5
            while True:
                listing = subprocess.run(['ps', '-axo', 'pgid=,command='], check=True,
                                         capture_output=True, text=True).stdout.splitlines()
                if not any(line.split(None, 1)[0] == str(process.pid) for line in listing):
                    break
                assert time.monotonic() < deadline, 'orphaned Docker waits'
                time.sleep(0.1)
            if outcome == 'proxy':
                assert runtime.run(['inspect', containers[0][1]], check=False, capture_output=True).returncode != 0
            print('PASS: monitor', outcome, flush=True)
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            for _, name in containers:
                runtime.run(['rm', '-f', name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    raise SystemExit(main())
