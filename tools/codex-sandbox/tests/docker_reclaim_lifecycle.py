"""Temporarily install candidate units in an idle, caller-owned Docker guest.

Run through limactl shell in a disposable instance, passing its host.json.
Original guest files are restored even when a lifecycle assertion fails.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'lima/docker'
BASE = Path('/usr/local/share/codex-sandbox')


def run(*args, check=True, **kwargs):
    result = subprocess.run(list(map(str, args)), capture_output=True,
                            text=True, timeout=kwargs.pop('timeout', 45), **kwargs)
    if check and result.returncode:
        print(result.stdout + result.stderr, file=sys.stderr, flush=True)
        result.check_returncode()
    return result


def systemctl(*args, **kwargs):
    if args in (('start', 'docker.service'), ('restart', 'docker.service')):
        # Deliberately rapid fixture transitions must not spend Docker's
        # production restart allowance (three starts per minute).
        run('systemctl', '--user', 'reset-failed', 'docker.service')
    return run('systemctl', '--user', *args, **kwargs)


def value(unit, property):
    return systemctl('show', unit, '--property=' + property, '--value').stdout.strip()


def wait_for(predicate, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True, help='host.json path, or - for stdin')
    parser.add_argument('--image', required=True, help='local image containing python3')
    parser.add_argument('--work', required=True, type=Path, help='writable fixture share')
    parser.add_argument('--replay-image', help='also run the prepared Paracress corpus offline')
    args = parser.parse_args()
    record = json.load(sys.stdin) if args.record == '-' else json.loads(Path(args.record).read_text())
    assert record['instance'].startswith('sandbox-host-docker-')
    assert record['generation'] == os.environ['SANDBOX_GENERATION']
    assert not run('docker', 'ps', '-q').stdout.strip(), 'fixture has workloads'
    home = Path.home() / '.config/systemd/user'
    timer, service = 'sandbox-reclaim.timer', 'sandbox-reclaim.service'
    files = {'docker-daemon.json': 'daemon.json', 'docker-user.py': 'configure-user.py',
             'docker-policy.py': 'policy.py', 'docker-reclaim.py': 'reclaim.py',
             **{name: name for name in ('docker-service.conf', 'sandbox.slice', service, timer)}}
    targets = [*[BASE / name for name in files], home / 'docker.service.d/sandbox.conf',
               *[home / name for name in ('sandbox.slice', service, timer)]]
    backup = Path(tempfile.mkdtemp(prefix='reclaim-lifecycle-'))
    saved = {}
    timer_override = Path(f'/run/user/{os.getuid()}/systemd/user/{timer}.d')
    service_override = timer_override.with_name(service + '.d')
    assert not timer_override.exists() and not service_override.exists()
    assert not (home / 'docker.service.wants' / timer).exists()
    try:
        for index, target in enumerate(targets):
            saved[target] = backup / str(index) if target.exists() else None
            if target.exists():
                run('sudo', 'cp', '-p', target, saved[target])
        for name, source in files.items():
            run('sudo', 'install', '-m', '0644', SOURCE / source, BASE / name)
            record['files'][name] = hashlib.sha256((SOURCE / source).read_bytes()).hexdigest()
        systemctl('reset-failed', 'docker.service')
        run('python3', BASE / 'docker-user.py')
        run('systemd-analyze', '--user', 'verify', home / 'sandbox.slice', home / service, home / timer)
        run('python3', BASE / 'docker-policy.py', 'check', input=json.dumps(record))
        assert value(timer, 'UnitFileState') == 'disabled'
        assert value('sandbox.slice', 'ActiveState') == 'active'
        group = value('sandbox.slice', 'ControlGroup')
        assert group.endswith('/sandbox.slice')
        assert not value('docker.service', 'ControlGroup').startswith(group + '/')
        membership = run('docker', 'run', '--rm', '--network=none', '--cgroupns=host',
                         '--entrypoint=/bin/cat', args.image, '/proc/self/cgroup').stdout
        assert membership.startswith('0::' + group + '/docker-'), membership
        systemctl('start', service)
        assert value(service, 'Result') == 'success'
        corpus = Path(tempfile.mkdtemp(prefix='reclaim-active-', dir=args.work))
        name = 'reclaim-active-' + uuid.uuid4().hex
        try:
            for index in range(512):
                (corpus / str(index)).write_bytes(b'x' * 4096)
            argv = ['docker', 'run', '--rm', '-i', '--name', name, '--network=none',
                    '--mount', f'type=bind,src={corpus},dst={corpus}',
                    '--mount', f'type=bind,src={ROOT / "tests/docker_reclaim_probe.py"},dst=/probe.py,readonly',
                    '--entrypoint=python3', args.image, '/probe.py', 'hold', str(corpus)]
            with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as reader:
                try:
                    import select
                    assert select.select([reader.stdout], [], [], 15)[0], 'reader startup'
                    assert reader.stdout.readline().strip() == 'ready'
                    systemctl('start', service)
                    writer = argv[:]
                    writer.remove('-i')
                    writer[writer.index(name)] = name + '-writer'
                    writer[-2] = 'write'
                    with subprocess.Popen(writer, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          text=True) as writing:
                        while writing.poll() is None:
                            systemctl('start', service)
                            time.sleep(0.05)
                        stdout, stderr = writing.communicate(timeout=15)
                        assert writing.returncode == 0, stdout + stderr
                    stdout, stderr = reader.communicate('\n', timeout=15)
                    assert reader.returncode == 0, stdout + stderr
                finally:
                    run('docker', 'rm', '-f', name, name + '-writer', check=False)
                    if reader.poll() is None:
                        reader.kill()
                        reader.wait(timeout=10)
            assert all((corpus / str(index)).read_bytes() == b'x' * 4096 for index in range(512))
        finally:
            shutil.rmtree(corpus)
        print('PASS: default placement and live read/write/fsync during reclaim', flush=True)
        print('PASS: provisioned policy, disabled timer, manual reclaim', flush=True)

        proxy_corpus = Path(tempfile.mkdtemp(prefix='reclaim-helper-', dir=args.work))
        try:
            proxy_corpus.chmod(0o755)
            (proxy_corpus / 'helper').mkdir()
            shutil.copyfile(ROOT / 'tests/docker_reclaim_probe.py', proxy_corpus / 'probe.py')
            for index in range(512):
                (proxy_corpus / 'helper' / str(index)).write_bytes(b'x' * 4096)
            run('python3', ROOT / 'tests/reclaim_proxy_fixture.py',
                '--repo', proxy_corpus, '--image', args.image)
            systemctl('start', service)
        finally:
            shutil.rmtree(proxy_corpus)
        print('PASS: production helper creation uses the container parent', flush=True)

        if args.replay_image:
            run('python3', ROOT / 'tests/docker_reclaim_replay.py',
                '--work', args.work / 'paracress-replay', '--image', args.replay_image, timeout=1800)
            print('PASS: replay completed; inspect replay-results.jsonl for acceptance', flush=True)

        timer_override.mkdir(parents=True)
        # These are independent unit-language fixture files, not embedded scripts.
        shutil.copyfile(ROOT / 'tests/fixtures/reclaim-fast-timer.conf', timer_override / 'fixture.conf')
        systemctl('daemon-reload')
        failed_audit = run('python3', BASE / 'docker-policy.py', 'check',
                           input=json.dumps(record), check=False)
        assert failed_audit.returncode != 0 and 'overridden' in failed_audit.stderr
        systemctl('enable', '--now', timer)
        first = value(timer, 'LastTriggerUSec')
        wait_for(lambda: value(timer, 'LastTriggerUSec') != first, 'first activation')
        first = value(timer, 'LastTriggerUSec')
        wait_for(lambda: value(timer, 'LastTriggerUSec') != first, 'repeat activation')
        assert value(service, 'Result') == 'success'
        systemctl('stop', 'docker.service')
        assert value(timer, 'ActiveState') == 'inactive'
        assert value(service, 'ActiveState') in ('inactive', 'failed')
        assert value(service, 'MainPID') == '0'
        assert systemctl('start', service, check=False).returncode != 0
        assert value('docker.service', 'ActiveState') == 'inactive'
        systemctl('start', 'docker.service')
        assert value(timer, 'ActiveState') == 'active'
        systemctl('restart', 'docker.service')
        assert value(timer, 'ActiveState') == 'active'
        systemctl('reset-failed', 'docker.service')
        previous = value('docker.service', 'InvocationID')
        systemctl('kill', '--signal=SIGKILL', '--kill-whom=main', 'docker.service')
        wait_for(lambda: value('docker.service', 'InvocationID') != previous and
                 value('docker.service', 'ActiveState') == 'active',
                 'Docker automatic restart', timeout=30)
        wait_for(lambda: value(timer, 'ActiveState') == 'active', 'timer after Docker crash')
        print('PASS: timer repeats, rejects drift, follows Docker stop/start/restart', flush=True)

        service_override.mkdir(parents=True)
        shutil.copyfile(ROOT / 'tests/fixtures/reclaim-slow-service.conf', service_override / 'fixture.conf')
        systemctl('daemon-reload')
        systemctl('stop', service)
        wait_for(lambda: value(service, 'Result') == 'timeout', 'oneshot deadline')
        first = value(timer, 'LastTriggerUSec')
        wait_for(lambda: value(timer, 'LastTriggerUSec') != first, 'rearm after timeout')
        systemctl('disable', '--now', timer)
        systemctl('stop', service)
        run('python3', BASE / 'docker-reclaim.py', '--check-idle')
        service_override.joinpath('fixture.conf').unlink()
        service_override.rmdir()
        systemctl('daemon-reload')
        # The unit has failed, but simulate a worker that still owns the lock
        # independently of systemd's bookkeeping. Exercise the real host disable
        # implementation using a local transport in this already-verified guest.
        sys.path.insert(0, str(ROOT))
        from lima.docker_host import DockerHost
        host = object.__new__(DockerHost)
        host.record = lambda: record
        host.machine = lambda _: None
        host.guest = lambda _, *argv, **kwargs: run(
            *argv, **{key: value for key, value in kwargs.items() if key not in ('text', 'capture_output')})
        marker = backup / 'lock-ready'
        holder = subprocess.Popen(['python3', str(ROOT / 'tests/reclaim_lock_holder.py'), str(marker)])
        try:
            wait_for(marker.exists, 'surviving lock holder')
            assert systemctl('start', service, check=False).returncode != 0
            assert value(service, 'ExecMainStatus') == '75'
            try:
                host.reclaim('disable')
            except subprocess.CalledProcessError as error:
                assert error.returncode == 75
            else:
                raise AssertionError('disable reported success with a surviving worker')
        finally:
            holder.terminate()
            holder.wait(timeout=5)
        host.reclaim('disable')
        last_start = value(service, 'ExecMainStartTimestampMonotonic')
        systemctl('restart', 'docker.service')
        assert value(timer, 'ActiveState') == 'inactive'
        assert value(timer, 'UnitFileState') == 'disabled'
        assert value(service, 'ExecMainStartTimestampMonotonic') == last_start
        systemctl('reset-failed', 'docker.service')
        run('python3', BASE / 'docker-user.py')
        assert value(timer, 'UnitFileState') == 'disabled'
        assert value(timer, 'ActiveState') == 'inactive'
        assert value(service, 'ExecMainStartTimestampMonotonic') == last_start
        print('PASS: deadline, failure rearming, disable survives Docker restart', flush=True)
    finally:
        systemctl('disable', '--now', timer, check=False)
        systemctl('stop', service, check=False)
        for directory in (timer_override, service_override):
            if directory.exists():
                shutil.rmtree(directory)
        for target, original in saved.items():
            if original is None:
                run('sudo', 'rm', '-f', target)
            else:
                run('sudo', 'cp', '-p', original, target)
        systemctl('daemon-reload')
        systemctl('restart', 'docker.service')
        run('sudo', 'rm', '-rf', backup)


if __name__ == '__main__':
    main()
