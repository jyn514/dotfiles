//! Discovery must not read HEAD/layout redirects before its support checks.
#![cfg(unix)]
use nix::{sys::stat::Mode, unistd::mkfifo};
use std::{
    fs,
    os::unix::fs::{symlink, MetadataExt},
    path::{Path, PathBuf},
    process::Command,
};
use tempfile::TempDir;
use tic_proxy::repository::preflight;

struct Fixture {
    _root: TempDir,
    workspace: PathBuf,
    common: PathBuf,
    invocation: PathBuf,
}
fn git(cwd: &Path, args: &[&str]) {
    let out = Command::new("git")
        .args(args)
        .current_dir(cwd)
        .env_clear()
        .env("PATH", std::env::var_os("PATH").unwrap())
        .env("HOME", cwd)
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}
impl Fixture {
    fn new(linked: bool) -> Self {
        let root = tempfile::tempdir().unwrap();
        let main = root.path().join("main");
        git(
            root.path(),
            &["init", "--initial-branch=main", main.to_str().unwrap()],
        );
        let common = main.join(".git").canonicalize().unwrap();
        let (workspace, invocation) = if linked {
            git(
                &main,
                &[
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "fixture",
                ],
            );
            let workspace = root.path().join("linked");
            git(
                &main,
                &[
                    "worktree",
                    "add",
                    "-b",
                    "linked",
                    workspace.to_str().unwrap(),
                ],
            );
            let invocation = fs::read_dir(common.join("worktrees"))
                .unwrap()
                .next()
                .unwrap()
                .unwrap()
                .path();
            (workspace, invocation)
        } else {
            (main, common.clone())
        };
        Self {
            _root: root,
            workspace,
            common,
            invocation,
        }
    }
    fn rejects_unsafe_control_without_opening(&self, control: &Path, kind: &str) {
        let original = fs::read(control).unwrap();
        fs::remove_file(control).unwrap();
        let canary = self.workspace.join("ordinary-writable-control-canary");
        let expected = match kind {
            "hardlink" => {
                fs::write(&canary, &original).unwrap();
                fs::hard_link(&canary, control).unwrap();
                "hard-linked repository file"
            }
            "symlink" => {
                fs::write(&canary, &original).unwrap();
                symlink(&canary, control).unwrap();
                "unsupported non-regular file or symlink"
            }
            "dangling" => {
                symlink("missing-control-target", control).unwrap();
                "unsupported non-regular file or symlink"
            }
            "fifo" => {
                mkfifo(control, Mode::S_IRUSR | Mode::S_IWUSR).unwrap();
                "unsupported non-regular file or symlink"
            }
            "symlink-fifo" => {
                mkfifo(&canary, Mode::S_IRUSR | Mode::S_IWUSR).unwrap();
                symlink(&canary, control).unwrap();
                "unsupported non-regular file or symlink"
            }
            "directory" => {
                fs::create_dir(control).unwrap();
                "unsupported non-regular file or symlink"
            }
            "oversized" => {
                fs::write(control, vec![b'x'; 64 * 1024 + 1]).unwrap();
                "repository discovery control exceeds preflight limit"
            }
            _ => unreachable!(),
        };
        let before = fs::symlink_metadata(control).unwrap();
        // Neither FIFO has any writer. Following/opening it would block here.
        let error = preflight(&self.workspace, &self.common).unwrap_err();
        assert!(
            format!("{error:#}").contains(expected),
            "{control:?} {kind}: {error:#}"
        );
        let after = fs::symlink_metadata(control).unwrap();
        assert_eq!(
            (
                before.dev(),
                before.ino(),
                before.mode(),
                before.nlink(),
                before.len()
            ),
            (
                after.dev(),
                after.ino(),
                after.mode(),
                after.nlink(),
                after.len()
            )
        );
        if matches!(kind, "hardlink" | "symlink") {
            assert_eq!(fs::read(&canary).unwrap(), original);
        }
        for name in [
            "git-meta.sqlite",
            "git-meta.sqlite-wal",
            "git-meta.sqlite-shm",
        ] {
            assert!(fs::symlink_metadata(self.common.join(name)).is_err());
            assert!(fs::symlink_metadata(self.invocation.join(name)).is_err());
        }
    }
}
const UNSAFE: &[&str] = &[
    "hardlink",
    "symlink",
    "dangling",
    "fifo",
    "symlink-fifo",
    "directory",
    "oversized",
];

#[test]
fn main_head_is_checked_before_the_public_locator_can_read_it() {
    for kind in UNSAFE {
        let f = Fixture::new(false);
        f.rejects_unsafe_control_without_opening(&f.common.join("HEAD"), kind);
    }
}

#[test]
fn linked_invocation_and_common_heads_are_both_checked_before_locator_reads() {
    for common_head in [false, true] {
        for kind in UNSAFE {
            let f = Fixture::new(true);
            let dir = if common_head {
                &f.common
            } else {
                &f.invocation
            };
            f.rejects_unsafe_control_without_opening(&dir.join("HEAD"), kind);
        }
    }
}

#[test]
fn bare_head_is_checked_before_public_locator_reads() {
    for kind in UNSAFE {
        let root = tempfile::tempdir().unwrap();
        let bare = root.path().join("bare.git");
        git(root.path(), &["init", "--bare", bare.to_str().unwrap()]);
        let bare = bare.canonicalize().unwrap();
        let f = Fixture {
            _root: root,
            workspace: bare.clone(),
            common: bare.clone(),
            invocation: bare,
        };
        f.rejects_unsafe_control_without_opening(&f.common.join("HEAD"), kind);
    }
}

#[test]
fn unrecognized_root_candidate_never_falls_back_to_unchecked_parent_head() {
    let f = Fixture::new(false);
    // is_git deliberately tolerates invalid HEAD syntax, so remove its required
    // object directory to make the exact candidate unrecognizable instead.
    fs::remove_dir_all(f.common.join("objects")).unwrap();
    let parent_git = f._root.path().join(".git");
    fs::create_dir(&parent_git).unwrap();
    mkfifo(&parent_git.join("HEAD"), Mode::S_IRUSR | Mode::S_IWUSR).unwrap();
    let error = preflight(&f.workspace, &f.common).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("locate root repository without loading configuration"),
        "{error:#}"
    );
    assert!(fs::symlink_metadata(f.common.join("git-meta.sqlite")).is_err());
}

#[test]
fn root_gitfile_is_checked_before_public_gitfile_parsing() {
    for kind in UNSAFE {
        let f = Fixture::new(true);
        // A directory here is a different candidate, not a gitfile. Its missing
        // HEAD still rejects without reading a FIFO; the expected message in
        // this shared helper applies specifically to non-directory controls.
        if *kind == "directory" {
            continue;
        }
        f.rejects_unsafe_control_without_opening(&f.workspace.join(".git"), kind);
    }
}

#[test]
fn commondir_and_gitdir_are_checked_before_public_layout_parsing() {
    for name in ["commondir", "gitdir"] {
        for kind in UNSAFE {
            let f = Fixture::new(true);
            f.rejects_unsafe_control_without_opening(&f.invocation.join(name), kind);
        }
    }
}
