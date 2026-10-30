import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "bin/transplant-commits"


class TransplantCommitsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        self.environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_NAME="Transplant Test",
            GIT_AUTHOR_EMAIL="transplant@example.invalid",
            GIT_COMMITTER_NAME="Transplant Test",
            GIT_COMMITTER_EMAIL="transplant@example.invalid",
            GIT_TERMINAL_PROMPT="0",
        )

    def git(self, repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            env=self.environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def commit_files(self, repo: Path, files: dict[str, str], subject: str) -> None:
        for name, content in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", subject)

    def init_repo(self, name: str, files: dict[str, str]) -> Path:
        repo = self.directory / name
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.commit_files(repo, files, "base")
        return repo

    def assert_committed_files(self, repo: Path, expected: dict[str, str]) -> None:
        names = self.git(repo, "ls-tree", "-rz", "--name-only", "HEAD").split("\0")[:-1]
        self.assertEqual(set(expected), set(names))
        for name, content in expected.items():
            self.assertEqual(content, self.git(repo, "show", f"HEAD:{name}"), name)
        self.assertEqual("", self.git(repo, "status", "--porcelain"))

    def transplant(self, source: str, target: str) -> None:
        result = subprocess.run(
            [str(COMMAND), "--from", source, "--to", target, "HEAD~1..HEAD"],
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_source_selection_preserves_whitespace_and_existing_path_conventions(self) -> None:
        for index, selected in enumerate(("selected", " selected", "selected ", " selected ", " ", "./selected/")):
            with self.subTest(selected=selected):
                source = self.init_repo(f"source-{index}", {"base.txt": "source base\n"})
                target = self.init_repo(f"target-{index}", {"base.txt": "target base\n"})
                directory = "selected" if selected == "./selected/" else selected
                files = {f"{directory}/payload.txt": "chosen source\n"}
                if directory.strip() != directory:
                    control = f"{directory.strip()}/payload.txt" if directory.strip() else "payload.txt"
                    files[control] = "wrong trimmed source\n"
                files["unselected/other.txt"] = "unselected source\n"
                self.commit_files(source, files, "distinct source sentinels")

                self.transplant(f"{source}:{selected}", str(target))

                self.assert_committed_files(target, {
                    "base.txt": "target base\n",
                    "payload.txt": "chosen source\n",
                })
                self.assert_committed_files(source, {"base.txt": "source base\n", **files})

    def test_target_selection_preserves_whitespace_and_existing_path_conventions(self) -> None:
        for index, selected in enumerate(("selected", " selected", "selected ", " selected ", " ", "./selected/")):
            with self.subTest(selected=selected):
                source = self.init_repo(f"source-{index}", {"base.txt": "source base\n"})
                self.commit_files(source, {"input/payload.txt": "chosen source\n"}, "payload")
                directory = "selected" if selected == "./selected/" else selected
                base = {
                    "base.txt": "target base\n",
                    f"{directory}/keep.txt": "chosen target sentinel\n",
                }
                if directory.strip() != directory:
                    control = f"{directory.strip()}/keep.txt" if directory.strip() else "keep.txt"
                    base[control] = "trimmed target sentinel\n"
                target = self.init_repo(f"target-{index}", base)

                self.transplant(f"{source}:input", f"{target}:{selected}")

                self.assert_committed_files(target, {
                    **base, f"{directory}/payload.txt": "chosen source\n",
                })

    def test_empty_or_omitted_optional_path_transplants_whole_repository(self) -> None:
        for index, suffix in enumerate(("", ":", ":./", ":/")):
            with self.subTest(suffix=suffix):
                source = self.init_repo(f"source-{index}", {"base.txt": "source base\n"})
                files = {"payload.txt": "root payload\n", "nested/file.txt": "nested payload\n"}
                self.commit_files(source, files, "whole repository payload")
                target = self.init_repo(f"target-{index}", {"base.txt": "target base\n"})

                self.transplant(f"{source}{suffix}", f"{target}{suffix}")

                self.assert_committed_files(target, {"base.txt": "target base\n", **files})


if __name__ == "__main__":
    unittest.main()
