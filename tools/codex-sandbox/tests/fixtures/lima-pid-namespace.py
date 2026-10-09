#!/usr/bin/env python3
"""Check the guard in a child PID namespace while retaining the host procfs."""

import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lima.host import Host, machines


try:
    os.kill(int(sys.argv[1]), 0)
except ProcessLookupError:
    pass
else:
    raise AssertionError("the live parent must be hidden by the child PID namespace")

with patch("lima.host.subprocess.run", side_effect=AssertionError("limactl was executed")):
    instance = object.__new__(Host)
    for operation in (machines, lambda: instance.guest_argv({"instance": "unused"}, "true")):
        try:
            operation()
        except ValueError as error:
            assert "nested PID namespace" in str(error), str(error)
        else:
            raise AssertionError("the nested PID namespace was accepted")

print("live parent hidden; Lima rejected before execution")
