"""Listener ownership must survive partial gateway creation."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway


class GatewayTest(unittest.TestCase):
    def test_second_listener_spawn_failure_reaps_the_first(self):
        popen = subprocess.Popen
        children = []

        def spawn(_command, **kwargs):
            if children:
                raise OSError('second listener failed')
            child = popen(['sleep', '300'], **kwargs)
            children.append(child)
            return child

        with patch.object(gateway.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaisesRegex(OSError, 'second listener failed'):
                gateway.serve('host.lima.internal', 1234, 5678)
        self.assertIsNotNone(children[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(children[0].pid, 0)


if __name__ == '__main__':
    unittest.main()
