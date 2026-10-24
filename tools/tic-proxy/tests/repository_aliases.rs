//! All canaries and aliases are owned disposable fixture resources.
#![cfg(unix)]
use std::{
    fs,
    os::unix::fs::{symlink, MetadataExt},
    path::PathBuf,
    process::Command,
};
use tempfile::TempDir;
use tic_proxy::repository::preflight;

struct Fixture {
    _root: TempDir,
    workspace: PathBuf,
    common: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let workspace = root.path().join("workspace");
        let output = Command::new("git")
            .args(["init", "--initial-branch=main"])
            .arg(&workspace)
            .env_clear()
            .env("PATH", std::env::var_os("PATH").unwrap())
            .env("HOME", root.path())
            .env("GIT_CONFIG_NOSYSTEM", "1")
            .env("GIT_CONFIG_GLOBAL", "/dev/null")
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let common = workspace.join(".git").canonicalize().unwrap();
        Self {
            _root: root,
            workspace,
            common,
        }
    }
    fn reject(&self, message: &str) {
        let error = preflight(&self.workspace, &self.common).unwrap_err();
        assert!(format!("{error:#}").contains(message), "{error:#}");
    }
    fn absent_store(&self) {
        for name in [
            "git-meta.sqlite",
            "git-meta.sqlite-wal",
            "git-meta.sqlite-shm",
        ] {
            assert!(fs::symlink_metadata(self.common.join(name)).is_err());
        }
    }
}

#[test]
fn absent_and_single_link_regular_packed_refs_need_no_native_or_sqlite_open() {
    let f = Fixture::new();
    let packed = f.common.join("packed-refs");
    preflight(&f.workspace, &f.common).unwrap();
    assert!(fs::symlink_metadata(&packed).is_err());
    f.absent_store();
    // Preflight checks only the entry's type/link count, not packed-ref grammar.
    for bytes in [
        b"# pack-refs with: peeled fully-peeled sorted \n".as_slice(),
        b"opaque bytes: readiness must not parse these".as_slice(),
    ] {
        fs::write(&packed, bytes).unwrap();
        let before = fs::symlink_metadata(&packed).unwrap();
        preflight(&f.workspace, &f.common).unwrap();
        let after = fs::symlink_metadata(&packed).unwrap();
        assert_eq!(
            (before.dev(), before.ino(), before.nlink(), before.len()),
            (after.dev(), after.ino(), after.nlink(), after.len())
        );
        assert_eq!(fs::read(&packed).unwrap(), bytes);
        f.absent_store();
    }
}

#[test]
fn packed_refs_aliases_and_special_files_reject_without_native_or_sqlite_work() {
    use nix::{sys::stat::Mode, unistd::mkfifo};
    for kind in [
        "symlink",
        "dangling",
        "symlink-fifo",
        "fifo",
        "directory",
        "hardlink",
    ] {
        let f = Fixture::new();
        let packed = f.common.join("packed-refs");
        let canary = f
            .workspace
            .join("ordinary-guest-writable-packed-refs-canary");
        if kind == "symlink-fifo" {
            mkfifo(&canary, Mode::S_IRUSR | Mode::S_IWUSR).unwrap();
        } else {
            fs::write(&canary, b"preserve guest-writable target bytes").unwrap();
        }
        match kind {
            "symlink" | "symlink-fifo" => symlink(&canary, &packed).unwrap(),
            "dangling" => symlink("missing-packed-refs-target", &packed).unwrap(),
            "fifo" => mkfifo(&packed, Mode::S_IRUSR | Mode::S_IWUSR).unwrap(),
            "directory" => fs::create_dir(&packed).unwrap(),
            "hardlink" => fs::hard_link(&canary, &packed).unwrap(),
            _ => unreachable!(),
        }
        let before = fs::symlink_metadata(&packed).unwrap();
        // Neither FIFO has a writer. Opening either would block readiness.
        let error = preflight(&f.workspace, &f.common).unwrap_err();
        let message = format!("{error:#}");
        assert!(message.contains(packed.to_str().unwrap()), "{message}");
        assert!(
            message.contains(if kind == "hardlink" {
                "hard-linked repository file"
            } else {
                "unsupported non-regular file or symlink"
            }),
            "{message}"
        );
        let after = fs::symlink_metadata(&packed).unwrap();
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
        if kind != "symlink-fifo" {
            assert_eq!(
                fs::read(&canary).unwrap(),
                b"preserve guest-writable target bytes"
            );
        }
        f.absent_store();
    }
}

#[test]
fn current_database_and_each_sidecar_reject_writable_workspace_hardlink_aliases() {
    for name in [
        "git-meta.sqlite",
        "git-meta.sqlite-wal",
        "git-meta.sqlite-shm",
    ] {
        let f = Fixture::new();
        let store = f.common.join(name);
        let alias = f.workspace.join("ordinary-writable-canary");
        fs::write(&store, b"not SQLite: preserve exact store bytes").unwrap();
        fs::hard_link(&store, &alias).unwrap();
        let before = fs::symlink_metadata(&store).unwrap();
        assert_eq!(before.nlink(), 2);
        assert_eq!(before.ino(), fs::metadata(&alias).unwrap().ino());
        f.reject("hard-linked repository file");
        assert_eq!(
            fs::read(&store).unwrap(),
            b"not SQLite: preserve exact store bytes"
        );
        assert_eq!(
            fs::read(&alias).unwrap(),
            b"not SQLite: preserve exact store bytes"
        );
        let after = fs::symlink_metadata(&store).unwrap();
        assert_eq!(
            (
                after.dev(),
                after.ino(),
                after.nlink(),
                after.len(),
                after.mtime(),
                after.mtime_nsec()
            ),
            (
                before.dev(),
                before.ino(),
                before.nlink(),
                before.len(),
                before.mtime(),
                before.mtime_nsec()
            )
        );
        for other in [
            "git-meta.sqlite",
            "git-meta.sqlite-wal",
            "git-meta.sqlite-shm",
        ] {
            if other != name {
                assert!(fs::symlink_metadata(f.common.join(other)).is_err());
            }
        }
    }
}

#[test]
fn current_store_symlinks_and_nonregular_entries_are_refused_without_opening() {
    use nix::{sys::stat::Mode, unistd::mkfifo};
    for name in [
        "git-meta.sqlite",
        "git-meta.sqlite-wal",
        "git-meta.sqlite-shm",
    ] {
        for kind in ["symlink", "dangling", "directory", "fifo"] {
            let f = Fixture::new();
            let store = f.common.join(name);
            let canary = f.workspace.join("ordinary-writable-canary");
            fs::write(&canary, b"preserve external target").unwrap();
            match kind {
                "symlink" => symlink(&canary, &store).unwrap(),
                "dangling" => symlink("missing-target", &store).unwrap(),
                "directory" => fs::create_dir(&store).unwrap(),
                "fifo" => mkfifo(&store, Mode::S_IRUSR | Mode::S_IWUSR).unwrap(),
                _ => unreachable!(),
            }
            // The FIFO would block if readiness tried opening its bytes.
            let before = fs::symlink_metadata(&store).unwrap();
            f.reject("unsupported non-regular file or symlink");
            let after = fs::symlink_metadata(&store).unwrap();
            assert_eq!(
                (before.dev(), before.ino(), before.mode(), before.nlink()),
                (after.dev(), after.ino(), after.mode(), after.nlink())
            );
            assert_eq!(fs::read(&canary).unwrap(), b"preserve external target");
        }
    }
}

#[test]
fn config_and_enabled_worktree_config_reject_workspace_hardlink_aliases() {
    for name in ["config", "config.worktree"] {
        let f = Fixture::new();
        fs::write(
            f.common.join("config"),
            b"[extensions]\nworktreeConfig = true\n",
        )
        .unwrap();
        if name == "config.worktree" {
            fs::write(f.common.join(name), b"[user]\nname = Preserved Canary\n").unwrap();
        }
        let config = f.common.join(name);
        let before = fs::read(&config).unwrap();
        let alias = f.workspace.join("ordinary-writable-config-canary");
        fs::hard_link(&config, &alias).unwrap();
        f.reject("hard-linked repository file");
        assert_eq!(fs::read(&config).unwrap(), before);
        assert_eq!(fs::read(&alias).unwrap(), before);
        assert_eq!(fs::metadata(&config).unwrap().nlink(), 2);
        f.absent_store();
    }
}

#[test]
fn separate_gitdir_pointer_rejects_writable_workspace_hardlink_alias() {
    let mut f = Fixture::new();
    let separate = f._root.path().join("separate-metadata");
    fs::rename(&f.common, &separate).unwrap();
    f.common = separate.canonicalize().unwrap();
    let gitfile = f.workspace.join(".git");
    let content = format!("gitdir: {}\n", f.common.display());
    fs::write(&gitfile, &content).unwrap();
    let alias = f.workspace.join("ordinary-writable-gitfile-canary");
    fs::hard_link(&gitfile, &alias).unwrap();
    f.reject("hard-linked repository file");
    assert_eq!(fs::read_to_string(&gitfile).unwrap(), content);
    assert_eq!(fs::read_to_string(&alias).unwrap(), content);
    f.absent_store();
}

#[test]
fn loose_objects_packs_indices_and_midx_reject_workspace_hardlink_aliases() {
    for relative in [
        "objects/ab/00000000000000000000000000000000000000",
        "objects/pack/pack-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pack",
        "objects/pack/pack-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.idx",
        "objects/pack/multi-pack-index",
    ] {
        let f = Fixture::new();
        let object = f.common.join(relative);
        fs::create_dir_all(object.parent().unwrap()).unwrap();
        // Deliberately invalid MIDX: alias refusal must happen before parsing.
        fs::write(&object, b"preserve opaque object canary bytes").unwrap();
        let alias = f.workspace.join("ordinary-writable-object-canary");
        fs::hard_link(&object, &alias).unwrap();
        f.reject("hard-linked repository file");
        assert_eq!(
            fs::read(&object).unwrap(),
            b"preserve opaque object canary bytes"
        );
        assert_eq!(
            fs::read(&alias).unwrap(),
            b"preserve opaque object canary bytes"
        );
        assert_eq!(fs::metadata(&object).unwrap().nlink(), 2);
        f.absent_store();
    }
}
