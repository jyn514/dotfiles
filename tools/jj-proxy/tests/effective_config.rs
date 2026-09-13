use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

const TRUSTED_CONFIG: &str = include_str!("../jj.toml");

fn real_jj() -> Option<PathBuf> {
    std::env::var_os("JJ_PROXY_TEST_JJ")
        .map(PathBuf::from)
        .or_else(|| {
            ["/trusted/bin/jj", "/opt/agent-tools/bin/jj"]
                .into_iter()
                .map(PathBuf::from)
                .find(|path| path.is_file())
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
