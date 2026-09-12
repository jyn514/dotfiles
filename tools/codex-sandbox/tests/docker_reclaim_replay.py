"""Replay an isolated Paracress native build/test corpus in the Docker guest."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    log = (args.work / 'replay-results.jsonl').open('w')

    def event(**values):
        values['time'] = time.time()
        print(json.dumps(values), file=log, flush=True)

    def run(*argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout

    prefix = ['docker', 'run', '--rm', '--name', 'reclaim-replay-cycle', '--network=none',
              '--mount', f'type=bind,src={args.work},dst=/replay',
              '--env', 'CARGO_HOME=/replay/cargo-home', '--env', 'BLUSH_SYNTAX_DIR=/replay/syntax',
              '--workdir', '/replay/native', '--entrypoint', 'cargo', args.image]

    def cycle():
        run(*prefix, 'build', '--locked', '--offline')
        output = run(*prefix, 'test', '--locked', '--offline')
        assert 'test result: ok.' in output
        artifact = args.work / 'native/target/debug/libsyntect_bridge.a'
        run('sync', '-f', str(artifact))
        return hashlib.sha256(artifact.read_bytes()).hexdigest()

    durations = {'baseline': [], 'timer': []}
    expected = None
    try:
        for pair in range(3):
            for mode in ('baseline', 'timer'):
                run('systemctl', '--user', 'disable', '--now', 'sandbox-reclaim.timer')
                run('systemctl', '--user', 'stop', 'sandbox-reclaim.service')
                # This is an idle disposable VM. Reset only its guest cache
                # before identical warmup; this is not a production operation.
                run('sync')
                run('sudo', 'sysctl', '-w', 'vm.drop_caches=3')
                digest = cycle()
                expected = expected or digest
                assert digest == expected, 'warmup artifact changed'
                if mode == 'timer':
                    run('systemctl', '--user', 'enable', '--now', 'sandbox-reclaim.timer')
                event(event='start', mode=mode, pair=pair)
                started = time.monotonic()
                for index in range(10):
                    assert cycle() == expected, 'finalized artifact changed'
                elapsed = time.monotonic() - started
                durations[mode].append(elapsed)
                event(event='finish', mode=mode, pair=pair, seconds=elapsed, artifact_sha256=expected,
                      last_trigger=run('systemctl', '--user', 'show', 'sandbox-reclaim.timer',
                                       '--property=LastTriggerUSec', '--value').strip())
        ratio = statistics.median(durations['timer']) / statistics.median(durations['baseline'])
        pairs = [new / old for old, new in zip(durations['baseline'], durations['timer'])]
        event(event='cost', median_ratio=ratio, pair_ratios=pairs,
              passed=ratio <= 1.10 and all(value <= 1.20 for value in pairs))
    finally:
        run('systemctl', '--user', 'disable', '--now', 'sandbox-reclaim.timer')
        run('systemctl', '--user', 'stop', 'sandbox-reclaim.service')
        log.close()


if __name__ == '__main__':
    main()
