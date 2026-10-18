use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

const TRUSTED_CONFIG: &str = include_str!("../jj.toml");

fn real_jj() -> Option<PathBuf> {
    std::env::var_os("JJ_PROXY_TEST_JJ")
        .or_else(|| std::env::var_os("JJ_REAL"))
        .map(PathBuf::from)
        .or_else(|| {
            ["/trusted/bin/jj", "/opt/agent-tools/bin/jj"]
                .into_iter()
                .map(PathBuf::from)
                .find(|path| {
                    fs::symlink_metadata(path)
                        .is_ok_and(|metadata| metadata.file_type().is_file())
                })
        })
}

fn run(jj: &Path, home: &Path, args: &[&str]) -> Output {
    Command::new(jj)
        .args(args)
        .env_clear()
        .env("HOME", home)
        .env("XDG_CONFIG_HOME", home)
        .current_dir(home)
        .output()
        .expect("could not run jj")
}

fn success(output: Output) -> String {
    assert!(
        output.status.success(),
        "jj failed with {}:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stderr),
    );
    String::from_utf8(output.stdout).expect("jj output was not UTF-8")
}

#[test]
fn fetch_uses_configured_remotes_and_jj_defaults() {
    let Some(jj) = real_jj() else {
        eprintln!("skipping fetch test: set JJ_PROXY_TEST_JJ to a real jj binary");
        return;
    };
    let root = std::env::temp_dir().join(format!("jj-proxy-fetch-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let source = root.join("source");
    let repo = root.join("repo");
    let trusted_config = root.join("trusted-jj.toml");
    fs::write(&trusted_config, TRUSTED_CONFIG).unwrap();
    success(run(&jj, &root, &["git", "init", source.to_str().unwrap()]));
    success(run(&jj, &root, &["git", "init", repo.to_str().unwrap()]));
    success(run(&jj, &root, &[
        "--repository", source.to_str().unwrap(), "--config-file", trusted_config.to_str().unwrap(),
        "commit", "-m", "remote commit",
    ]));
    success(run(&jj, &root, &[
        "--repository", source.to_str().unwrap(), "bookmark", "create", "main", "-r", "@-",
    ]));
    success(run(&jj, &root, &["--repository", source.to_str().unwrap(), "git", "export"]));
    for name in ["upstream", "contributor"] {
        success(run(&jj, &root, &[
            "--repository", repo.to_str().unwrap(), "git", "remote", "add", name, source.to_str().unwrap(),
        ]));
    }
    let config_path = success(run(&jj, &root, &[
        "--repository", repo.to_str().unwrap(), "config", "path", "--repo",
    ]));
    fs::write(config_path.trim(), "[git]\nfetch = [\"contributor\"]\n").unwrap();
    let policy = jj_proxy::policy::Policy::load(Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/policy.toml"))).unwrap();
    let fetch = |args: &[&str]| {
        let argv = args.iter().map(|arg| (*arg).to_owned()).collect::<Vec<_>>();
        let decision = policy.validate(&argv).unwrap();
        Command::new(&jj)
            .args(["--repository", repo.to_str().unwrap(), "--config-file", trusted_config.to_str().unwrap()])
            .args(&decision.argv)
            .env_clear().env("HOME", &root).env("XDG_CONFIG_HOME", &root)
            .current_dir(&root).output().unwrap()
    };
    // No origin exists: the omitted selection must reach JJ's configured default.
    success(fetch(&["git", "fetch"]));
    let bookmarks = || success(run(&jj, &root, &[
        "--repository", repo.to_str().unwrap(), "bookmark", "list", "--all-remotes",
    ]));
    assert!(bookmarks().contains("@contributor"));
    assert!(!bookmarks().contains("@upstream"));
    success(fetch(&["git", "fetch", "--remote", "upstream"]));
    assert!(bookmarks().contains("@upstream"));
    success(fetch(&["git", "fetch", "--remote=contributor"]));
    success(fetch(&["git", "fetch", "--remote", "upstream", "--remote", "contributor"]));
    success(fetch(&["git", "fetch", "--all-remotes"]));
    for args in [
        vec!["git", "fetch", "--remote", "missing"],
        vec!["git", "fetch", "--remote"],
        vec!["git", "fetch", "--remote", source.to_str().unwrap()],
    ] {
        assert!(!fetch(&args).status.success(), "JJ accepted invalid fetch: {args:?}");
    }
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn command_line_trusted_config_defeats_hostile_repository_config() {
    let Some(jj) = real_jj() else {
        eprintln!("skipping effective config test: set JJ_PROXY_TEST_JJ to a real jj binary");
        return;
    };
    let root = std::env::temp_dir().join(format!(
        "jj-proxy-effective-config-{}-{}",
        std::process::id(),
        std::thread::current().name().unwrap_or("test"),
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let repo = root.join("repo");
    let trusted_config = root.join("trusted-jj.toml");
    fs::write(&trusted_config, TRUSTED_CONFIG).unwrap();

    success(run(&jj, &root, &["git", "init", repo.to_str().unwrap()]));
    let config_path = success(run(
        &jj,
        &root,
        &[
            "--repository", repo.to_str().unwrap(), "--ignore-working-copy",
            "config", "path", "--repo",
        ],
    ));
    fs::write(
        config_path.trim(),
        r#"[ui]
editor = ["/bin/sh", "-c", "touch /tmp/hostile-editor"]
diff-editor = ["/bin/sh", "-c", "touch /tmp/hostile-diff"]
merge-editor = ["/bin/sh", "-c", "touch /tmp/hostile-merge"]
diff-formatter = ["/bin/sh", "-c", "touch /tmp/hostile-formatter"]
[signing]
behavior = "own"
"#,
    )
    .unwrap();

    for (key, expected) in [
        ("ui.editor", r#"["/trusted/bin/jj-proxy", "reject-editor"]"#),
        ("ui.diff-editor", ":builtin"),
        ("ui.merge-editor", ":builtin"),
        ("ui.diff-formatter", ":git"),
        ("signing.behavior", "drop"),
    ] {
        let value = success(run(
            &jj,
            &root,
            &[
                "--config-file", trusted_config.to_str().unwrap(), "--repository",
                repo.to_str().unwrap(), "--ignore-working-copy", "config", "get", key,
            ],
        ));
        assert_eq!(expected, value.trim(), "hostile repository config overrode {key}");
    }

    fs::remove_dir_all(root).unwrap();
}

#[test]
fn command_line_agent_identity_stamps_the_commit_then_resets_to_the_human() {
    let Some(jj) = real_jj() else {
        eprintln!("skipping effective config test: set JJ_PROXY_TEST_JJ to a real jj binary");
        return;
    };
    let root = std::env::temp_dir().join(format!(
        "jj-proxy-identity-{}-{}",
        std::process::id(),
        std::thread::current().name().unwrap_or("test"),
    ));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let repo = root.join("repo");
    let trusted_config = root.join("trusted-jj.toml");
    fs::write(&trusted_config, TRUSTED_CONFIG).unwrap();

    success(run(&jj, &root, &["git", "init", repo.to_str().unwrap()]));
    fs::write(repo.join("file"), "change\n").unwrap();
    let agent_config = [
        "--config-file", trusted_config.to_str().unwrap(),
        "--repository", repo.to_str().unwrap(),
        "--config", "user.name=Pi gpt-test",
        "--config", "user.email=pi@example.test",
    ];
    success(run(
        &jj,
        &root,
        &[
            &agent_config[..],
            &["metaedit", "--update-author", "-r", "@", "--quiet"],
        ].concat(),
    ));
    success(run(
        &jj,
        &root,
        &[&agent_config[..], &["commit", "-m", "test"]].concat(),
    ));

    let committed_identity = success(run(
        &jj,
        &root,
        &[
            "--config-file", trusted_config.to_str().unwrap(),
            "--repository", repo.to_str().unwrap(),
            "log", "-r", "@-", "--no-graph", "-T",
            r#"author.name() ++ "|" ++ author.email() ++ "|" ++ committer.name() ++ "|" ++ committer.email()"#,
        ],
    ));
    assert_eq!(
        "Pi gpt-test|pi@example.test|Pi gpt-test|pi@example.test",
        committed_identity.trim(),
    );

    success(run(
        &jj,
        &root,
        &[
            "--config-file", trusted_config.to_str().unwrap(),
            "--repository", repo.to_str().unwrap(),
            "metaedit", "--update-author", "-r", "@", "--quiet",
        ],
    ));
    let working_copy_author = success(run(
        &jj,
        &root,
        &[
            "--config-file", trusted_config.to_str().unwrap(),
            "--repository", repo.to_str().unwrap(),
            "log", "-r", "@", "--no-graph", "-T",
            r#"author.name() ++ "|" ++ author.email()"#,
        ],
    ));
    assert_eq!("jyn|github@jyn.dev", working_copy_author.trim());

    fs::remove_dir_all(root).unwrap();
}
