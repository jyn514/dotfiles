"""Owned workload caller used to exercise actual host SIGTERM cleanup."""

import argparse
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sandbox_runtime import image_runtime


def interrupted(signum, _frame):
    signal.signal(signum, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    runtime = image_runtime(args.provider, args.state)
    image = runtime.resolve_image(args.image)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with runtime.workload(image, args.name, ["--network", "none"], ["sleep", "300"],
                              stdout=subprocess.DEVNULL):
            print("transport started", flush=True)
            signal.pause()
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)


if __name__ == "__main__":
    main()
