import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]


class ArchiveWebpageTests(unittest.TestCase):
    def test_archive_webpage_rejects_path_titles_and_serializes_metadata(self) -> None:
        harness = r"""
const Module = require("module");
const archive = process.argv[1];
const archiveArguments = JSON.parse(process.env.ARCHIVE_ARGUMENTS);
const state = { trees: [], renders: [], writes: [], spawns: [] };
const page = {
  title: 'quoted " title\nnext',
  evaluate: () => "complete",
  open: (_url, callback) => callback("success"),
  render: (path, options) => state.renders.push([path, options]),
};
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === "system") return { args: [archive, ...archiveArguments] };
  if (request === "fs") return {
    makeTree: path => { state.trees.push(path); return true; },
    write: (path, contents, mode) => state.writes.push([path, contents, mode]),
  };
  if (request === "webpage") return { create: () => page };
  if (request === "child_process") return {
    spawn: (command, args) => {
      state.spawns.push([command, args]);
      return { on: (_event, callback) => callback(0) };
    },
  };
  return originalLoad(request, parent, isMain);
};
global.setTimeout = callback => callback();
global.phantom = { exit: code => { throw { archiveExit: true, code }; } };
let status = 0;
try {
  require(archive);
} catch (error) {
  if (!error.archiveExit) throw error;
  status = error.code;
}
console.log("__RESULT__" + JSON.stringify({ status, state }));
"""

        def run_archive(*arguments: str) -> tuple[int, dict[str, list]]:
            result = subprocess.run(
                ["node", "-e", harness, str(ROOT / "bin/archive-webpage")],
                env=os.environ | {"ARCHIVE_ARGUMENTS": json.dumps(arguments)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            output = next(
                line.removeprefix("__RESULT__")
                for line in result.stdout.splitlines()
                if line.startswith("__RESULT__")
            )
            archived = json.loads(output)
            return archived["status"], archived["state"]

        for title in (".", "..", "nested/name", r"nested\\name"):
            status, state = run_archive("output", "https://example.test", title)
            self.assertEqual(1, status, title)
            self.assertEqual([], state["trees"], title)
            self.assertEqual([], state["writes"], title)

        status, state = run_archive("output", "https://example.test", "page")
        self.assertEqual(0, status)
        self.assertEqual("output/page_meta.yaml", state["writes"][0][0])
        self.assertEqual("w", state["writes"][0][2])
        metadata = json.loads(state["writes"][0][1])
        self.assertEqual('quoted " title\nnext', metadata["title"])
        self.assertEqual("https://example.test", metadata["url"])
        self.assertEqual([], metadata["tags"])


if __name__ == "__main__":
    unittest.main()
