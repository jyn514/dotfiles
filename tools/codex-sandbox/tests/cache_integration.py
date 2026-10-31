"""Check the image-seeded worker cache in a fresh offline container."""

import argparse
from pathlib import Path
import subprocess
import uuid


FIXTURE = Path(__file__).resolve().with_name("fixtures") / "node-cache.py"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, help="built final sandbox image")
    args = parser.parse_args()
    container = f"pi-cache-test-{uuid.uuid4().hex}"
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--interactive", "--name", container,
             "--network", "none", "--entrypoint", "python3", args.runtime, "-"],
            input=FIXTURE.read_text(), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=60,
        )
        print(result.stdout, end="")
        result.check_returncode()
    finally:
        subprocess.run(["docker", "rm", "--force", container],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


if __name__ == "__main__":
    main()
