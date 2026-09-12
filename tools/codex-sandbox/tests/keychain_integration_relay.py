"""Opt-in existing-VM transport test. Creates only owned relay/client resources."""

from pathlib import Path
import runpy
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker


def main():
    runtime = Docker(Path.home() / '.local/state/codex-sandbox-docker')
    launcher = runpy.run_path(str(ROOT / 'codex-sandbox'))
    launcher['new_state'].__globals__['OUTER_RUNTIME'] = runtime
    state = launcher['new_state'](['--help'])
    try:
        state.sidecar_image = runtime.prepare_images(ROOT.parents[1], {},
            auth_builder=([str(ROOT / 'auth-proxy/image')], ROOT.parents[1])).auth
        flags = launcher['start_keychain'](state)
        assert flags and state.host_keychain is not None
        # Native children are covered by keychain_bridge_test; this test owns wiring.
        state.host_keychain._read = lambda account, connection, deadline: 'dummy-' + account
        image = runtime.inspect_image(state.sidecar_image)
        with runtime.environment_file({'CODEX_SANDBOX_KEYCHAIN_TOKEN': state.host_keychain.token}) as env:
            with runtime.workload(image, 'keychain-client-' + uuid.uuid4().hex[:12], [
                    *flags, *env, '--cap-drop=ALL',
                    '--mount', f'type=bind,src={ROOT / "tests"},dst=/probe,readonly',
                    '--entrypoint', 'python3'], ['/probe/keychain_guest.py']) as process:
                assert process.wait(timeout=30) == 0
    finally:
        launcher['cleanup'](state)
        names = runtime.run(['network', 'ls', '--format', '{{.Name}}'], capture_output=True).stdout.splitlines()
        assert not set(state.keychain_networks).intersection(names)
        if state.keychain_container:
            assert not runtime.run(['ps', '-aq', '--filter', 'name=^/' + state.keychain_container + '$'],
                                   capture_output=True).stdout.strip()
    print('Owned relay resources removed.')


if __name__ == '__main__':
    main()
