"""Behavioral tests for shared per-launch relay resource topology."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay_lifecycle import RelayResourcePlan


class RelayResourcePlanTest(unittest.TestCase):
    def test_gateway_and_keychain_shape_derives_cleanup_and_recovery_edges(self):
        for prefix in ("gateway", "keychain"):
            with self.subTest(prefix=prefix):
                plan = RelayResourcePlan(
                    prefix + "-link", prefix + "-egress", prefix + "-container",
                )
                container = "container:" + prefix + "-container"
                dependencies = (
                    "network:" + prefix + "-link",
                    "network:" + prefix + "-egress",
                )
                self.assertEqual(dependencies, plan.bound_topology()[container])
                resources = plan.recovery_resources(
                    (container, *dependencies), "owner",
                )
                self.assertEqual(
                    [prefix + "-link", prefix + "-egress"],
                    resources[0]["dependencies"],
                )


if __name__ == "__main__":
    unittest.main()
