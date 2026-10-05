"""Cheap child process for the test-environment behavioral contract."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


STATE_DEFAULTS = {
    "PI_CODING_AGENT_DIR": ".pi/agent",
    "PI_CODING_AGENT_SESSION_DIR": ".pi/agent/sessions",
    "PI_SUBAGENT_TEMP_DIR": "tmp/subagents",
    "XDG_CONFIG_HOME": ".config",
    "XDG_CACHE_HOME": ".cache",
    "XDG_DATA_HOME": ".local/share",
    "XDG_STATE_HOME": ".local/state",
    "XDG_RUNTIME_DIR": ".runtime",
}


def report():
    home = Path(os.environ["HOME"])
    paths = {
        key: os.environ.get(key) or str(home / default)
        for key, default in STATE_DEFAULTS.items()
    }
    return {
        "home": str(home),
        "home_exists": home.is_dir(),
        "home_mode": home.stat().st_mode & 0o777 if home.exists() else None,
        "environment": dict(os.environ),
        "state_paths": paths,
        "state_exists_before_child_write": {
            key: Path(path).is_dir() for key, path in paths.items()
        },
        "runtime_mode": Path(paths["XDG_RUNTIME_DIR"]).stat().st_mode & 0o777
        if Path(paths["XDG_RUNTIME_DIR"]).exists() else None,
    }


def emit(value):
    print(json.dumps(value), flush=True)


def main():
    mode = sys.argv[1]
    value = report()
    home = Path(value["home"])
    if mode == "write":
        for directory in [home, *map(Path, value["state_paths"].values())]:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "probe-write").write_bytes(b"isolated child state\x00\xff")
        emit(value)
        return int(sys.argv[2])
    if mode == "native-signal":
        emit(value)
        os.kill(os.getpid(), int(sys.argv[2]))
        raise AssertionError("terminating signal returned")
    if mode == "stdin":
        value["stdin"] = sys.stdin.read()
        emit(value)
        return 0
    if mode == "nested":
        wrapper = sys.argv[2]
        nested = subprocess.run(
            [wrapper, sys.executable, __file__, "write", "0"],
            env=dict(os.environ, BB_REAL="/replacement/bb"),
            text=True,
            capture_output=True,
            check=False,
        )
        value["nested_status"] = nested.returncode
        value["nested_stderr"] = nested.stderr
        value["nested"] = json.loads(nested.stdout)
        value["nested_home_exists_after"] = Path(value["nested"]["home"]).exists()
        value["outer_home_exists_after"] = home.is_dir()
        emit(value)
        return 0
    if mode == "signal":
        def terminated(signum, frame):
            # Make deleting HOME before reaping the child observable.
            time.sleep(0.15)
            value["home_exists_during_cleanup"] = home.is_dir()
            if home.is_dir():
                (home / "child-cleanup").write_bytes(b"cleanup completed")
            value["cleanup_completed"] = True
            emit(value)
            raise SystemExit(130 if signum == signal.SIGINT else 37)

        signal.signal(signal.SIGTERM, terminated)
        signal.signal(signal.SIGINT, terminated)
        signal.alarm(10)
        emit(value)
        while True:
            signal.pause()
    raise ValueError(mode)


if __name__ == "__main__":
    sys.exit(main())
