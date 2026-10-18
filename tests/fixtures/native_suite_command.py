"""Fake native executables; pytest and isolation always use the real Python."""

import json
import os
from pathlib import Path
import sys
import time


role, *arguments = sys.argv[1:]
if role == "pytest":
    os.execv(os.environ["TEST_REAL_PYTHON"], [os.environ["TEST_REAL_PYTHON"], "-m", "pytest", *arguments])
if role == "python3" and arguments and arguments[0].endswith("/dev/test-environment"):
    os.execv(os.environ["TEST_REAL_PYTHON"], [os.environ["TEST_REAL_PYTHON"], *arguments])


def record(kind, **fields):
    payload = (json.dumps({"kind": kind, **fields}) + "\n").encode()
    descriptor = os.open(os.environ["TEST_NATIVE_LOG"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        # One append per event keeps parallel writers from interleaving JSON.
        if os.write(descriptor, payload) != len(payload):
            raise OSError("incomplete native fixture log write")
    finally:
        os.close(descriptor)


if role == "python3":
    record("postcheck", argv=arguments)
    if arguments and arguments[0].endswith("/tools/codex-sandbox/owned_images.py"):
        print("0123456789abcdef0123456789abcdef01234567")
    raise SystemExit(0)
if role == "container-test":
    record("container", argv=arguments)
    raise SystemExit(0)

native_role = "bb" if role == "bb-override" else role
xdg = {key: os.environ[key] for key in (
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
)}
record("native", tool=native_role, executable=role, argv=arguments,
       cwd=os.getcwd(), home=os.environ["HOME"], xdg=xdg,
       directories_exist=all(Path(path).is_dir() for path in [os.environ["HOME"], *xdg.values()]),
       jj_real=os.environ.get("JJ_REAL"), jj_proxy_test_jj=os.environ.get("JJ_PROXY_TEST_JJ"))

if os.environ.get("TEST_NATIVE_BARRIER"):
    barrier = Path(os.environ["TEST_NATIVE_BARRIER"])
    record("started", tool=native_role)
    (barrier / native_role).touch()
    deadline = time.monotonic() + 10
    while not all((barrier / tool).exists() for tool in ("bb", "bun")):
        if time.monotonic() >= deadline:
            print("native rendezvous timed out: both adapters must start before either finishes", file=sys.stderr)
            raise SystemExit(41)
        time.sleep(0.01)
    record("finished", tool=native_role)

if native_role == "bun" and arguments == ["test", "tests/pi"] and os.environ.get("TEST_NATIVE_PI_STATUS"):
    print("NATIVE_PI_STDOUT_SENTINEL", flush=True)
    print("NATIVE_PI_STDERR_SENTINEL", file=sys.stderr, flush=True)
    raise SystemExit(int(os.environ["TEST_NATIVE_PI_STATUS"]))
