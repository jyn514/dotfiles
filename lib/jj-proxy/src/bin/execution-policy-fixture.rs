use jj_proxy::execution_policy;
use std::env;
use std::fs;
use std::io::ErrorKind;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = env::temp_dir().join(format!("jj-proxy-policy-{}", std::process::id()));
    let repo = root.join("repo");
    let git = repo.join(".git");
    let jj_repo = repo.join(".jj/repo");
    fs::create_dir_all(&git)?;
    fs::create_dir_all(&jj_repo)?;
    fs::create_dir_all("/trusted/bin")?;
    fs::create_dir_all("/tmp/jj-config")?;
    fs::create_dir_all("/run/sandbox-proxy")?;

    let working_file = repo.join("working-file");
    fs::write(&working_file, "old")?;
    fs::write(git.join("metadata"), "old")?;
    env::set_var("JJ_PROXY_GIT_DIR", &git);
    env::set_var("JJ_PROXY_COMMON_DIR", &git);
    env::set_var("JJ_PROXY_JJ_REPO", &jj_repo);
    execution_policy::install(repo.to_str().ok_or("non-UTF-8 repository path")?)?;

    match env::args().nth(1).as_deref() {
        Some("worktree") => {
            fs::remove_file(&working_file)?;
            fs::write(&working_file, "new")?;
            fs::write(git.join("metadata"), "new")?;
        }
        Some("outside") => match fs::write(root.join("outside-repository"), "no") {
            Err(error) if error.kind() == ErrorKind::PermissionDenied => {}
            Err(error) => return Err(error.into()),
            Ok(()) => return Err("policy allowed a write outside the repository".into()),
        },
        _ => return Err("expected worktree or outside mode".into()),
    }
    Ok(())
}
