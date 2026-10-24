use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};
use tempfile::TempDir;
use tic_proxy::repository::preflight;

struct Fixture {
    root: TempDir,
    workspace: PathBuf,
    common: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let workspace = root.path().join("main");
        git(
            root.path(),
            &["init", "--initial-branch=main", workspace.to_str().unwrap()],
        );
        let common = workspace.join(".git").canonicalize().unwrap();
        Self {
            root,
            workspace,
            common,
        }
    }
    fn linked(&self) -> PathBuf {
        git(
            &self.workspace,
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
        let linked = self.root.path().join("linked");
        git(
            &self.workspace,
            &["worktree", "add", "-b", "linked", linked.to_str().unwrap()],
        );
        linked
    }
    fn assert_absent(&self) {
        for name in [
            "git-meta.sqlite",
            "git-meta.sqlite-wal",
            "git-meta.sqlite-shm",
        ] {
            assert!(fs::symlink_metadata(self.common.join(name)).is_err());
        }
    }
    fn rejected(&self, workspace: &Path, message: &str) {
        let error = preflight(workspace, &self.common).unwrap_err();
        assert!(format!("{error:#}").contains(message), "{error:#}");
        self.assert_absent();
    }
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
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn main_and_linked_roots_share_identity_without_creating_database() {
    let f = Fixture::new();
    let linked = f.linked();
    for workspace in [&f.workspace, &linked] {
        let context = preflight(workspace, &f.common).unwrap();
        assert_eq!(context.workspace, workspace.canonicalize().unwrap());
        assert_eq!(context.common_dir, f.common);
    }
    f.assert_absent();
}

#[test]
fn ordinary_main_and_linked_subdirectories_are_not_fixed_discovery_authority() {
    let f = Fixture::new();
    let linked = f.linked();
    for root in [&f.workspace, &linked] {
        let nested = root.join("one/two");
        fs::create_dir_all(&nested).unwrap();
        // Before a guest could create nested/.git after readiness, startup must
        // already refuse this cwd, even though it currently finds the expected
        // common directory by walking upwards.
        f.rejected(
            &nested,
            "accepted workspace must be the discovered worktree root",
        );
        assert!(!nested.join(".git").exists());
    }
}

#[test]
fn repository_created_below_accepted_root_does_not_change_fixed_root_identity() {
    let f = Fixture::new();
    let accepted = preflight(&f.workspace, &f.common).unwrap();
    let nested = f.workspace.join("guest-created-repository");
    git(&f.workspace, &["init", nested.to_str().unwrap()]);
    assert_eq!(preflight(&f.workspace, &f.common).unwrap(), accepted);
    f.rejected(&nested, "repository common identity mismatch");
    assert!(!nested.join(".git/git-meta.sqlite").exists());
}

#[test]
fn readiness_does_not_open_even_invalid_existing_sqlite_or_sidecars() {
    let f = Fixture::new();
    for name in [
        "git-meta.sqlite",
        "git-meta.sqlite-wal",
        "git-meta.sqlite-shm",
    ] {
        fs::write(f.common.join(name), b"not SQLite; preserve exactly").unwrap();
    }
    preflight(&f.workspace, &f.common).unwrap();
    for name in [
        "git-meta.sqlite",
        "git-meta.sqlite-wal",
        "git-meta.sqlite-shm",
    ] {
        assert_eq!(
            fs::read(f.common.join(name)).unwrap(),
            b"not SQLite; preserve exactly"
        );
    }
}

#[test]
fn bare_and_separate_gitdir_layouts_are_supported() {
    let root = tempfile::tempdir().unwrap();
    for name in ["bare.git", "unusual-bare"] {
        let bare = root.path().join(name);
        git(root.path(), &["init", "--bare", bare.to_str().unwrap()]);
        assert_eq!(
            preflight(&bare, &bare).unwrap().common_dir,
            bare.canonicalize().unwrap()
        );
        let nested = bare.join("ordinary-subdirectory");
        fs::create_dir(&nested).unwrap();
        assert!(preflight(&nested, &bare)
            .unwrap_err()
            .to_string()
            .contains("accepted workspace must be the discovered worktree root or the bare invocation git directory"));
        assert!(!bare.join("git-meta.sqlite").exists());
    }
    let workspace = root.path().join("separate-worktree");
    let common = root.path().join("metadata");
    git(
        root.path(),
        &[
            "init",
            "--separate-git-dir",
            common.to_str().unwrap(),
            workspace.to_str().unwrap(),
        ],
    );
    assert_eq!(
        preflight(&workspace, &common).unwrap().common_dir,
        common.canonicalize().unwrap()
    );
    let nested = workspace.join("ordinary-subdirectory");
    fs::create_dir(&nested).unwrap();
    assert!(preflight(&nested, &common)
        .unwrap_err()
        .to_string()
        .contains("accepted workspace must be the discovered worktree root"));
    assert!(!common.join("git-meta.sqlite").exists());
}

#[test]
fn expected_common_is_not_an_authority_to_select_another_repository() {
    let a = Fixture::new();
    let b = Fixture::new();
    assert!(preflight(&a.workspace, &b.common)
        .unwrap_err()
        .to_string()
        .contains("identity mismatch"));
    a.assert_absent();
    b.assert_absent();
}

#[test]
fn local_includes_including_inactive_conditions_are_refused() {
    for fixture in [
        include_str!("repository-fixtures/include.config"),
        include_str!("repository-fixtures/inactive-include.config"),
    ] {
        let f = Fixture::new();
        fs::write(f.common.join("config"), fixture).unwrap();
        f.rejected(&f.workspace, "includes are unsupported");
    }
}

#[cfg(unix)]
#[test]
fn include_canary_is_never_opened() {
    use nix::{sys::stat::Mode, unistd::mkfifo};
    let f = Fixture::new();
    let canary = f.root.path().join("include-canary");
    // Opening this FIFO for reading would block: no writer ever exists.
    mkfifo(&canary, Mode::S_IRUSR | Mode::S_IWUSR).unwrap();
    fs::write(
        f.common.join("config"),
        format!("[include]\npath = {}\n", canary.display()),
    )
    .unwrap();
    f.rejected(&f.workspace, "includes are unsupported");
}

#[test]
fn enabled_worktree_config_covers_both_native_opens() {
    for common_config in [false, true] {
        let f = Fixture::new();
        let linked = f.linked();
        git(
            &f.workspace,
            &["config", "extensions.worktreeConfig", "true"],
        );
        let admin = fs::read_dir(f.common.join("worktrees"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap()
            .path();
        let target = if common_config { &f.common } else { &admin };
        fs::write(
            target.join("config.worktree"),
            include_str!("repository-fixtures/inactive-include.config"),
        )
        .unwrap();
        f.rejected(&linked, "includes are unsupported");
    }
}

#[test]
fn main_worktree_config_and_malformed_local_config_fail_before_database_creation() {
    let f = Fixture::new();
    git(
        &f.workspace,
        &["config", "extensions.worktreeConfig", "true"],
    );
    fs::write(
        f.common.join("config.worktree"),
        include_str!("repository-fixtures/include.config"),
    )
    .unwrap();
    f.rejected(&f.workspace, "includes are unsupported");
    fs::write(f.common.join("config"), b"[unterminated").unwrap();
    f.rejected(&f.workspace, "parse config without following includes");
}

#[test]
fn disabled_worktree_config_is_not_loaded() {
    let f = Fixture::new();
    fs::write(
        f.common.join("config.worktree"),
        include_str!("repository-fixtures/include.config"),
    )
    .unwrap();
    preflight(&f.workspace, &f.common).unwrap();
    f.assert_absent();
}

#[test]
fn every_registered_private_database_and_sidecar_is_inventoried_without_mutation() {
    for name in [
        "git-meta.sqlite",
        "git-meta.sqlite-wal",
        "git-meta.sqlite-shm",
    ] {
        let f = Fixture::new();
        let _linked = f.linked();
        let admin = fs::read_dir(f.common.join("worktrees"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap()
            .path();
        let legacy = admin.join(name);
        fs::write(&legacy, b"preserve legacy bytes").unwrap();
        f.rejected(&f.workspace, "legacy worktree-local metadata stores found");
        assert_eq!(fs::read(legacy).unwrap(), b"preserve legacy bytes");
    }
}

#[cfg(unix)]
#[test]
fn stale_worktree_and_dangling_legacy_sidecar_are_not_hidden() {
    use std::os::unix::fs::symlink;
    let f = Fixture::new();
    let linked = f.linked();
    let admin = fs::read_dir(f.common.join("worktrees"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    fs::remove_dir_all(&linked).unwrap();
    let legacy = admin.join("git-meta.sqlite-shm");
    symlink("missing-legacy-target", &legacy).unwrap();
    f.rejected(&f.workspace, "legacy worktree-local metadata stores found");
    assert_eq!(
        fs::read_link(legacy).unwrap(),
        PathBuf::from("missing-legacy-target")
    );
}

#[cfg(unix)]
#[test]
fn alternates_entries_and_object_symlink_escapes_are_refused() {
    use std::os::unix::fs::symlink;
    for dangling in [false, true] {
        let f = Fixture::new();
        let alternate = f.common.join("objects/info/alternates");
        if dangling {
            symlink("missing-canary", &alternate).unwrap();
        } else {
            fs::write(&alternate, "external").unwrap();
        }
        f.rejected(&f.workspace, "alternates is unsupported");
    }
    for location in ["objects/ab", "objects/pack", "objects/info"] {
        let f = Fixture::new();
        let target = f.root.path().join("outside");
        fs::create_dir(&target).unwrap();
        let link = f.common.join(location);
        if link.exists() {
            fs::remove_dir(&link).unwrap();
        }
        symlink(&target, link).unwrap();
        f.rejected(&f.workspace, "unsupported");
    }
    let f = Fixture::new();
    fs::create_dir(f.common.join("objects/ab")).unwrap();
    symlink(
        f.root.path().join("outside-canary"),
        f.common.join(format!("objects/ab/{}", "0".repeat(38))),
    )
    .unwrap();
    f.rejected(&f.workspace, "object symlink");
}

#[cfg(unix)]
#[test]
fn pack_file_symlinks_are_rejected_even_when_the_target_is_internal() {
    use std::os::unix::fs::symlink;
    let f = Fixture::new();
    let pack = f.common.join("objects/pack");
    fs::write(pack.join("real.pack"), b"not opened").unwrap();
    symlink(
        "real.pack",
        pack.join("pack-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pack"),
    )
    .unwrap();
    f.rejected(&f.workspace, "object symlink");
}

#[test]
fn normal_git_generated_pack_and_multi_index_are_supported() {
    let f = Fixture::new();
    let _linked = f.linked();
    git(&f.workspace, &["repack", "-ad"]);
    git(&f.workspace, &["multi-pack-index", "write"]);
    preflight(&f.workspace, &f.common).unwrap();
    f.assert_absent();
}

#[test]
fn nonstandard_common_with_nested_git_entry_is_ambiguous_even_if_invalid() {
    let root = tempfile::tempdir().unwrap();
    let common = root.path().join("metadata");
    git(root.path(), &["init", "--bare", common.to_str().unwrap()]);
    fs::write(common.join(".git"), "not even a repository").unwrap();
    assert!(preflight(&common, &common)
        .unwrap_err()
        .to_string()
        .contains("nested .git"));
    assert!(!common.join("git-meta.sqlite").exists());
}

// Minimal MIDX fixture writer only for tests: production uses gix-pack's parser.
fn midx(name: &str) -> Vec<u8> {
    let mut names = name.as_bytes().to_vec();
    names.push(0);
    while names.len() % 4 != 0 {
        names.push(0);
    }
    let start = 12 + 5 * 12;
    let offsets = [
        start,
        start + names.len(),
        start + names.len() + 1024,
        start + names.len() + 1024 + 20,
        start + names.len() + 1024 + 20 + 8,
    ];
    let mut bytes = b"MIDX\x01\x01\x04\x00\x00\x00\x00\x01".to_vec();
    for (id, offset) in [b"PNAM", b"OIDF", b"OIDL", b"OOFF", b"\0\0\0\0"]
        .iter()
        .zip(offsets)
    {
        bytes.extend_from_slice(*id);
        bytes.extend_from_slice(&(offset as u64).to_be_bytes());
    }
    bytes.extend(names);
    for _ in 0..256 {
        bytes.extend(1u32.to_be_bytes());
    }
    bytes.extend([0; 20]); // one object ID
    bytes.extend([0; 8]); // pack ordinal and offset
    bytes.extend([0; 20]); // unchecked checksum (the parser does not verify it)
    bytes
}

#[test]
fn multi_pack_index_names_cannot_escape_pack_directory() {
    for name in [
        "../outside.idx",
        "/outside.idx",
        "subdir/pack-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.idx",
        "./pack-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.idx",
    ] {
        let f = Fixture::new();
        fs::write(f.common.join("objects/pack/multi-pack-index"), midx(name)).unwrap();
        f.rejected(&f.workspace, "multi-pack-index pack name");
    }
    let f = Fixture::new();
    fs::write(
        f.common.join("objects/pack/multi-pack-index"),
        midx("pack-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.idx"),
    )
    .unwrap();
    preflight(&f.workspace, &f.common).unwrap();
    f.assert_absent();
}
