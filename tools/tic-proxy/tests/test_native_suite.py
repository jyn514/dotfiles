"""Opt-in route from dev/test discovery to the complete pinned Cargo suite.

Set TIC_PROXY_NATIVE_REPOSITORY to an owned local fork containing native-revision.
The build helper archives the Git object; mutable working-tree files are not input.
"""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TicNativeSuite(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('TIC_PROXY_NATIVE_REPOSITORY'),
                         'opt in with TIC_PROXY_NATIVE_REPOSITORY to build the pinned local fork')
    def test_complete_pinned_native_and_broker_suite(self):
        output = subprocess.run(
            [str(ROOT / 'build-local'), os.environ['TIC_PROXY_NATIVE_REPOSITORY'], 'test'],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900,
        )
        evidence = ROOT.parents[1] / 'target/tic-proxy-build/discovered-native.log'
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(output.stdout)
        self.assertEqual(output.returncode, 0, output.stdout)
