"""Exercise owned gateways on an existing Docker VM without resetting shared state.

Requires an existing sandbox agent image and configured Agent Podman SSH access.
Creates two isolated gateways and removes only its own containers/networks.
"""
import argparse
from pathlib import Path
import runpy
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path.home() / '.local/state/codex-sandbox-docker')
    parser.add_argument('--agent-image', required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    launcher = runpy.run_path(str(ROOT / 'codex-sandbox'))
    launcher['new_state'].__globals__['OUTER_RUNTIME'] = runtime
    image = runtime.inspect_image(args.agent_image)
    auth = runtime.prepare_images(ROOT.parents[1], {},
        auth_builder=([str(ROOT / 'auth-proxy/image')], ROOT.parents[1])).auth
    states = []
    try:
        for _ in range(2):
            state = launcher['new_state'](['--help'])
            states.append(state)
            assert state.agent_podman is not None, 'Agent Podman access must be configured'
            state.sidecar_image = auth
            flags = launcher['prepare_gateway'](state)
            state.host_editor._edit = lambda content: content + ' edited'
            launcher['start_gateway'](state)
        other, state = states
        other_ip = runtime.network_address(other.gateway_container, other.gateway_link_network)
        flags = ['--network', 'codex-public-only', *flags]
        with runtime.environment_file({'CODEX_SANDBOX_EDITOR_TOKEN': state.host_editor.token,
                'OTHER_GATEWAY_IP': other_ip, 'HOST_EDITOR_PORT': str(state.host_editor.port)}) as env:
            for probe in ([], ['--refused-editor']):
                if probe:
                    state.host_editor.stop()
                with runtime.workload(image, 'gateway-client-' + uuid.uuid4().hex[:12], [
                        *flags, *env, '--cap-drop=ALL',
                        '--mount', f'type=bind,src={ROOT / "tests"},dst=/probe,readonly',
                        '--entrypoint', 'python3'], ['/probe/gateway_guest.py', *probe]) as process:
                    assert process.wait(timeout=30) == 0
        print('Editor upstream refusal left SSH available.')
        # SIGTERM must end the PID1 supervisor and all of its listener children.
        runtime.run(['kill', '--signal', 'TERM', state.gateway_container], stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while runtime.inspect_container(state.gateway_container)['State']['Running']:
            assert time.monotonic() < deadline, 'gateway did not stop on SIGTERM'
            time.sleep(0.05)
        print('Gateway cancellation passed.')
        # The other gateway remains owned and running; kill one listener only.
        with (ROOT / 'tests/gateway_kill_listener.py').open() as script:
            runtime.run(['exec', '--interactive', other.gateway_container, 'python3', '-'],
                        stdin=script, check=False)
        deadline = time.monotonic() + 5
        while runtime.inspect_container(other.gateway_container)['State']['Running']:
            assert time.monotonic() < deadline, 'incomplete gateway kept running'
            time.sleep(0.05)
        assert runtime.inspect_container(other.gateway_container)['State']['ExitCode'] != 0
        print('Listener failure stopped the gateway.')
    finally:
        for state in states:
            launcher['cleanup'](state)
            assert not runtime.run(['ps', '-aq', '--filter', 'name=^/' + state.gateway_container + '$'],
                                   capture_output=True).stdout.strip()
            networks = runtime.run(['network', 'ls', '--format', '{{.Name}}'], capture_output=True).stdout.splitlines()
            assert state.gateway_link_network not in networks and state.gateway_egress_network not in networks


if __name__ == '__main__':
    main()
