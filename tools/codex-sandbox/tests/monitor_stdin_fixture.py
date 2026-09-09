"""Run a standalone monitor against an engine that observes its stdin."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import time


if sys.argv[1] == "engine":
    operation = sys.argv[2]
    data = os.read(0, 1)
    with Path(os.environ["MONITOR_INPUT_LOG"]).open("a") as stream:
        stream.write(json.dumps({"operation": operation, "input": data.decode(), "pid": os.getpid()}) + "\n")
    if operation == "inspect":
        print("true")
    elif operation == "wait" and (sys.argv[-1] == "agent" or os.environ.get("MONITOR_STAY_RUNNING")):
        time.sleep(20)
else:
    source = Path(__file__).resolve().parents[1] / "sandbox-proxies.py"
    spec = importlib.util.spec_from_file_location("sandbox_proxies", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Engine:
        def argv(self, arguments):
            return [sys.executable, str(Path(__file__).resolve()), "engine", *arguments]

    module.state_runtime = lambda _: Engine()
    if sys.argv[1] == "guest":
        raise SystemExit(module.monitor(Engine().argv, [("agent", "agent"), ("proxy", "proxy")], parent_fd=0))
    raise SystemExit(module.main(["monitor", "--state", sys.argv[2], "--agent", "agent"]))
