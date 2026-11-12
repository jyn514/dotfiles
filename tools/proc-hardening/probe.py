#!/usr/bin/env python3
"""Check parent and sibling proc reads against a disposable child."""

import argparse
import json
import os


def read_result(pid: int) -> dict[str, str]:
    result = {}
    for name in ("environ", "maps"):
        try:
            with open(f"/proc/{pid}/{name}", "rb") as file:
                file.read(1)
            result[name] = "readable"
        except PermissionError:
            result[name] = "denied"
        except OSError as error:
            result[name] = f"error:{error.errno}"
    return result


def run_probe() -> dict[str, dict[str, str]]:
    ready_read, ready_write = os.pipe()
    stop_read, stop_write = os.pipe()
    result_read, result_write = os.pipe()
    target = os.fork()
    if target == 0:
        os.close(ready_read)
        os.close(stop_write)
        os.close(result_read)
        os.close(result_write)
        os.environ["PROC_READ_GUARD_PROBE_SECRET"] = "probe-only"
        os.write(ready_write, b"1")
        os.close(ready_write)
        os.read(stop_read, 1)
        os.close(stop_read)
        os._exit(0)

    os.close(ready_write)
    os.close(stop_read)
    try:
        if os.read(ready_read, 1) != b"1":
            raise RuntimeError("target did not become ready")
        os.close(ready_read)
        sibling = os.fork()
        if sibling == 0:
            try:
                os.close(result_read)
                os.close(stop_write)
                payload = json.dumps(read_result(target)).encode()
                os.write(result_write, payload)
                os.close(result_write)
                os._exit(0)
            except BaseException:
                os._exit(1)
        os.close(result_write)
        sibling_result = json.loads(os.read(result_read, 4096).decode())
        os.close(result_read)
        _, sibling_status = os.waitpid(sibling, 0)
        if sibling_status != 0:
            raise RuntimeError("sibling reader failed")
        return {"parent": read_result(target), "sibling": sibling_result}
    finally:
        try:
            os.close(stop_write)
        except OSError:
            pass
        os.waitpid(target, 0)


def matches_expectation(result: dict[str, dict[str, str]], expectation: str) -> bool:
    parent = result["parent"]
    sibling = result["sibling"]
    if expectation == "baseline":
        return all(parent[name] == "readable" and sibling[name] == "readable"
                   for name in ("environ", "maps"))
    return all(parent[name] == "readable" and sibling[name] == "denied"
               for name in ("environ", "maps"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect", choices=("baseline", "protected"))
    args = parser.parse_args()
    result = run_probe()
    print(json.dumps(result, sort_keys=True))
    if args.expect is None or matches_expectation(result, args.expect):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
