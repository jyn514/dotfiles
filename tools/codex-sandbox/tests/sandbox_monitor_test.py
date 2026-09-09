"""A failed observation must not masquerade as a completed workload."""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox_monitor


class MonitorTest(unittest.TestCase):
    def test_agent_wait_failure_removes_still_running_agent(self):
        for status, output, expected in ((1, "", 1), (0, "broken", 1), (0, "23\n", 0)):
            with self.subTest(status=status, output=output):
                reader, writer = os.pipe()
                os.close(writer)
                agent = Mock(stdout=os.fdopen(reader), returncode=status)
                agent.communicate.return_value = (output, "")
                with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "true")) as run, \
                     patch.object(subprocess, "Popen", return_value=agent):
                    result = sandbox_monitor.monitor(lambda args: args, [("agent", "owned")])
                self.assertEqual(expected, result)
                self.assertEqual(bool(expected), any(call.args[0][0] == "rm" for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
