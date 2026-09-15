#!/usr/bin/env python3

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = ROOT / "libexec" / "agent-wrappers"


class ContainerWrapperTests(unittest.TestCase):
    def test_container_wrappers_invoke_packaged_clients(self) -> None:
        for name in ("docker", "podman"):
            with self.subTest(name=name):
                wrapper = (WRAPPERS / name).read_text(encoding="utf-8")
                self.assertIn(
                    f"gateway-transport /opt/agent-tools/bin/{name}",
                    wrapper,
                )
                self.assertNotIn(f"/usr/local/bin/{name}", wrapper)


if __name__ == "__main__":
    unittest.main()
