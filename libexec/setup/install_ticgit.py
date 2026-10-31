#!/usr/bin/env python3
"""Build and install the TicGit fork used by the sandbox into Cargo's bin directory."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    revision = (ROOT / "tools/tic-proxy/native-revision").read_text(encoding="utf-8").strip()
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("tools/tic-proxy/native-revision must contain one full commit hash")
    print(f"Installing host TicGit at sandbox revision {revision[:12]}", flush=True)
    subprocess.run([
        "cargo", "install", "--git", "https://github.com/jyn514/ticgit.git",
        "--rev", revision, "--locked", "--force", "--bin", "ti", "ticgit",
    ], check=True)


if __name__ == "__main__":
    main()
