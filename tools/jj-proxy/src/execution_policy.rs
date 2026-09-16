use color_eyre::eyre::Result;
use std::path::Path;

#[cfg(target_os = "linux")]
use color_eyre::eyre::{bail, WrapErr};
#[cfg(target_os = "linux")]
use std::env;

#[cfg(target_os = "linux")]
use landlock::{
    make_bitflags, AccessFs, CompatLevel, Compatible, PathBeneath, PathFd, Ruleset, RulesetAttr,
    RulesetCreatedAttr, RulesetStatus,
};

pub struct PolicyPaths<'a> {
    pub source: &'a Path,
    pub trusted: &'a Path,
    pub trusted_bin: &'a Path,
    pub config: &'a Path,
    pub socket: &'a Path,
}

#[cfg(target_os = "linux")]
pub fn install(repo: &str) -> Result<()> {
    install_with_paths(
        repo,
        &PolicyPaths {
            source: Path::new("/src"),
            trusted: Path::new("/trusted"),
            trusted_bin: Path::new("/trusted/bin"),
            config: Path::new("/tmp/jj-config"),
            socket: Path::new("/run/sandbox-proxy"),
        },
    )
}

#[cfg(target_os = "linux")]
pub fn install_with_paths(repo: &str, paths: &PolicyPaths<'_>) -> Result<()> {
    install_with_paths_mode(repo, paths, true)
}

#[cfg(target_os = "linux")]
pub fn install_inspect(repo: &str) -> Result<()> {
    install_inspect_with_paths(
        repo,
        &PolicyPaths {
            source: Path::new("/src"),
            trusted: Path::new("/trusted"),
            trusted_bin: Path::new("/trusted/bin"),
            config: Path::new("/tmp/jj-config"),
            socket: Path::new("/run/sandbox-proxy"),
        },
    )
}

#[cfg(target_os = "linux")]
pub fn install_inspect_with_paths(repo: &str, paths: &PolicyPaths<'_>) -> Result<()> {
    install_with_paths_mode(repo, paths, false)
}

#[cfg(target_os = "linux")]
fn install_with_paths_mode(repo: &str, paths: &PolicyPaths<'_>, writable: bool) -> Result<()> {
    let trusted =
        PathFd::new(paths.trusted).wrap_err("cannot open trusted directory")?;
    let trusted_bin = PathFd::new(paths.trusted_bin)
        .wrap_err("cannot open trusted executable directory")?;
    let source = PathFd::new(paths.source).wrap_err("cannot open source directory")?;
    let repository = PathFd::new(repo).wrap_err("cannot open repository directory")?;
    let git_path = env::var("JJ_PROXY_GIT_DIR").wrap_err("Git directory is not configured")?;
    let common_path =
        env::var("JJ_PROXY_COMMON_DIR").wrap_err("Git common directory is not configured")?;
    let jj_repo_path =
        env::var("JJ_PROXY_JJ_REPO").wrap_err("Jujutsu repository directory is not configured")?;
    let git = PathFd::new(&git_path).wrap_err("cannot open Git metadata directory")?;
    let common = PathFd::new(&common_path).wrap_err("cannot open Git common directory")?;
    let jj =
        PathFd::new(format!("{repo}/.jj")).wrap_err("cannot open Jujutsu metadata directory")?;
    let jj_repo =
        PathFd::new(&jj_repo_path).wrap_err("cannot open Jujutsu repository directory")?;
    let config =
        PathFd::new(paths.config).wrap_err("cannot open secure config directory")?;
    let socket =
        PathFd::new(paths.socket).wrap_err("cannot open proxy socket directory")?;
    let system_config =
        PathFd::new("/etc").wrap_err("cannot open system configuration directory")?;
    let system_lib = PathFd::new("/lib").wrap_err("cannot open system library directory")?;
    let user_lib = PathFd::new("/usr/lib").wrap_err("cannot open user library directory")?;
    let null = PathFd::new("/dev/null").wrap_err("cannot open null device")?;
    let read_access = make_bitflags!(AccessFs::{ ReadFile | ReadDir });
    let write_access = make_bitflags!(AccessFs::{
        WriteFile | RemoveDir | RemoveFile | MakeDir | MakeReg | MakeSock |
        MakeFifo | MakeSym | Refer | Truncate
    });
    let repository_access = if writable { read_access | write_access } else { read_access };
    let metadata_access = repository_access;
    let status = Ruleset::default()
        .set_compatibility(CompatLevel::HardRequirement)
        .handle_access(read_access | write_access | AccessFs::Execute)
        .wrap_err("cannot configure Landlock filesystem access")?
        .create()
        .wrap_err("cannot create Landlock ruleset")?
        .add_rule(PathBeneath::new(trusted, read_access))
        .wrap_err("cannot add trusted read rule")?
        .add_rule(PathBeneath::new(trusted_bin, AccessFs::Execute))
        .wrap_err("cannot add trusted Landlock execution rule")?
        .add_rule(PathBeneath::new(source, read_access))
        .wrap_err("cannot add /src read-only rule")?
        .add_rule(PathBeneath::new(repository, repository_access))
        .wrap_err("cannot add repository access rule")?
        .add_rule(PathBeneath::new(git, metadata_access))
        .wrap_err("cannot add Git metadata access rule")?
        .add_rule(PathBeneath::new(common, metadata_access))
        .wrap_err("cannot add Git common-directory access rule")?
        .add_rule(PathBeneath::new(jj, metadata_access))
        .wrap_err("cannot add Jujutsu metadata access rule")?
        .add_rule(PathBeneath::new(jj_repo, metadata_access))
        .wrap_err("cannot add Jujutsu repository access rule")?
        .add_rule(PathBeneath::new(config, if writable { read_access | write_access } else { read_access }))
        .wrap_err("cannot add configuration access rule")?
        .add_rule(PathBeneath::new(socket, read_access | write_access))
        .wrap_err("cannot add proxy socket write rule")?
        .add_rule(PathBeneath::new(system_config, read_access))
        .wrap_err("cannot add system configuration read rule")?
        .add_rule(PathBeneath::new(
            system_lib,
            read_access | AccessFs::Execute,
        ))
        .wrap_err("cannot add system library runtime rule")?
        .add_rule(PathBeneath::new(user_lib, read_access))
        .wrap_err("cannot add user library read rule")?
        .add_rule(PathBeneath::new(
            null,
            make_bitflags!(AccessFs::{ ReadFile | WriteFile }),
        ))
        .wrap_err("cannot add null-device rule")?
        .restrict_self()
        .wrap_err("cannot enforce Landlock execution policy")?;
    if !matches!(
        status.ruleset,
        RulesetStatus::FullyEnforced | RulesetStatus::PartiallyEnforced
    ) || !status.no_new_privs
    {
        bail!("Landlock execution policy was not enforced: {status:?}");
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
pub fn install(_repo: &str) -> Result<()> {
    Err(color_eyre::eyre::eyre!("the jj proxy requires Linux Landlock support"))
}

#[cfg(not(target_os = "linux"))]
pub fn install_inspect(_repo: &str) -> Result<()> {
    Err(color_eyre::eyre::eyre!("the jj proxy requires Linux Landlock support"))
}

#[cfg(not(target_os = "linux"))]
pub fn install_inspect_with_paths(_repo: &str, _paths: &PolicyPaths<'_>) -> Result<()> {
    Err(color_eyre::eyre::eyre!("the jj proxy requires Linux Landlock support"))
}

#[cfg(not(target_os = "linux"))]
pub fn install_with_paths(_repo: &str, _paths: &PolicyPaths<'_>) -> Result<()> {
    Err(color_eyre::eyre::eyre!("the jj proxy requires Linux Landlock support"))
}
