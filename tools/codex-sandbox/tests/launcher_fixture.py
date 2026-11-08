"""Run launcher integration tests with proxy lifecycle calls at a fake boundary."""

from pathlib import Path
import os
import json
import runpy
import subprocess
import sys


tool = Path(__file__).resolve().parents[1]
launcher = runpy.run_path(str(tool / "codex-sandbox"))
launcher["main"].__globals__["image_runtime"] = lambda: launcher["ContainerRuntime"]()


native_validate_repository = launcher["validate_repository"]


def validate_fixture_repository(state, *, initialize_missing=True):
    # Config and builder sources still come from the real launcher checkout.
    # Only workspace discovery uses the disposable fake-boundary repository;
    # never initialize or inspect the authoritative checkout's JJ metadata.
    scope = native_validate_repository.__globals__
    source = scope["DOTFILES"]
    scope["DOTFILES"] = Path(os.environ["FAKE_REPOSITORY"])
    try:
        native_validate_repository(state, initialize_missing=initialize_missing)
    finally:
        scope["DOTFILES"] = source


launcher["main"].__globals__["validate_repository"] = validate_fixture_repository


def helper(*arguments: str, check: bool = True):
    # The fixture's PATH provides the existing fake proxy helper process.
    return subprocess.run(["python3", str(tool / "sandbox-proxies.py"), *arguments], check=check)



def reset_session(_runtime, *, unpublished_state=None):
    helper("stop", *(["--state", str(unpublished_state)] if unpublished_state is not None else []))

# Startup and removal use the same fake service boundary. Real metadata and
# native session locking are covered by the cleanup and session-lock suites.
native_session = launcher["CommandProxySession"]

def record_api(action, **values):
    # Record meaningful inputs at the lifecycle boundary, not CLI serialization.
    arguments = [str(tool / "sandbox-proxies.py"), action]
    for key, value in values.items():
        if value is not None:
            arguments += ["--" + key.replace("_", "-"), str(value)]
    with Path(os.environ["FAKE_PYTHON_LOG"]).open("a") as output:
        output.write("CALL\t" + "\t".join(arguments) + "\n")


def fixture_policy(*, shared=False):
    return {"version": 1,
            "capabilities": {"host-editor": True, "nested-containers": True},
            "commands": {"jj": {}} if shared else {"jj": {}, "zulip": {}}}


def fixture_state():
    return json.loads(os.environ.get("FAKE_PROXY_STATE", '{"proxies":[]}'))


def snapshot_policy(repo, **options):
    record_api("snapshot", repo=repo, **options)
    return fixture_policy()


def join_session(request):
    record_api("join", repo=request.repo)
    image = "sha256:" + "0" * 64
    return fixture_state(), {"manifest": fixture_policy(shared=True), "source-present": True,
                             "images": {"agent": image, "helper": image, "proxies": {"jj": image}}}


def attach_session(request, manifest, images):
    record_api("attach", repo=request.repo, zuliprc=request.zuliprc)
    state = fixture_state()
    request.state.write_text(json.dumps(state))
    return state, manifest, False


def publish_session(repo, container_repo, state, manifest):
    record_api("publish", repo=repo)


def agent_arguments(repo, container_repo, manifest, state):
    record_api("agent-args", repo=repo)
    return ["--env", "SANDBOX_PROXY_DIR=/run/sandbox-proxies"]


def command_proxy_session(*arguments, **options):
    session = native_session(*arguments, **options)
    module = session._backend
    module.reset_session = reset_session
    module.snapshot_policy = snapshot_policy
    module.join_session = join_session
    module.attach_session = attach_session
    module.publish_session = publish_session
    module.agent_arguments = agent_arguments
    return session

launcher["main"].__globals__["CommandProxySession"] = command_proxy_session
acquire = launcher['acquire_lock']

def acquire_lock(state):
    acquire(state)
    # Shared-session fixtures supply accepted authority through the fake helper.
    if os.environ.get('FAKE_SESSION') == 'shared':
        state.command_session._lock.shared = True
        state.command_session.release_coordination()

launcher['main'].__globals__['acquire_lock'] = acquire_lock
raise SystemExit(launcher["main"](sys.argv[1:]))
