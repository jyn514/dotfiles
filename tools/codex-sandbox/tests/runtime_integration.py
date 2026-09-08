#!/usr/bin/env python3
"""Opt-in real image, transport, network identity, EOF, and cancellation contract."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sandbox_runtime import image_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("podman", "lima"))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--base", required=True, help="already local Alpine-compatible image")
    args = parser.parse_args()
    runtime = image_runtime(args.provider, args.state)
    before = set()
    if args.provider == "lima":
        before = {item["Image"]["Name"] for item in json.loads(runtime.run(
            ["image", "inspect", "--mode=native", args.base], capture_output=True).stdout)}
    base = runtime.resolve_image(args.base)
    name = "sandbox-runtime-test-" + uuid.uuid4().hex[:12]
    tag = "localhost/" + name + ":test"
    containers = []
    image = None
    directory = runtime.host.state / "scratch" if args.provider == "lima" else None
    with tempfile.TemporaryDirectory(prefix="runtime contract ", dir=directory) as temporary:
        context = Path(temporary)
        (context / "marker").write_text(name)
        (context / "Dockerfile").write_text(
            "ARG BASE_IMAGE\nFROM ${BASE_IMAGE} AS local\nCOPY marker /marker\n"
            "FROM local\nWORKDIR /\n"
        )
        try:
            image = runtime.build(tag, context / "Dockerfile", context,
                                  build_args=["BASE_IMAGE=" + base.reference])
            if args.provider == "lima":
                # Simulate a stale caller trying to publish another source at
                # an immutable reference already used by this session.
                runtime.register_reference(base.reference, image.reference)
                assert runtime.inspect_image(image.reference).content == image.content
            # Retargeting a mutable alias must not change the already resolved image.
            runtime.run(["tag", base.reference, tag], stdout=subprocess.DEVNULL)
            container = name + "-live"
            containers.append(container)
            argv = runtime.workload_argv(image, ["-d", "--name", container,
                "--network", "codex-public-only", "--dns", "10.0.2.3",
                "--cap-drop=ALL", "--security-opt=no-new-privileges"], ["sleep", "300"])
            subprocess.run(argv, check=True, stdout=subprocess.DEVNULL)
            assert runtime.container_matches_image(container, image), "wrong live image identity"
            assert not runtime.container_matches_image(container, base), "base image accepted as derived image"
            address = runtime.network_address(container, "codex-public-only")
            assert address, "missing live CNI address"
            marker = runtime.run(["exec", container, "cat", "/marker"], capture_output=True).stdout
            assert marker == name, "mutable alias changed workload content"
            literal = "spaces ' $() `literal` ; newline\nend"
            output = runtime.run(["exec", container, "printf", "%s", literal], capture_output=True).stdout
            assert output == literal, "transport changed argument boundaries"
            failure = runtime.run(["exec", container, "false"], check=False, capture_output=True)
            assert failure.returncode == 1, "exec status was lost"
            runtime.terminate(container)
            containers.remove(container)

            container = name + "-eof"
            containers.append(container)
            with runtime.environment_file({"OWNED_VALUE": literal.replace("\n", " ")}) as environment:
                environment_path = Path(environment[1])
                argv = runtime.workload_argv(image, ["--name", container, "--interactive",
                    "--network", "none", *environment], ["cat"])
                process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True)
                output, errors = process.communicate("owned stdin\n", timeout=30)
                assert process.returncode == 0 and output == "owned stdin\n", errors
                assert runtime.wait(container) == 0, "EOF workload did not exit normally"
                observed = runtime.run(["inspect", "--format", "{{json .Config.Env}}", container],
                                       capture_output=True).stdout
                assert "OWNED_VALUE=" in observed, "host environment did not reach workload"
            assert not environment_path.exists(), "staged environment survived its owner"

            container = name + "-cancel"
            containers.append(container)
            argv = runtime.workload_argv(image, ["--name", container, "--network", "none"],
                                         ["sleep", "300"])
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                # Wait until the daemon sees the owned process, not an arbitrary sleep.
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    result = runtime.run(["inspect", "--format", "{{.State.Running}}", container],
                                         check=False, capture_output=True)
                    if result.returncode == 0 and result.stdout.strip() == "true":
                        break
                    if process.poll() is not None:
                        raise AssertionError("workload exited before cancellation")
                    time.sleep(0.1)
                else:
                    raise AssertionError("workload never became ready")
                runtime.terminate(container)
                process.communicate(timeout=30)
                assert process.returncode != 0, "cancellation reported success"
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            container = name + "-signal"
            containers.append(container)
            fixture = [sys.executable, str(Path(__file__).with_name("runtime_signal_fixture.py")),
                       "--provider", args.provider, "--image", image.reference, "--name", container]
            if args.state:
                fixture += ["--state", str(args.state)]
            process = subprocess.Popen(fixture, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    result = runtime.run(["inspect", "--format", "{{.State.Running}}", container],
                                         check=False, capture_output=True)
                    if result.returncode == 0 and result.stdout.strip() == "true":
                        break
                    if process.poll() is not None:
                        raise AssertionError(process.communicate())
                    time.sleep(0.1)
                else:
                    raise AssertionError("signal fixture never became ready")
                process.terminate()
                output, errors = process.communicate(timeout=40)
                assert process.returncode == 143, (output, errors, process.returncode)
                absent = runtime.run(["inspect", container], check=False, capture_output=True)
                assert absent.returncode != 0, "SIGTERM left the owned container alive"
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            print(f"{args.provider}: local FROM, immutable run, image/network identity, argv, status, EOF, cancellation, host SIGTERM passed")
        finally:
            for container in containers:
                runtime.run(["rm", "--force", container], check=False,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            runtime.run(["image", "rm", tag], check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if args.provider == "lima":
                references = {base.reference, base.reference.split("@", 1)[0]}
                if image is not None:
                    references.update((image.reference, image.reference.split("@", 1)[0]))
                for reference in references - before:
                    # ctr removes this exact registration, not every alias of
                    # an image that might already belong to another consumer.
                    runtime.guest(["containerd-rootless-setuptool.sh", "nsenter", "--",
                        "ctr", "--namespace", runtime.record["namespace"], "images", "rm", reference],
                        stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
