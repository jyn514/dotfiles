//! Pure repository metadata inspection: no effective configuration or storage.
//! Each subprocess receives its own HOME/XDG/Git environment and owned fixtures.
#![cfg(unix)]
use serde_json::{json, Value};
use std::{
    fs,
    io::Read,
    os::unix::{ffi::OsStringExt, fs::PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
    thread,
    time::{Duration, Instant},
};
use tempfile::TempDir;
use tic_proxy::{broker::NATIVE_REVISION, inspect::MAX_CONTEXT_OUTPUT};

struct Fixture {
    root: TempDir,
    main: PathBuf,
    linked: PathBuf,
    home: PathBuf,
    xdg: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let root = tempfile::Builder::new()
            .prefix("tic-inspect-")
            .tempdir_in(std::env::temp_dir().canonicalize().unwrap())
            .unwrap();
        let main = root.path().join("main");
        let linked = root.path().join("linked");
        let home = root.path().join("home");
        let xdg = root.path().join("xdg");
        for path in [&main, &home, &xdg] {
            fs::create_dir(path).unwrap();
        }
        let this = Self {
            root,
            main,
            linked,
            home,
            xdg,
        };
        this.git(&["init", "-qb", "main"]);
        this.git(&[
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "initial",
        ]);
        this.git(&[
            "worktree",
            "add",
            "-qb",
            "linked",
            this.linked.to_str().unwrap(),
        ]);
        this
    }
    fn git(&self, args: &[&str]) {
        let output = Command::new("git")
            .current_dir(&self.main)
            .env_clear()
            .env("PATH", std::env::var_os("PATH").unwrap())
            .env("HOME", &self.home)
            .env("GIT_CONFIG_NOSYSTEM", "1")
            .env("GIT_CONFIG_GLOBAL", "/dev/null")
            .args(args)
            .output()
            .unwrap();
        assert!(output.status.success(), "git {args:?}: {output:?}");
    }
    fn inspect(&self, workspace: &Path) -> Command {
        self.inspect_expected(workspace, &self.main.join(".git"))
    }
    fn inspect_expected(&self, workspace: &Path, common: &Path) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_tic-broker"));
        command
            .env_clear()
            .env("HOME", &self.home)
            .env("XDG_CONFIG_HOME", &self.xdg)
            .arg("inspect-context")
            .arg("--workspace")
            .arg(workspace)
            .arg("--common-dir")
            .arg(common);
        command
    }
    fn no_store(&self) {
        for dir in [
            self.main.join(".git"),
            self.main.join(".git/worktrees/linked"),
        ] {
            for name in [
                "git-meta.sqlite",
                "git-meta.sqlite-wal",
                "git-meta.sqlite-shm",
            ] {
                assert!(
                    !dir.join(name).exists(),
                    "inspection created store/sidecar {:?}",
                    dir.join(name)
                );
            }
        }
    }
}
fn run(command: &mut Command) -> Output {
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut stdout = child.stdout.take().unwrap();
    let mut stderr = child.stderr.take().unwrap();
    let out = thread::spawn(move || {
        let mut bytes = Vec::new();
        stdout.read_to_end(&mut bytes).unwrap();
        bytes
    });
    let err = thread::spawn(move || {
        let mut bytes = Vec::new();
        stderr.read_to_end(&mut bytes).unwrap();
        bytes
    });
    let deadline = Instant::now() + Duration::from_secs(3);
    let mut timed_out = false;
    let status = loop {
        if let Some(status) = child.try_wait().unwrap() {
            break status;
        }
        if Instant::now() >= deadline {
            timed_out = true;
            child.kill().unwrap();
            break child.wait().unwrap();
        }
        thread::sleep(Duration::from_millis(10));
    };
    let output = Output {
        status,
        stdout: out.join().unwrap(),
        stderr: err.join().unwrap(),
    };
    assert!(
        !timed_out,
        "inspector blocked on a forbidden configuration/ref/store read: {output:?}"
    );
    output
}
fn capture(command: &mut Command) -> Value {
    let output = run(command);
    assert!(output.status.success(), "{output:?}");
    assert!(output.stderr.is_empty(), "{output:?}");
    assert!(output.stdout.len() <= MAX_CONTEXT_OUTPUT);
    assert_eq!(output.stdout.last(), Some(&b'\n'));
    assert_eq!(
        output.stdout.iter().filter(|&&byte| byte == b'\n').count(),
        1
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn reject(command: &mut Command) -> Output {
    let output = run(command);
    assert!(!output.status.success(), "{output:?}");
    assert!(output.stdout.is_empty(), "partial metadata: {output:?}");
    assert!(!output.stderr.is_empty());
    assert!(output.stderr.len() < 512);
    output
}
fn expected(workspace: &Path, common: &Path, invocation: &Path) -> Value {
    json!({"version":1,"policy_version":1,"native_revision":NATIVE_REVISION,
        "workspace":workspace,"common_dir":common,"invocation_git_dir":invocation})
}
fn fifo(path: &Path) {
    nix::unistd::mkfifo(
        path,
        nix::sys::stat::Mode::S_IRUSR | nix::sys::stat::Mode::S_IWUSR,
    )
    .unwrap();
}

#[test]
fn exact_six_field_metadata_identifies_main_and_linked_invocations() {
    let fixture = Fixture::new();
    let common = fixture.main.join(".git").canonicalize().unwrap();
    assert_eq!(
        capture(&mut fixture.inspect(&fixture.main)),
        expected(&fixture.main, &common, &common)
    );
    let invocation = common.join("worktrees/linked").canonicalize().unwrap();
    assert_eq!(
        capture(&mut fixture.inspect(&fixture.linked)),
        expected(&fixture.linked, &common, &invocation)
    );
    fixture.no_store();
}

#[test]
fn bare_and_separate_gitdir_metadata_use_the_actual_explicit_invocation() {
    let fixture = Fixture::new();
    let bare = fixture.root.path().join("bare.git");
    fixture.git(&["init", "--bare", bare.to_str().unwrap()]);
    assert_eq!(
        capture(&mut fixture.inspect_expected(&bare, &bare)),
        expected(&bare, &bare, &bare)
    );
    let work = fixture.root.path().join("separate-work");
    let separate = fixture.root.path().join("separate.git");
    fixture.git(&[
        "init",
        "--separate-git-dir",
        separate.to_str().unwrap(),
        work.to_str().unwrap(),
    ]);
    assert_eq!(
        capture(&mut fixture.inspect_expected(&work, &separate)),
        expected(&work, &separate, &separate)
    );
    assert!(!bare.join("git-meta.sqlite").exists());
    assert!(!separate.join("git-meta.sqlite").exists());
    fixture.no_store();
}

#[test]
fn explicit_roots_are_authority_not_search_hints_or_expected_common_selection() {
    let fixture = Fixture::new();
    let subdir = fixture.main.join("subdir");
    fs::create_dir(&subdir).unwrap();
    reject(&mut fixture.inspect(&subdir));
    reject(&mut fixture.inspect(&fixture.home));
    reject(
        &mut fixture.inspect_expected(&fixture.main, &fixture.main.join(".git/worktrees/linked")),
    );
    reject(&mut fixture.inspect_expected(&fixture.main, &fixture.home));
    let mut relative = fixture.inspect_expected(Path::new("main"), Path::new("main/.git"));
    relative.current_dir(fixture.root.path());
    reject(&mut relative);
    fixture.no_store();
}

#[test]
fn configuration_sources_are_never_loaded_and_redirect_environment_cannot_select_paths() {
    let fixture = Fixture::new();
    fifo(&fixture.home.join(".gitconfig"));
    fs::create_dir_all(fixture.xdg.join("git")).unwrap();
    fifo(&fixture.xdg.join("git/config"));
    let source = fixture.root.path().join("config-source-canary");
    fifo(&source);
    let common = fixture.main.join(".git");
    let metadata = expected(&fixture.main, &common, &common);
    let mut command = fixture.inspect(&fixture.main);
    command
        .env("GIT_CONFIG_SYSTEM", &source)
        .env("GIT_CONFIG_GLOBAL", &source)
        .env("GIT_CONFIG_NOSYSTEM", "not-a-boolean")
        .env("GIT_CONFIG", &source)
        .env("GIT_CONFIG_PARAMETERS", "'unterminated")
        .env("GIT_CONFIG_COUNT", "not-an-integer")
        .env("GIT_CONFIG_KEY_0", "include.path")
        .env("GIT_CONFIG_VALUE_0", &source);
    assert_eq!(capture(&mut command), metadata);
    // None of these variables is consumed by the explicit low-level locator.
    // Presence is not a reason for a metadata-only operation to deny the launch.
    for key in [
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_INDEX_FILE",
        "GIT_SHALLOW_FILE",
        "GIT_QUARANTINE_PATH",
        "GIT_CEILING_DIRECTORIES",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_REPLACE_REF_BASE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_PREFIX",
        "GIT_INTERNAL_SUPER_PREFIX",
        "GIT_GRAFT_FILE",
    ] {
        let mut command = fixture.inspect(&fixture.main);
        command.env(key, &source);
        assert_eq!(
            capture(&mut command),
            metadata,
            "environment selector {key}"
        );
    }
    fixture.no_store();
}

#[test]
fn preflight_rejection_precedes_any_host_config_or_store_access() {
    let fixture = Fixture::new();
    fifo(&fixture.home.join(".gitconfig"));
    let included = fixture.root.path().join("local-include-canary");
    fifo(&included);
    fixture.git(&["config", "include.path", included.to_str().unwrap()]);
    let output = reject(&mut fixture.inspect(&fixture.main));
    assert!(!String::from_utf8_lossy(&output.stderr).contains("local-include-canary"));
    fixture.no_store();
}

#[test]
fn metadata_does_not_parse_packed_refs_follow_head_or_apply_effective_config() {
    let fixture = Fixture::new();
    fixture.git(&["config", "core.worktree", fixture.home.to_str().unwrap()]);
    fixture.git(&["config", "core.useReplaceRefs", "false"]);
    fs::write(
        fixture.home.join(".gitconfig"),
        b"malformed host configuration\0\xff",
    )
    .unwrap();
    fs::write(
        fixture.main.join(".git/packed-refs"),
        b"not packed refs\0\xff",
    )
    .unwrap();
    let tip = fixture.main.join(".git/refs/heads/main");
    fs::remove_file(&tip).unwrap();
    fifo(&tip);
    let common = fixture.main.join(".git");
    assert_eq!(
        capture(&mut fixture.inspect(&fixture.main)),
        expected(&fixture.main, &common, &common)
    );
    fixture.no_store();
}

#[test]
fn existing_invalid_sqlite_and_sidecars_are_only_inventoried_without_mutation() {
    let fixture = Fixture::new();
    let mut paths = Vec::new();
    for name in [
        "git-meta.sqlite",
        "git-meta.sqlite-wal",
        "git-meta.sqlite-shm",
    ] {
        let path = fixture.main.join(".git").join(name);
        fs::write(&path, b"invalid SQLite contents\0\xff").unwrap();
        paths.push((
            path.clone(),
            fs::read(&path).unwrap(),
            fs::metadata(&path).unwrap().modified().unwrap(),
        ));
    }
    capture(&mut fixture.inspect(&fixture.main));
    capture(&mut fixture.inspect(&fixture.linked));
    // Existing private stores are an established preflight refusal, not an
    // invitation for inspection to open, migrate or repair their contents.
    let legacy = fixture.main.join(".git/worktrees/linked/git-meta.sqlite");
    fs::write(&legacy, b"private SQLite canary\0\xff").unwrap();
    reject(&mut fixture.inspect(&fixture.main));
    reject(&mut fixture.inspect(&fixture.linked));
    assert_eq!(fs::read(legacy).unwrap(), b"private SQLite canary\0\xff");
    for (path, contents, modified) in paths {
        assert_eq!(fs::read(&path).unwrap(), contents);
        assert_eq!(fs::metadata(path).unwrap().modified().unwrap(), modified);
    }
}

#[test]
fn metadata_inspection_never_invokes_git_shell_or_editor_helpers() {
    let fixture = Fixture::new();
    let bin = fixture.root.path().join("bin");
    fs::create_dir(&bin).unwrap();
    let marker = fixture.root.path().join("helper-ran");
    for name in ["git", "sh", "ssh", "editor"] {
        let path = bin.join(name);
        fs::write(
            &path,
            format!(
                "#!/bin/sh\nprintf helper > '{}'\nexit 91\n",
                marker.display()
            ),
        )
        .unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
    }
    let mut command = fixture.inspect(&fixture.main);
    command
        .env("PATH", &bin)
        .env("GIT_EDITOR", bin.join("editor"))
        .env("EDITOR", bin.join("editor"));
    capture(&mut command);
    assert!(!marker.exists());
    fixture.no_store();
}

#[test]
fn unrepresentable_repository_paths_and_invalid_cli_fail_without_partial_json() {
    let fixture = Fixture::new();
    let work = fixture
        .root
        .path()
        .join(std::ffi::OsString::from_vec(b"non-utf8-\xff".to_vec()));
    fixture.git(&[
        "init",
        "-qb",
        "other",
        fixture.root.path().join("rename-me").to_str().unwrap(),
    ]);
    fs::rename(fixture.root.path().join("rename-me"), &work).unwrap();
    let output = reject(&mut fixture.inspect_expected(&work, &work.join(".git")));
    assert!(String::from_utf8_lossy(&output.stderr).contains("unrepresentable"));
    let mut command = fixture.inspect(&fixture.main);
    command.arg("--unknown-secret-canary");
    let output = reject(&mut command);
    assert!(!String::from_utf8_lossy(&output.stderr).contains("secret-canary"));
    assert!(!work.join(".git/git-meta.sqlite").exists());
    fixture.no_store();
}
