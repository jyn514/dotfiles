//! Trusted launch authority. Guest requests can select, but cannot extend, it.
use color_eyre::eyre::{bail, Result, WrapErr};
use serde::{Deserialize, Serialize};
use std::{collections::{HashMap, HashSet}, fs, os::unix::fs::MetadataExt, path::Path};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Workspace {
    pub root: String,
    pub git_dir: String,
    pub common_dir: String,
    pub jj_repo: String,
    pub lock: String,
}

pub fn load() -> Result<Vec<Workspace>> {
    let json = std::env::var("JJ_PROXY_WORKSPACES").wrap_err("workspace authority is not configured")?;
    let workspaces: Vec<Workspace> = serde_json::from_str(&json).wrap_err("invalid workspace authority")?;
    validate(&workspaces)?;
    let active = std::env::var("JJ_PROXY_REPO").wrap_err("active workspace is not configured")?;
    if !workspaces.iter().any(|workspace| workspace.root == active) {
        bail!("active workspace is absent from workspace authority");
    }
    Ok(workspaces)
}

fn validate_description(workspaces: &[Workspace]) -> Result<()> {
    if workspaces.is_empty() { bail!("workspace authority is empty"); }
    let mut roots = HashSet::new();
    let mut stores = HashMap::new();
    for workspace in workspaces {
        if !roots.insert(&workspace.root) { bail!("duplicate workspace root"); }
        let root = Path::new(&workspace.root);
        if root == Path::new("/src") || !root.starts_with("/src") { bail!("workspace root is outside /src"); }
        for path in [&workspace.root, &workspace.git_dir, &workspace.common_dir, &workspace.jj_repo] {
            if !Path::new(path).is_absolute() || path.contains('\0') || path.split('/').any(|part| part == "." || part == "..")
                || path.contains("//") || path.ends_with('/') { bail!("launch path is not canonical absolute: {path}"); }
        }
        let lock = Path::new(&workspace.lock);
        let hash = lock.file_name().and_then(|name| name.to_str()).and_then(|name| name.strip_suffix(".lock")).unwrap_or("");
        if lock.parent() != Some(Path::new("/run/jj-locks")) || workspace.lock != format!("/run/jj-locks/{hash}.lock")
            || hash.is_empty() || !hash.bytes().all(|b| b.is_ascii_hexdigit()) { bail!("invalid repository request lock path"); }
        if stores.insert(&workspace.jj_repo, &workspace.lock).is_some_and(|previous| previous != &workspace.lock) {
            bail!("inconsistent backing store lock identity");
        }
    }
    Ok(())
}

pub fn validate(workspaces: &[Workspace]) -> Result<()> {
    validate_description(workspaces)?;
    let mut stores = HashMap::new();
    let mut locks = HashMap::new();
    for workspace in workspaces {
        let root = Path::new(&workspace.root);
        for path in [&workspace.root, &workspace.git_dir, &workspace.common_dir, &workspace.jj_repo] {
            if !Path::new(path).is_absolute() || fs::canonicalize(path).wrap_err("cannot resolve launch path")? != Path::new(path) {
                bail!("launch path is not canonical absolute: {path}");
            }
            if !Path::new(path).is_dir() { bail!("launch path is not a directory: {path}"); }
        }
        let lock = Path::new(&workspace.lock);
        let metadata = fs::symlink_metadata(lock).wrap_err("cannot inspect repository request lock")?;
        if !metadata.is_file() || fs::canonicalize(lock)? != lock { bail!("request lock is not a canonical regular file"); }
        let store_metadata = fs::metadata(&workspace.jj_repo)?;
        let store_id = (store_metadata.dev(), store_metadata.ino());
        let lock_id = (metadata.dev(), metadata.ino());
        // Bind mounts may expose the same host backing store under distinct
        // canonical guest paths. Object identity, not guest spelling, owns the lease.
        validate_identity(&mut stores, &mut locks, store_id, lock_id)?;
        if !root.join(".jj").is_dir() { bail!("workspace has no Jujutsu metadata"); }
        let entry = root.join(".jj/repo");
        let backing = if entry.is_dir() { fs::canonicalize(entry)? } else {
            fs::canonicalize(root.join(".jj").join(fs::read_to_string(entry)?.trim_end()))?
        };
        validate_backing(&backing, Path::new(&workspace.jj_repo))?;
    }
    Ok(())
}

/// Launch paths are canonicalized separately. Canonical spelling does not
/// identify a backing object: two bind destinations can both be canonical.
fn validate_backing(backing: &Path, configured: &Path) -> Result<()> {
    let actual = fs::metadata(backing)?;
    let expected = fs::metadata(configured)?;
    if (actual.dev(), actual.ino()) != (expected.dev(), expected.ino()) {
        bail!("workspace backing store disagrees with launch authority");
    }
    Ok(())
}

type Identity = (u64, u64);
fn validate_identity(stores: &mut HashMap<Identity, Identity>, locks: &mut HashMap<Identity, Identity>, store: Identity, lock: Identity) -> Result<()> {
    if stores.insert(store, lock).is_some_and(|previous| previous != lock)
        || locks.insert(lock, store).is_some_and(|previous| previous != store) {
        bail!("inconsistent backing store lock identity");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn workspace(root: &str) -> Workspace {
        Workspace { root: root.into(), git_dir: "/src/repository/.git".into(), common_dir: "/src/repository/.git".into(),
            jj_repo: "/src/repository/.jj/repo".into(), lock: "/run/jj-locks/abcdef.lock".into() }
    }

    #[test]
    fn launch_authority_is_nonempty_exact_and_store_lock_consistent() {
        let one = workspace("/src/relocated");
        assert!(validate_description(&[one.clone()]).is_ok());
        assert!(validate_description(&[]).is_err());
        assert!(validate_description(&[one.clone(), one.clone()]).is_err());
        let linked = workspace("/src/linked");
        assert!(validate_description(&[one.clone(), linked.clone()]).is_ok());
        let mut mismatch = linked.clone(); mismatch.lock = "/run/jj-locks/123456.lock".into();
        assert!(validate_description(&[one.clone(), mismatch]).is_err());
        let mut independent = linked; independent.jj_repo = "/src/other/.jj/repo".into();
        // Guest spellings alone cannot distinguish two bind aliases of one store.
        assert!(validate_description(&[one.clone(), independent.clone()]).is_ok());
        independent.lock = "/run/jj-locks/123456.lock".into();
        assert!(validate_description(&[one, independent]).is_ok());
    }

    #[test]
    fn authority_rejects_ambiguous_paths_and_extra_or_missing_fields() {
        for root in ["relative", "/outside/repo", "/src", "/src/../outside", "/src/./repo", "/src//repo", "/src/repo/"] {
            assert!(validate_description(&[workspace(root)]).is_err(), "accepted {root}");
        }
        let encoded = serde_json::to_value(workspace("/src/relocated")).unwrap();
        let mut extra = encoded.clone(); extra["writable"] = true.into();
        assert!(serde_json::from_value::<Workspace>(extra).is_err());
        let mut missing = encoded.clone(); missing.as_object_mut().unwrap().remove("lock");
        assert!(serde_json::from_value::<Workspace>(missing).is_err());
        let mut wrong_type = encoded; wrong_type["root"] = 12.into();
        assert!(serde_json::from_value::<Workspace>(wrong_type).is_err());
    }

    #[test]
    fn filesystem_identity_preserves_store_aliases_without_sharing_independent_locks() {
        let mut stores = HashMap::new(); let mut locks = HashMap::new();
        validate_identity(&mut stores, &mut locks, (1, 10), (2, 20)).unwrap();
        validate_identity(&mut stores, &mut locks, (1, 10), (2, 20)).unwrap();
        assert!(validate_identity(&mut stores.clone(), &mut locks.clone(), (1, 10), (2, 21)).is_err());
        assert!(validate_identity(&mut stores.clone(), &mut locks.clone(), (1, 11), (2, 20)).is_err());
        validate_identity(&mut stores, &mut locks, (1, 11), (2, 21)).unwrap();
    }

    #[test]
    fn backing_comparison_accepts_filesystem_alias_but_rejects_different_directory() {
        let root = std::env::temp_dir().join(format!("jj-backing-alias-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let backing = root.join("backing");
        let alias = root.join("metadata-alias");
        let different = root.join("different-backing");
        fs::create_dir(&backing).unwrap();
        fs::create_dir(&different).unwrap();
        // A symlink exercises this comparison's filesystem-identity boundary
        // without requiring mount privileges. Production launch validation still
        // rejects noncanonical paths; the container suite covers canonical bind aliases.
        std::os::unix::fs::symlink(&backing, &alias).unwrap();
        assert_ne!(backing, alias);
        validate_backing(&backing, &alias).unwrap();
        assert!(validate_backing(&backing, &different).is_err());
        fs::remove_dir_all(root).unwrap();
    }

}
