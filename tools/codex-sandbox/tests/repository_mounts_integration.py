"""Exercise the launcher's repository mounts on the existing Docker VM."""

import argparse
from pathlib import Path
import runpy
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docker_runtime import Docker
from repository_mounts_test import LAUNCHER, repository_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    image = runtime.inspect_image(args.image)
    launcher = runpy.run_path(str(LAUNCHER))
    mounts = launcher["agent_repository_mounts"]
    mounts.__globals__["OUTER_RUNTIME"] = runtime
    cases = [("directory", False, "common")]
    cases.extend(("linked", absolute, backend)
                 for absolute in (False, True) for backend in ("worktree", "common"))
    for layout, absolute, backend in cases:
        with tempfile.TemporaryDirectory(prefix="repository-mounts-", dir=runtime.host.state / "scratch") as directory:
            state, git_dir, common = repository_fixture(Path(directory), layout, absolute=absolute)
            state.git_repository = git_dir if backend == "worktree" else common
            state.git_mount_source = state.git_repository
            entry = state.repository / ".git"
            original = entry.read_bytes() if entry.is_file() else None
            command = mounts(state)
            launcher["check_mount_destinations"](command)
            expected_common = common if absolute else Path("/src/team/main/.git")
            probe = Path(__file__).with_name("repository_mounts_probe.py")
            options = [
                "--network", "none", "--cap-drop=ALL", "--read-only",
                "--entrypoint", "python3", "--workdir", str(state.container_repository),
                "--env", f"EXPECTED_COMMON={expected_common}",
                "--mount", f"type=bind,src={probe},dst=/probe.py,readonly", *command,
            ]
            name = "repository-mounts-" + uuid.uuid4().hex[:12]
            with runtime.workload(image, name, options, ["/probe.py", layout]) as process:
                assert process.wait(timeout=20) == 0
            assert (state.repository / "created").read_text() == "writable"
            if original is not None:
                assert entry.read_bytes() == original
            print(f"PASS: {layout}, absolute={absolute}, backend={backend}", flush=True)


if __name__ == "__main__":
    main()
