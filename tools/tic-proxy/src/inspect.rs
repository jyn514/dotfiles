//! Trusted local repository metadata producer, not part of the request API.
//! Effective host configuration is queried separately by the launcher using Git.
use crate::{
    broker::{NATIVE_REVISION, POLICY_VERSION},
    protocol::VERSION,
    repository,
};
use serde::Serialize;
use std::{
    fmt, fs,
    path::{Path, PathBuf},
};

pub const MAX_CONTEXT_OUTPUT: usize = 64 * 1024;

#[derive(Debug)]
pub enum InspectError {
    Preflight,
    Context,
    Output,
}
impl fmt::Display for InspectError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Preflight => "unsupported repository context",
            Self::Context => "repository context does not match the explicit canonical roots",
            Self::Output => "context output is unrepresentable or exceeds 64 KiB",
        })
    }
}
impl std::error::Error for InspectError {}

#[derive(Serialize)]
struct RepositoryMetadata {
    version: u32,
    policy_version: u32,
    native_revision: &'static str,
    workspace: PathBuf,
    common_dir: PathBuf,
    invocation_git_dir: PathBuf,
}

/// Return one bounded metadata JSON line, or a fixed scrubbed diagnostic.
/// Preflight checks accepted local metadata; neither it nor this locator loads
/// effective host configuration, traverses refs/objects, or opens SQLite.
pub fn inspect_context(workspace: &Path, common_dir: &Path) -> Result<Vec<u8>, InspectError> {
    let context =
        repository::preflight(workspace, common_dir).map_err(|_| InspectError::Preflight)?;
    if workspace != context.workspace
        || common_dir != context.common_dir
        || !workspace.is_absolute()
        || !common_dir.is_absolute()
    {
        return Err(InspectError::Context);
    }

    // Reuse preflight's low-level explicit candidate, never upward discovery or
    // an environment-aware repository open. The locator reads checked HEAD and
    // layout controls, not effective configuration or HEAD's symbolic target.
    let candidate = if context.workspace == context.common_dir {
        context.workspace.clone()
    } else {
        context.workspace.join(".git")
    };
    let kind = gix_discover::is_git(&candidate).map_err(|_| InspectError::Preflight)?;
    let located =
        gix_discover::repository::Path::from_dot_git_dir(candidate, kind, &context.workspace)
            .ok_or(InspectError::Context)?;
    let (invocation, worktree) = located.into_repository_and_work_tree_directories();
    let invocation = fs::canonicalize(invocation).map_err(|_| InspectError::Context)?;
    match worktree {
        Some(worktree)
            if fs::canonicalize(&worktree).map_err(|_| InspectError::Context)?
                == context.workspace => {}
        None if invocation == context.workspace => {}
        _ => return Err(InspectError::Context),
    }
    let metadata = RepositoryMetadata {
        version: VERSION,
        policy_version: POLICY_VERSION,
        native_revision: NATIVE_REVISION,
        workspace: context.workspace,
        common_dir: context.common_dir,
        invocation_git_dir: invocation,
    };
    let mut encoded = serde_json::to_vec(&metadata).map_err(|_| InspectError::Output)?;
    encoded.push(b'\n');
    if encoded.len() > MAX_CONTEXT_OUTPUT {
        return Err(InspectError::Output);
    }
    Ok(encoded)
}
