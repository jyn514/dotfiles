use color_eyre::eyre::Result;

#[cfg(target_os = "linux")]
use color_eyre::eyre::{bail, WrapErr};
#[cfg(target_os = "linux")]
use std::env;

#[cfg(target_os = "linux")]
use landlock::{
    make_bitflags, AccessFs, CompatLevel, Compatible, PathBeneath, PathFd, Ruleset, RulesetAttr,
    RulesetCreatedAttr, RulesetStatus,
};

#[cfg(target_os = "linux")]
pub fn install(repo: &str) -> Result<()> {
    let trusted = PathFd::new("/trusted").wrap_err("cannot open trusted directory")?;
    let trusted_bin =
        PathFd::new("/trusted/bin").wrap_err("cannot open trusted executable directory")?;
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
    let config = PathFd::new("/tmp/jj-config").wrap_err("cannot open secure config directory")?;
    let socket =
        PathFd::new("/run/sandbox-proxy").wrap_err("cannot open proxy socket directory")?;
    let system_config =
        PathFd::new("/etc").wrap_err("cannot open system configuration directory")?;
    let null = PathFd::new("/dev/null").wrap_err("cannot open null device")?;
    let read_access = make_bitflags!(AccessFs::{ ReadFile | ReadDir });
    let write_access = make_bitflags!(AccessFs::{
        WriteFile | RemoveDir | RemoveFile | MakeDir | MakeReg | MakeSock |
        MakeFifo | MakeSym | Refer | Truncate
    });
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
        .add_rule(PathBeneath::new(repository, read_access | write_access))
        .wrap_err("cannot add repository read-write rule")?
        .add_rule(PathBeneath::new(git, read_access | write_access))
        .wrap_err("cannot add Git metadata write rule")?
        .add_rule(PathBeneath::new(common, read_access | write_access))
        .wrap_err("cannot add Git common-directory rule")?
        .add_rule(PathBeneath::new(jj, read_access | write_access))
        .wrap_err("cannot add Jujutsu metadata write rule")?
        .add_rule(PathBeneath::new(jj_repo, read_access | write_access))
        .wrap_err("cannot add Jujutsu repository write rule")?
        .add_rule(PathBeneath::new(config, read_access | write_access))
        .wrap_err("cannot add configuration write rule")?
        .add_rule(PathBeneath::new(socket, read_access | write_access))
        .wrap_err("cannot add proxy socket write rule")?
        .add_rule(PathBeneath::new(system_config, read_access))
        .wrap_err("cannot add system configuration read rule")?
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
