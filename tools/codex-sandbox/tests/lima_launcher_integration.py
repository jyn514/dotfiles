"""Test real launcher startup, interactive input, and cleanup with dummy credentials.

Requires a provisioned test host sharing dotfiles read-only and --work writable.
The caller owns host teardown; this test owns its repository and session reset.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import runpy
import re
import secrets
import select
import shutil
import subprocess
import struct
import sys
import tempfile
import termios
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sandbox_credentials import boot_credential
from sandbox_runtime import image_runtime


def terminal_run(command, environment, cwd, *, interactive=False, ready_barrier=None, hold_seconds=0,
                 proxy_requests=0):
    started = time.monotonic()
    ready_at = key_at = None
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 100, 0, 0))
    process = subprocess.Popen(command, env=environment, cwd=cwd,
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    output = bytearray()
    sent_key = interrupted = False
    deadline = time.monotonic() + 1200
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 1)[0]:
                try:
                    block = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
                if not block:
                    break
                output.extend(block)
                sys.stdout.buffer.write(block)
                sys.stdout.buffer.flush()
                if interactive and not sent_key and b'__SANDBOX_PI_READY__' in output:
                    ready_at = time.monotonic()
                    if ready_barrier is not None:
                        ready_barrier.wait(timeout=180)
                        time.sleep(hold_seconds)
                    key_sent_at = time.monotonic()
                    os.write(master, b'nft-key-probe')
                    sent_key = True
                if interactive and not interrupted and b'__SANDBOX_PI_KEY__' in output:
                    key_at = time.monotonic()
                    process.terminate()
                    interrupted = True
            elif process.poll() is not None:
                break
        else:
            raise TimeoutError("real Lima launcher exceeded its test deadline")
        status = process.wait(timeout=30)
        assert status == (143 if interactive else 0), f"launcher exited {status}"
        if interactive:
            assert sent_key and interrupted, 'Pi never accepted interactive input'
            if proxy_requests:
                assert b'__SANDBOX_PROXY_WORK_DONE__' in output, 'proxy workload did not finish before cancellation'
                assert b'__SANDBOX_PROXY_WORK_FAILED__' not in output, 'proxy workload failed'
            print('\nTERMINAL TIMING ' + json.dumps({
                'ready_seconds': ready_at - started,
                'key_delivery_seconds': key_at - key_sent_at,
                'cancellation_seconds': time.monotonic() - key_at,
            }), flush=True)
        assert b"owned-dummy-github-token" not in output, "credential escaped into terminal output"
    finally:
        if ready_barrier is not None and key_at is None:
            ready_barrier.abort()
        if process.poll() is None:
            process.terminate()
            # On a failed barrier, keep consuming the PTY while the launcher
            # reports cleanup. Otherwise a full terminal buffer can block it
            # until our timeout kills it and strands relay containers.
            deadline = time.monotonic() + 30
            while process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        block = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                    else:
                        sys.stdout.buffer.write(block)
                        sys.stdout.buffer.flush()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        os.close(master)


@contextmanager
def fixture_home(work):
    home = Path(tempfile.mkdtemp(prefix='launcher-', dir=work))
    try:
        yield home
    except BaseException:
        print(f'Failed launcher fixture retained at {home}', file=sys.stderr, flush=True)
        raise
    else:
        shutil.rmtree(home)


def exercise(state, work, provider='lima', interactive_runs=1, concurrent_sessions=1, hold_seconds=0,
             proxy_requests=0):
    runtime = image_runtime(provider, state)
    native = ['--mode=native'] if provider == 'lima' else []
    def resources():
        return {
            kind: set(runtime.run(arguments, capture_output=True).stdout.splitlines())
            for kind, arguments in (
                ('containers', ['ps', '-a', '--no-trunc', '--format', '{{.ID}}']),
                ('networks', ['network', 'ls', '--no-trunc', '--format', '{{.ID}}']),
                ('volumes', ['volume', 'ls', '--format', '{{.Name}}']),
            )
        }

    # Compare identities, not counts: deleting another workload must not hide
    # a leaked relay. Images are deliberately retained for subsequent tests.
    baseline = resources() if provider == 'lima-docker' else None
    with fixture_home(work) as temporary:
        home = Path(temporary)
        repo = home / "src/dotfiles"
        sandbox = repo / ".agents/sandbox"
        sandbox.mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name('pi_startup_observer.js'), sandbox / 'observer.js')
        (sandbox / 'observer-workload.json').write_text(json.dumps({'requests': proxy_requests}))
        (repo / "nested").mkdir()
        # Use the real builder through an executable fixture with its own file
        # as argv[0], so its relative Dockerfile lookup stays in dotfiles.
        (sandbox / "base-image").symlink_to(Path(__file__).with_name("lima_fixture_base_image.py"))
        if provider == 'lima-docker':
            shutil.copyfile(ROOT.parents[1] / '.agents/sandbox/bake', sandbox / 'bake')
            (sandbox / 'bake').chmod(0o755)
            shutil.copyfile(ROOT.parents[1] / '.agents/sandbox/Dockerfile', sandbox / 'Dockerfile')
        (home / ".agents/skills").mkdir(parents=True)
        (home / ".codex").mkdir()
        (home / ".codex/config.toml").write_text("")
        auth = home / "sandbox-auth"
        auth.mkdir(mode=0o700)
        (auth / "auth.json").write_text('{"OPENAI_API_KEY":"owned-dummy-codex-token"}')
        (auth / "auth.json").chmod(0o600)
        (home / "runtime").mkdir(mode=0o700)
        environment = {**os.environ, "HOME": str(home), "XDG_RUNTIME_DIR": str(home / "runtime"),
            "LIMA_HOME": os.environ.get("LIMA_HOME", str(Path.home() / ".lima")),
            "CODEX_SANDBOX_RUNTIME": provider, "CODEX_SANDBOX_LIMA_STATE": str(state),
            "CODEX_SANDBOX_DOCKER_STATE": str(state),
            "CODEX_SANDBOX_AUTH_DIR": str(auth),
            "AGENT_PODMAN_ACCESS_DIR": str(home / "no-worker"), "CODEX_SANDBOX_TIMING": "1"}
        for name in ("TMUX", "TMUX_PANE", "GH_TOKEN", "GITHUB_TOKEN"):
            environment.pop(name, None)
        subprocess.run(["jj", "git", "init", str(repo)], cwd=repo, check=True)
        # Import no real credential and never contact Keychain in this fixture.
        boot_credential(runtime, invalidate=True)
        cache = boot_credential(runtime, retrieve=lambda: b"owned-dummy-github-token")
        try:
            launcher = runpy.run_path(str(ROOT / "codex-sandbox"))
            launcher["ensure_image"].__globals__["OUTER_RUNTIME"] = runtime
            collision = launcher["new_state"](["--help"])
            network = collision.gateway_link_network
            runtime.run(["network", "create", "--label", "dev.codex.relay-owner=" + "0" * 32, network],
                        stdout=subprocess.DEVNULL)
            try:
                before = runtime.run(["network", "inspect", *native, network], capture_output=True).stdout
                print("\nEXPECTED FAILURE: rejecting a relay network owned by another creator.\n"
                      "The following traceback and retained-recovery warnings are part of this check.",
                      file=sys.stderr, flush=True)
                try:
                    launcher["prepare_gateway"](collision)
                except subprocess.CalledProcessError:
                    pass
                else:
                    raise AssertionError("relay creator adopted an existing network")
                launcher["cleanup"](collision)
                after = runtime.run(["network", "inspect", *native, network], capture_output=True).stdout
                assert before == after, "failed creation changed or deleted the existing relay network"
            finally:
                runtime.run(["network", "rm", network], stdout=subprocess.DEVNULL)
                if collision.proxy_state is not None:
                    collision.proxy_state.unlink(missing_ok=True)
                if collision.recovery_record is not None:
                    collision.recovery_record.unlink(missing_ok=True)
            print("PASS: the conflicting network survived; fixture resources and recovery record removed.\n",
                  file=sys.stderr, flush=True)
            base = (runtime.bake(repo, ['base'])['base'] if provider == 'lima-docker' else
                    subprocess.run([str(sandbox / "base-image")], env=environment, cwd=repo,
                                   check=True, text=True, stdout=subprocess.PIPE).stdout.strip())
            agent = launcher["ensure_image"](launcher["new_state"](["--help"]), base)
            editor = launcher["new_state"](["--help"])
            try:
                editor_flags = launcher["prepare_gateway"](editor)
                editor.host_editor._edit = lambda content: content + " edited"
                editor.sidecar_image = subprocess.run([str(ROOT / "auth-proxy/image")],
                    env=environment, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
                launcher["start_gateway"](editor)
                with runtime.environment_file({"CODEX_SANDBOX_EDITOR_TOKEN": editor.host_editor.token}) as secret:
                    with runtime.workload(runtime.inspect_image(agent), "editor-probe-" + secrets.token_hex(6), [
                            *editor_flags, *secret,
                            "--mount", f"type=bind,src={ROOT / 'tests/lima_editor_probe.py'},dst=/probe.py,readonly",
                            "--entrypoint", "python3"], ["/probe.py"]) as process:
                        assert process.wait(timeout=30) == 0
            finally:
                launcher["cleanup"](editor)
            probe_name = "credential-probe-" + secrets.token_hex(6)
            with runtime.workload(runtime.inspect_image(agent), probe_name, [
                    "--network", "codex-public-only", "--dns", "10.0.2.3",
                    "--mount", f"type=bind,src={cache},dst=/run/secrets/github-token,readonly",
                    "--mount", f"type=bind,src={repo},dst=/repo",
                    "--mount", f"type=bind,src={repo / '.git'},dst=/repo/.git,readonly",
                    "--mount", f"type=bind,src={ROOT / 'tests/lima_agent_probe.py'},dst=/probe.py,readonly",
                    "--entrypoint", "/opt/agent-tools/bin/with-github-token"],
                    ["python3", "/probe.py"]) as process:
                assert process.wait(timeout=60) == 0
                metadata = runtime.run(["inspect", *native, probe_name],
                                       capture_output=True).stdout
                assert "owned-dummy-github-token" not in metadata
            print("\nThe next checks reuse an existing proxy volume; nerdctl may warn that it already exists.",
                  file=sys.stderr, flush=True)
            for launch in range(1, 3):
                print(f"\nSTARTUP CHECK {launch}/2: Pi's help screen is the expected output.",
                      file=sys.stderr, flush=True)
                terminal_run([sys.executable, str(ROOT / "codex-sandbox"), "--help"],
                             environment, repo / "nested")
                print(f"PASS: PTY launch {launch}/2 exited successfully.", file=sys.stderr, flush=True)
                assert boot_credential(runtime, retrieve=lambda: (_ for _ in ()).throw(
                    AssertionError("session exit discarded the boot cache"))) == cache
                metadata_path, = (home / "runtime/codex-sandbox-proxies").glob("*/session.json")
                metadata = json.loads(metadata_path.read_text())
                sidecar = metadata["state"]["auth"]
                with runtime.workload(runtime.inspect_image(agent), "auth-probe-" + secrets.token_hex(6), [
                        "--network", "codex-public-only", "--dns", "10.0.2.3",
                        "--env", f"CODEX_SIDECAR_URL=http://{sidecar['container']}:8787",
                        "--env", f"CODEX_SIDECAR_KEY={sidecar['key']}",
                        "--mount", f"type=bind,src={ROOT / 'tests/lima_auth_probe.py'},dst=/probe.py,readonly",
                        "--entrypoint", "python3"], ["/probe.py"]) as process:
                    assert process.wait(timeout=30) == 0
                request = json.dumps({"version": 1, "cwd": "nested", "argv": ["status"],
                                      "user": "fixture", "email": "fixture@example.test"}).encode()
                with metadata_path.with_name("session.lock").open("a+b") as lock:
                    fcntl.flock(lock, fcntl.LOCK_SH)
                    route = [sys.executable, str(ROOT / "sandbox-proxies.py"),
                        "route", "--repo", str(repo), "--command", "jj", "--", "false"]
                    route_started = time.monotonic()
                    response = subprocess.run(route,
                        env=environment, input=struct.pack(">I", len(request)) + request,
                        stdout=subprocess.PIPE, check=True, timeout=30).stdout
                    print('PROXY TIMING ' + json.dumps({
                        'jj_status_seconds': time.monotonic() - route_started,
                    }), flush=True)
                    proxy = next(proxy for proxy in metadata["state"]["proxies"] if proxy["name"] == "jj")
                    if provider == 'lima':
                        stalled_route = route
                        container = json.loads(runtime.run(["inspect", *native, proxy["container"]],
                            capture_output=True).stdout)[0]["ID"]
                        listing = ["containerd-rootless-setuptool.sh", "nsenter", "--", "ctr",
                                   "--namespace", "default", "tasks", "ps", container]
                        tasks_now = lambda: runtime.guest(listing, capture_output=True, text=True, timeout=10).stdout
                        active = lambda tasks: bool(re.search(r'exec_id:"codex-forward-', tasks))
                    else:
                        ready = home / 'forwarding-request-sent'
                        ready.unlink(missing_ok=True)
                        stalled_route = [sys.executable, str(ROOT / 'tests/proxy_route_fixture.py'),
                                         str(ready), *route[2:]]
                        tasks_now = ready.exists
                        active = bool
                    stalled = subprocess.Popen(stalled_route, env=environment, stdin=subprocess.PIPE,
                                               stdout=subprocess.DEVNULL)
                    try:
                        # Cancellation must also cover a request already being
                        # forwarded, not just an exec waiting for its first byte.
                        stalled.stdin.write(struct.pack('>I', len(request)) + request[:8])
                        stalled.stdin.flush()
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            tasks = tasks_now()
                            if active(tasks):
                                break
                            assert stalled.poll() is None, "router exited before opening its connection"
                            time.sleep(0.1)
                        else:
                            raise AssertionError("router never opened its connection")
                        stalled.terminate()
                        assert stalled.wait(timeout=30) == 143
                        if provider == 'lima':
                            deadline = time.monotonic() + 10
                            while active(tasks_now()) and time.monotonic() < deadline:
                                time.sleep(0.1)
                            assert not active(tasks_now()), "terminated router retained its connection"
                        else:
                            recovered = subprocess.run(route, env=environment,
                                input=struct.pack('>I', len(request)) + request,
                                stdout=subprocess.PIPE, check=True, timeout=5).stdout
                            assert recovered == response, 'request after cancellation changed'
                        assert runtime.run(["inspect", "--format", "{{.State.Running}}", proxy["container"]],
                                           capture_output=True).stdout.strip() == "true"
                    finally:
                        if stalled.poll() is None:
                            stalled.kill()
                            stalled.wait()
                        stalled.stdin.close()
                length, = struct.unpack(">I", response[:4])
                assert len(response) == length + 4, "proxy response framing changed"
                result = json.loads(response[4:])
                assert result["exit"] == 0, result["stderr"]
                volume = next(proxy["volume"] for proxy in metadata["state"]["proxies"] if proxy["name"] == "jj")
                with runtime.workload(runtime.inspect_image(agent), "proxy-client-" + secrets.token_hex(6), [
                        "--network", "none", "--workdir", "/repo/nested",
                        "--env", "JJ_PROXY_REPO=/repo", "--env", "SANDBOX_PROXY_DIR=/run/sandbox-proxies",
                        "--mount", f"type=bind,src={repo},dst=/repo,readonly",
                        "--mount", f"type=volume,src={volume},dst=/run/sandbox-proxies/jj,readonly",
                        "--entrypoint", "/tools/jj-proxy/client"], ["status"]) as process:
                    assert process.wait(timeout=30) == 0
            print('STARTUP CHECK: interactive Pi session, key delivery, and cancellation.', flush=True)
            for _ in range(interactive_runs):
                command = [sys.executable, str(ROOT / 'codex-sandbox'), '--offline', '--approve', '--no-session',
                           '-e', '../.agents/sandbox/observer.js']
                if concurrent_sessions == 1:
                    terminal_run(command, environment, repo / 'nested', interactive=True)
                else:
                    barrier = threading.Barrier(concurrent_sessions)
                    with ThreadPoolExecutor(max_workers=concurrent_sessions) as executor:
                        futures = [executor.submit(terminal_run, command, environment, repo / 'nested',
                                   interactive=True, ready_barrier=barrier, hold_seconds=hold_seconds,
                                   proxy_requests=proxy_requests)
                                   for _ in range(concurrent_sessions)]
                        for future in futures:
                            future.result()
        finally:
            subprocess.run([sys.executable, str(ROOT / "sandbox-proxies.py"), "reset", "--repo", str(repo)],
                           env=environment, check=True, timeout=120)
            boot_credential(runtime, invalidate=True)
        if baseline is not None:
            remaining = resources()
            changes = {kind: {'added': sorted(remaining[kind] - original),
                              'removed': sorted(original - remaining[kind])}
                       for kind, original in baseline.items() if remaining[kind] != original}
            assert not changes, f'launcher cleanup changed the resource baseline: {changes}'
    print("PASS: all Lima launcher checks and cleanup completed; dummy boot credential invalidated.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--provider", choices=('lima', 'lima-docker'), default='lima')
    parser.add_argument('--interactive-runs', type=int, choices=range(1, 21), default=1,
                        metavar='1..20', help='repeat sequential interactive launches for warm timings')
    parser.add_argument('--concurrent-sessions', type=int, choices=range(1, 21), default=1, metavar='1..20')
    parser.add_argument('--hold-seconds', type=int, choices=range(0, 601), default=30, metavar='0..600',
                        help='hold concurrent sessions after all report readiness, before sending keys')
    parser.add_argument('--proxy-requests', type=int, choices=range(0, 101), default=0, metavar='0..100',
                        help='JJ status requests per concurrent session; must finish within the hold interval')
    args = parser.parse_args()
    if args.proxy_requests and args.concurrent_sessions < 2:
        parser.error('--proxy-requests requires at least two concurrent sessions')
    exercise(args.state.resolve(), args.work.resolve(), args.provider, args.interactive_runs,
             args.concurrent_sessions, args.hold_seconds, args.proxy_requests)
