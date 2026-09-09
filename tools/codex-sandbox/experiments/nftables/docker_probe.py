"""Check bridge-sysctl ownership using a disposable second rootless Docker daemon.

Run as the ordinary Linux guest user. No images, real credentials, published
ports, existing engine sockets, or systemd units are used.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from probe import candidate, run, handle_cancellation, ignore_cancellation, stop_build
from network_policy import policy_bytes


def main():
    if os.geteuid() == 0:
        raise SystemExit('run as the ordinary Linux guest user')
    handle_cancellation()
    with tempfile.TemporaryDirectory(prefix='codex-nft-docker-') as directory:
        root = Path(directory)
        (root / 'runtime').mkdir(mode=0o700)
        (root / 'client').mkdir(mode=0o700)
        config = root / 'daemon.json'
        config.write_text(json.dumps({'iptables': True, 'ip6tables': True,
                                      'userland-proxy': True, 'firewall-backend': 'iptables'}))
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('DOCKER', 'ROOTLESSKIT', '_DOCKERD', 'CONTAINERD_ROOTLESS'))}
        environment.update({
            'XDG_RUNTIME_DIR': str(root / 'runtime'),
            'DOCKERD_ROOTLESS_ROOTLESSKIT_STATE_DIR': str(root / 'rootlesskit'),
            'DOCKERD_ROOTLESS_ROOTLESSKIT_NET': 'slirp4netns',
            'DOCKERD_ROOTLESS_ROOTLESSKIT_DETACH_NETNS': 'true',
            'DOCKERD_ROOTLESS_ROOTLESSKIT_DISABLE_HOST_LOOPBACK': 'true',
            'DOCKERD_ROOTLESS_ROOTLESSKIT_FLAGS': '--cidr=10.0.2.0/24',
        })
        client = ['docker', '--config', str(root / 'client'), '--host', 'unix://' + str(root / 'docker.sock')]
        with (root / 'daemon.log').open('w+') as log:
            process = subprocess.Popen([
                'dockerd-rootless.sh', '--config-file', str(config),
                '--data-root', str(root / 'data'), '--exec-root', str(root / 'exec'),
                '--pidfile', str(root / 'daemon.pid'), '--host', 'unix://' + str(root / 'docker.sock'),
                '--storage-driver', 'vfs'], env=environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, start_new_session=True)
            try:
                deadline = time.monotonic() + 60
                while True:
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        raise RuntimeError('disposable Docker startup failed:\n' + log.read())
                    if (root / 'docker.sock').exists():
                        try:
                            info = json.loads(run(*client, 'info', '--format', '{{json .}}', env=environment))
                            break
                        except RuntimeError:
                            pass
                    time.sleep(0.2)
                if 'name=rootless' not in info['SecurityOptions']:
                    raise RuntimeError('disposable engine is not rootless')
                child = (root / 'rootlesskit/child_pid').read_text().strip()
                # Enter only this process's private user/mount and detached netns.
                prefix = ['nsenter', '--user', '--mount', '--preserve-credentials', '--target', child,
                          '--', 'nsenter', '--net=' + str(root / 'rootlesskit/netns'), '--']
                run(*prefix, 'sysctl', '-qw', 'net.bridge.bridge-nf-call-iptables=0',
                    'net.bridge.bridge-nf-call-ip6tables=0')
                run(*prefix, 'nft', '-f', '-', input=candidate(json.loads(policy_bytes())))

                def knobs():
                    return run(*prefix, 'sysctl', '-n', 'net.bridge.bridge-nf-call-iptables',
                               'net.bridge.bridge-nf-call-ip6tables').split()

                for name, flags in (('public', []), ('internal', ['--internal']), ('egress', [])):
                    run(*client, 'network', 'create', *flags, name, env=environment)
                    if knobs() != ['0', '0']:
                        raise AssertionError('Docker re-enabled bridge filtering for ' + name)
                print('PASS: normal public/internal/egress network creation preserves both zero sysctls', flush=True)
                # Adversarial configuration: this is why a migration must verify
                # effective settings instead of assuming setup owns these knobs.
                run(*client, 'network', 'create', '--opt', 'com.docker.network.bridge.enable_icc=false',
                    'icc-disabled', env=environment)
                changed = knobs()
                if changed != ['1', '0']:
                    raise AssertionError('unexpected ICC-disabled bridge behavior: ' + str(changed))
                print('PASS: ICC-disabled network reproduces Docker re-enabling IPv4 bridge filtering', flush=True)
            finally:
                ignore_cancellation()
                stop_build(process)


if __name__ == '__main__':
    main()
