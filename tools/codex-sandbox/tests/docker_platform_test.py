import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "lima/docker_platform.py"
spec = importlib.util.spec_from_file_location("docker_platform", SOURCE)
platform_policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform_policy)


class DockerPlatformTests(unittest.TestCase):
    def test_linux_selects_qemu_and_requires_kvm(self):
        with patch.object(platform_policy.platform, "system", return_value="Linux"), \
                patch.object(platform_policy.platform, "machine", return_value="x86_64"), \
                patch.object(platform_policy, "kvm_available", return_value=True):
            configuration = platform_policy.current()

        self.assertEqual("qemu", configuration.vm_type)
        self.assertEqual("x86_64", configuration.guest_arch)
        self.assertEqual("9p", configuration.mount_type)
        self.assertIsNone(configuration.default_client)

    def test_linux_without_kvm_is_rejected(self):
        with patch.object(platform_policy.platform, "system", return_value="Linux"), \
                patch.object(platform_policy.platform, "machine", return_value="x86_64"), \
                patch.object(platform_policy, "kvm_available", return_value=False):
            with self.assertRaisesRegex(ValueError, "/dev/kvm"):
                platform_policy.current()

    def test_macos_keeps_vz_and_virtiofs(self):
        with patch.object(platform_policy.platform, "system", return_value="Darwin"), \
                patch.object(platform_policy.platform, "machine", return_value="arm64"):
            configuration = platform_policy.current()

        self.assertEqual(("vz", "aarch64", "virtiofs"),
                         (configuration.vm_type, configuration.guest_arch, configuration.mount_type))


if __name__ == "__main__":
    unittest.main()
