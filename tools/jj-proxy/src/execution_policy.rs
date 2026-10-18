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
    install_with_paths_mode(repo, paths, true, None)
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
    install_with_paths_mode(repo, paths, false, None)
}

#[cfg(target_os = "linux")]
fn install_with_paths_mode(repo: &str, paths: &PolicyPaths<'_>, writable: bool, authority: Option<&[crate::workspaces::Workspace]>) -> Result<()> {
    let trusted =
        PathFd::new(paths.trusted).wrap_err("cannot open trusted directory")?;
    let trusted_bin = PathFd::new(paths.trusted_bin)
        .wrap_err("cannot open trusted executable directory")?;
    let source = PathFd::new(paths.source).wrap_err("cannot open source directory")?;
    let mut grants = Vec::new();
    if let Some(workspaces) = authority {
        for workspace in workspaces {
            for path in [&workspace.root, &workspace.git_dir, &workspace.common_dir, &workspace.jj_repo] {
                grants.push(PathFd::new(path).wrap_err("cannot open authorized workspace path")?);
            }
            grants.push(PathFd::new(format!("{}/.jj", workspace.root))?);
        }
    } else {
        // Legacy helper surface retained for native policy tests, never used by serve.
        grants.push(PathFd::new(repo)?);
        grants.push(PathFd::new(format!("{repo}/.jj"))?);
        for key in ["JJ_PROXY_GIT_DIR", "JJ_PROXY_COMMON_DIR", "JJ_PROXY_JJ_REPO"] {
            grants.push(PathFd::new(env::var(key).wrap_err("metadata directory is not configured")?)?);
        }
    }
    let config =
        PathFd::new(paths.config).wrap_err("cannot open secure config directory")?;
    let socket =
        PathFd::new(paths.socket).wrap_err("cannot open proxy socket directory")?;
    let system_config =
        PathFd::new("/etc").wrap_err("cannot open system configuration directory")?;
    let system_lib = PathFd::new("/lib").wrap_err("cannot open system library directory")?;
    let user_lib = PathFd::new("/usr/lib").wrap_err("cannot open user library directory")?;
    let null = PathFd::new("/dev/null").wrap_err("cannot open null device")?;
    let random = PathFd::new("/dev/urandom").wrap_err("cannot open random device")?;
    let read_access = make_bitflags!(AccessFs::{ ReadFile | ReadDir });
    let write_access = make_bitflags!(AccessFs::{
        WriteFile | RemoveDir | RemoveFile | MakeDir | MakeReg | MakeSock |
        MakeFifo | MakeSym | Refer | Truncate
    });
    let repository_access = if writable { read_access | write_access } else { read_access };
    let mut ruleset = Ruleset::default()
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
        // Alpine Git reads /dev/urandom when creating temporary object files.
        .add_rule(PathBeneath::new(random, AccessFs::ReadFile))
        .wrap_err("cannot add random-device read rule")?;
    for grant in grants {
        ruleset = ruleset.add_rule(PathBeneath::new(grant, repository_access))?;
    }
    if let Some(workspaces) = authority.filter(|_| writable) {
        for workspace in workspaces {
            ruleset = ruleset.add_rule(PathBeneath::new(PathFd::new(&workspace.lock)?, AccessFs::ReadFile | AccessFs::WriteFile))?;
        }
    }
    let status = ruleset.restrict_self()
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

/// Server authority is always explicit; inspection adds a read-only restriction.
#[cfg(target_os = "linux")]
pub fn install_workspaces(workspaces: &[crate::workspaces::Workspace], writable: bool) -> Result<()> {
    install_workspaces_with_paths(workspaces, &PolicyPaths {
        source: Path::new("/src"), trusted: Path::new("/trusted"),
        trusted_bin: Path::new("/trusted/bin"), config: Path::new("/tmp/jj-config"),
        socket: Path::new("/run/sandbox-proxy"),
    }, writable)
}
#[cfg(target_os = "linux")]
pub fn install_workspaces_with_paths(workspaces: &[crate::workspaces::Workspace], paths: &PolicyPaths<'_>, writable: bool) -> Result<()> {
    let Some(first) = workspaces.first() else { bail!("workspace authority is empty"); };
    install_with_paths_mode(&first.root, paths, writable, Some(workspaces))
}
#[cfg(not(target_os = "linux"))]
pub fn install_workspaces(_: &[crate::workspaces::Workspace], _: bool) -> Result<()> {
    Err(color_eyre::eyre::eyre!("the jj proxy requires Linux Landlock support"))
}

#[cfg(not(target_os = "linux"))]
pub fn install_workspaces_with_paths(_: &[crate::workspaces::Workspace], _: &PolicyPaths<'_>, _: bool) -> Result<()> {
    Err(color_eyre::eyre::eyre!("the jj proxy requires Linux Landlock support"))
}
