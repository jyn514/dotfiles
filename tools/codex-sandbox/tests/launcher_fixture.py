"""Run launcher integration tests with proxy lifecycle calls at a fake boundary."""

from pathlib import Path
import os
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


launcher["main"].__globals__["helper"] = helper

def reset_session(_runtime, *, unpublished_state=None):
    helper("stop", *(["--state", str(unpublished_state)] if unpublished_state is not None else []))

# Startup and removal use the same fake service boundary. Real metadata and
# native session locking are covered by the cleanup and session-lock suites.
native_proxy_module = launcher["proxy_module"]

def proxy_module():
    module = native_proxy_module()
    module.reset_session = reset_session
    return module

proxy_module.cache_clear = native_proxy_module.cache_clear
launcher["main"].__globals__["proxy_module"] = proxy_module
acquire = launcher['acquire_lock']

def acquire_lock(state):
    acquire(state)
    # The sidecar fixtures supply an existing publication through FAKE_PROXY_STATE.
    if os.environ.get('FAKE_SESSION') == 'shared':
        state.proxy_lock.shared = True
        state.proxy_lock.release_coordination()

launcher['main'].__globals__['acquire_lock'] = acquire_lock
raise SystemExit(launcher["main"](sys.argv[1:]))
