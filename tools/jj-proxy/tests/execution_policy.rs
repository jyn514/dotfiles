use std::process::{Command, Output};

fn run_fixture(mode: &str) -> Output {
    Command::new(env!("CARGO_BIN_EXE_execution-policy-fixture"))
        .arg(mode)
        .output()
        .expect("could not run execution-policy fixture")
}

fn assert_success(output: Output) {
    assert!(
        output.status.success(),
        "fixture failed with {}:\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

#[test]
fn trusted_jj_policy_can_replace_working_tree_files() {
    assert_success(run_fixture("worktree"));
}

#[test]
fn trusted_jj_policy_cannot_write_outside_repository() {
    assert_success(run_fixture("outside"));
}

#[test]
fn trusted_git_can_read_randomness_without_write_access() {
    assert_success(run_fixture("random"));
}

#[test]
fn inspection_policy_cannot_write_repository_or_metadata() {
    assert_success(run_fixture("inspect"));
}

/// Exercise the multi-root rules in a separate process: Landlock is irreversible.
#[test]
fn authority_grants_both_roots_but_inspection_removes_all_writes() {
    use std::{env, fs, io::ErrorKind, path::Path};
    use jj_proxy::{execution_policy::{self, PolicyPaths}, workspaces::Workspace};
    if let Ok(mode) = env::var("JJ_PROXY_MULTI_POLICY_CHILD") {
        let root = env::temp_dir().join(format!("jj-multi-policy-{}", std::process::id()));
        let source = root.join("src");
        let trusted = root.join("trusted");
        let trusted_bin = trusted.join("bin");
        let config = root.join("config");
        let socket = root.join("socket");
        for path in [&source, &trusted_bin, &config, &socket] { fs::create_dir_all(path).unwrap(); }
        let mut workspaces = Vec::new();
        for name in ["active", "relocated"] {
            let repo = source.join(name);
            fs::create_dir_all(repo.join(".git")).unwrap();
            fs::create_dir_all(repo.join(".jj/repo")).unwrap();
            let lock = root.join(format!("{name}.lock"));
            fs::write(&lock, "").unwrap();
            workspaces.push(Workspace {
                root: repo.to_str().unwrap().into(), git_dir: repo.join(".git").to_str().unwrap().into(),
                common_dir: repo.join(".git").to_str().unwrap().into(),
                jj_repo: repo.join(".jj/repo").to_str().unwrap().into(), lock: lock.to_str().unwrap().into(),
            });
        }
        fs::create_dir(source.join("unlisted")).unwrap();
        execution_policy::install_workspaces_with_paths(&workspaces, &PolicyPaths {
            source: &source, trusted: &trusted, trusted_bin: &trusted_bin, config: &config, socket: &socket,
        }, mode == "mutate").unwrap();
        for workspace in &workspaces {
            for path in [Path::new(&workspace.root).join("ordinary"), Path::new(&workspace.git_dir).join("metadata"),
                Path::new(&workspace.jj_repo).join("metadata")] {
                let result = fs::write(path, "test");
                if mode == "mutate" { result.unwrap(); }
                else { assert_eq!(ErrorKind::PermissionDenied, result.unwrap_err().kind()); }
            }
            let result = fs::OpenOptions::new().write(true).open(&workspace.lock);
            if mode == "mutate" { result.unwrap(); }
            else { assert_eq!(ErrorKind::PermissionDenied, result.unwrap_err().kind()); }
        }
        assert_eq!(ErrorKind::PermissionDenied, fs::write(source.join("unlisted/denied"), "no").unwrap_err().kind());
        return;
    }
    for mode in ["mutate", "inspect"] {
        let output = Command::new(env::current_exe().unwrap())
            .args(["--exact", "authority_grants_both_roots_but_inspection_removes_all_writes", "--nocapture"])
            .env("JJ_PROXY_MULTI_POLICY_CHILD", mode).output().unwrap();
        assert_success(output);
    }
}
