#!/usr/bin/python3
"""Fault injector installed only in the owned network fixture VM."""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys


loader = importlib.machinery.SourceFileLoader("public_only", "/usr/local/libexec/cni/public-only")
spec = importlib.util.spec_from_loader(loader.name, loader)
policy = importlib.util.module_from_spec(spec)
loader.exec_module(policy)


def main():
    config = json.load(sys.stdin)
    mode = config.pop("fixtureFailure")
    if mode not in ("route-error", "route-kill", "dns-error", "dns-kill"):
        raise ValueError("unknown fixture failure")
    original = policy.in_namespace

    def mutate(*args):
        result = original(*args)
        at_route = "prohibit" in args and "replace" in args
        at_dns = "rule" in args and "add" in args and "tcp" in args
        if os.environ["CNI_COMMAND"] == "ADD" and (
            (mode.startswith("route-") and at_route) or
            (mode.startswith("dns-") and at_dns)
        ):
            # Capture actual kernel state before failing, so an earlier unrelated
            # startup error cannot count as evidence of partial-policy rejection.
            evidence = {"mode": mode, "namespace": os.environ["CNI_NETNS"],
                        "routes": json.loads(original("/usr/sbin/ip", "-j", "-4", "route", "show", "type", "prohibit")),
                        "rules": json.loads(original("/usr/sbin/ip", "-j", "-4", "rule", "show"))}
            Path("/tmp/codex-sandbox-policy-fault.json").write_text(json.dumps(evidence))
            if mode.endswith("kill"):
                os.kill(os.getpid(), signal.SIGKILL)
            raise RuntimeError("injected failure after namespace mutation")
        return result

    policy.in_namespace = mutate
    # The real entrypoint reads stdin. Supply the same parsed CNI configuration
    # without the fixture-only selector; production policy has no fault switches.
    import io
    sys.stdin = io.StringIO(json.dumps(config))
    result = policy.main()
    if result is not None:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
