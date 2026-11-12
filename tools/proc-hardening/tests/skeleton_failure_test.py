"""Native libbpf allocation/errno regressions; no BPF programs are loaded."""
import errno
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
WRAPPED = (
    "calloc", "close", "strerror", "access", "fopen", "mkdir", "rmdir",
    "bpf_object__load_skeleton", "bpf_object__attach_skeleton", "bpf_link_update",
    "bpf_link__pin", "bpf_link__unpin",
    "bpf_link__open", "bpf_link__fd", "bpf_link__disconnect", "bpf_link__destroy",
    "bpf_link_get_info_by_fd", "bpf_prog_get_fd_by_id", "bpf_prog_get_info_by_fd",
    "bpf_map_get_fd_by_id", "bpf_map_get_info_by_fd", "bpf_map_lookup_elem",
)


@unittest.skipUnless(sys.platform == "linux", "native BPF build requires Linux BTF")
class SkeletonFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="proc-skeleton-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        for tool in ("make", "clang", "bpftool", "pkg-config", "cc"):
            if shutil.which(tool) is None:
                raise RuntimeError(f"{tool} is required for native skeleton tests")
        cls.checked([
            "make", "-C", str(SOURCE), f"BUILD_DIR={cls.build}",
            str(cls.build / "proc-read-guard.skel.h"),
        ])
        cflags = shlex.split(cls.checked(["pkg-config", "--cflags", "libbpf"]).stdout)
        libraries = shlex.split(cls.checked(["pkg-config", "--libs", "libbpf"]).stdout)
        cls.program = cls.build / "skeleton-failures"
        # One symbol list owns both linker interposition and API type checks.
        (cls.build / "wrapper_types.h").write_text("".join(
            f"__typeof__({name}) __wrap_{name};\n" for name in WRAPPED
        ))
        cls.checked([
            "cc", "-std=gnu11", "-O0", "-g", "-Wall", "-Wextra", "-Werror",
            "-I", str(cls.build), *cflags, str(HERE / "skeleton_failure_harness.c"),
            *[f"-Wl,--wrap={name}" for name in WRAPPED], *libraries,
            "-o", str(cls.program),
        ])

    @classmethod
    def checked(cls, command):
        result = subprocess.run(command, text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result

    def run_case(self, mode, allocation):
        return subprocess.run(
            [str(self.program), mode, str(allocation)],
            text=True, capture_output=True, timeout=10,
        )

    def test_normal_open_destroy_and_every_direct_allocation_failure(self):
        normal = self.run_case("allocation", 0)
        self.assertEqual(0, normal.returncode, normal.stderr)
        allocations = int(normal.stdout)
        self.assertGreater(allocations, 0)
        for allocation in range(1, allocations + 1):
            with self.subTest(allocation=allocation):
                failed = self.run_case("allocation", allocation)
                self.assertEqual(0, failed.returncode, failed.stderr)
                self.assertEqual(allocation, int(failed.stdout))

    def test_update_failure_preserves_primary_errno_across_cleanup(self):
        # Fail the first constructor allocation after validating the old pin.
        failed = self.run_case("errno", 1)
        self.assertEqual(1, failed.returncode, failed.stderr)
        self.assertIn(f"close program fd: errno-{errno.EIO}", failed.stderr)
        self.assertIn(f"open BPF skeleton: errno-{errno.ENOMEM}", failed.stderr)
        self.assertNotIn(f"open BPF skeleton: errno-{errno.EACCES}", failed.stderr)


if __name__ == "__main__":
    unittest.main()
