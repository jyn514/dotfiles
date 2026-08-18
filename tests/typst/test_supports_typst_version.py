import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[2] / "bin" / "supports-typst-version"
SPEC = importlib.util.spec_from_loader(
    "supports_typst_version",
    SourceFileLoader("supports_typst_version", str(SCRIPT)),
)
assert SPEC is not None
assert SPEC.loader is not None
supports_typst_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supports_typst_version)


class LatestCompatibleTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.cache = Path(self.temporary_directory.name) / "index.json"
        patch = mock.patch.object(
            supports_typst_version, "cache_path", return_value=self.cache
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_reuses_fresh_index_and_selects_latest_compatible_version(self):
        index = [
            {"name": "other", "version": "9.0.0", "compiler": "0.1.0"},
            {"name": "example", "version": "1.0.0"},
            {"name": "example", "version": "1.2.0", "compiler": "0.12.0"},
            {"name": "example", "version": "2.0.0", "compiler": "0.14.0"},
        ]

        with mock.patch.object(
            supports_typst_version,
            "get",
            return_value=json.dumps(index).encode(),
        ) as get:
            result = supports_typst_version.latest_compatible(
                "example", "0.13.1"
            )
            cached_result = supports_typst_version.latest_compatible(
                "example", "0.13.1"
            )

        self.assertEqual(result, "1.2.0")
        self.assertEqual(cached_result, "1.2.0")
        get.assert_called_once_with(supports_typst_version.INDEX_URL)

    def test_refreshes_index_after_one_hour(self):
        old_index = [{"name": "example", "version": "1.0.0"}]
        new_index = [{"name": "example", "version": "2.0.0"}]

        with mock.patch.object(
            supports_typst_version,
            "get",
            side_effect=[
                json.dumps(old_index).encode(),
                json.dumps(new_index).encode(),
            ],
        ) as get:
            self.assertEqual(
                supports_typst_version.latest_compatible("example", "1.0.0"),
                "1.0.0",
            )
            stale = supports_typst_version.time.time() - 3601
            os.utime(self.cache, (stale, stale))
            self.assertEqual(
                supports_typst_version.latest_compatible("example", "1.0.0"),
                "2.0.0",
            )

        self.assertEqual(get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
