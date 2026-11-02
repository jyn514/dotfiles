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

/// Selection pins the linked directory before guest-controlled paths change.
/// Run each restriction in its own process because Landlock cannot be removed.
#[test]
fn linked_scope_survives_pointer_metadata_and_root_swaps() {
    use std::{env, fs, io::ErrorKind, os::{fd::OwnedFd, unix::fs::symlink}, path::Path};
    use jj_proxy::{execution_policy::{self, PolicyPaths}, workspaces::{self, Workspace}};

    if let Ok(mode) = env::var("JJ_PROXY_LINKED_POLICY_CHILD") {
        let root = std::path::PathBuf::from(env::var_os("JJ_PROXY_LINKED_POLICY_ROOT").unwrap());
        let source = root.join("src");
        let trusted = root.join("trusted");
        let trusted_bin = trusted.join("bin");
        let config = root.join("config");
        let socket = root.join("socket");
        for path in [&source, &trusted_bin, &config, &socket] { fs::create_dir_all(path).unwrap(); }
        let paths = PolicyPaths {
            source: &source, trusted: &trusted, trusted_bin: &trusted_bin, config: &config, socket: &socket,
        };
        let mut workspaces = Vec::new();
        for name in ["selected", "independent"] {
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
        let selected = &workspaces[0];
        let independent = &workspaces[1];
        let linked = Path::new(&selected.root).join("linked");
        fs::create_dir_all(linked.join(".jj/working_copy")).unwrap();
        fs::write(linked.join(".jj/repo"), &selected.jj_repo).unwrap();
        let pinned: OwnedFd = fs::File::open(&linked).unwrap().into();
        let scoped = Workspace { root: linked.to_str().unwrap().into(), ..selected.clone() };
        let mounts = workspaces::mount_points().unwrap();
        execution_policy::install_workspaces_with_paths(&workspaces, &paths, true).unwrap();
        // Scope validation runs after the server restriction. Ancestor walks
        // must stop at its read boundary rather than fail on unrelated mounts.
        workspaces::validate_linked_scope(&pinned, selected, &workspaces, &mounts).unwrap();

        // B is writable under the server policy; only the child restriction
        // must prevent a changed pointer from using it without B's lock.
        let other_store_file = Path::new(&independent.jj_repo).join("metadata");
        fs::write(&other_store_file, "server-owned").unwrap();
        let original = if mode == "root" {
            let original = Path::new(&selected.root).join("pinned-original");
            fs::rename(&linked, &original).unwrap();
            symlink(&independent.root, &linked).unwrap();
            original
        } else {
            if mode == "metadata" {
                fs::remove_dir_all(linked.join(".jj")).unwrap();
                symlink(Path::new(&independent.root).join(".jj"), linked.join(".jj")).unwrap();
            } else {
                fs::write(linked.join(".jj/repo"), &independent.jj_repo).unwrap();
            }
            linked.clone()
        };
        execution_policy::install_linked_workspace_with_paths(&scoped, &pinned, &paths).unwrap();
        if mode == "inspect" {
            execution_policy::install_workspaces_with_paths(&workspaces, &paths, false).unwrap();
        }
        for path in [original.join("ordinary"), Path::new(&selected.git_dir).join("metadata"),
            Path::new(&selected.jj_repo).join("metadata")] {
            let result = fs::write(&path, "selected");
            if mode == "inspect" {
                assert_eq!(ErrorKind::PermissionDenied, result.unwrap_err().kind(), "{}", path.display());
            } else { result.unwrap(); }
        }
        for path in [&other_store_file, &Path::new(&independent.git_dir).join("metadata"),
            &Path::new(&independent.root).join("ordinary"), &Path::new(&selected.root).join("outside-linked")] {
            assert_eq!(ErrorKind::PermissionDenied, fs::write(path, "wrong-store").unwrap_err().kind(), "{}", path.display());
        }
        let redirected = if mode == "pointer" || mode == "inspect" {
            let target = fs::read_to_string(linked.join(".jj/repo")).unwrap();
            Path::new(&target).join("metadata")
        } else { linked.join(".jj/repo/metadata") };
        assert_eq!(ErrorKind::PermissionDenied, fs::write(&redirected, "redirected").unwrap_err().kind());
        assert_eq!("server-owned", fs::read_to_string(other_store_file).unwrap());
        if mode == "pointer" {
            // A later pointer change cannot add rights after restriction either.
            fs::write(linked.join(".jj/repo"), &selected.jj_repo).unwrap();
            fs::write(linked.join(".jj/repo"), &independent.jj_repo).unwrap();
            assert_eq!(ErrorKind::PermissionDenied, fs::write(redirected, "late-redirect").unwrap_err().kind());
        }
        return;
    }
    for mode in ["pointer", "metadata", "root", "inspect"] {
        let root = env::temp_dir().join(format!("jj-linked-policy-{}-{mode}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let output = Command::new(env::current_exe().unwrap())
            .args(["--exact", "linked_scope_survives_pointer_metadata_and_root_swaps", "--nocapture"])
            .env("JJ_PROXY_LINKED_POLICY_CHILD", mode)
            .env("JJ_PROXY_LINKED_POLICY_ROOT", &root).output().unwrap();
        assert_success(output);
        fs::remove_dir_all(root).unwrap();
    }
}
