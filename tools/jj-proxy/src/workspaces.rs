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

/// Resolve the backing repository exactly as a linked workspace's `.jj/repo`
/// pointer names it. Canonical paths alone are not identities across bind aliases.
pub fn backing_repo(root: &Path) -> Result<std::path::PathBuf> {
    let entry = root.join(".jj/repo");
    let backing = if entry.is_dir() { entry } else {
        root.join(".jj").join(fs::read_to_string(&entry).wrap_err("cannot read linked workspace repository pointer")?.trim_end())
    };
    fs::canonicalize(backing).wrap_err("cannot resolve workspace backing repository")
}

/// A linked workspace inherits the startup authority and request lock of its
/// backing repository, including when bind mounts give that repository aliases.
/// This does not grant filesystem access beyond the existing mounts and policy.
pub fn authority_for<'a>(root: &Path, workspaces: &'a [Workspace]) -> Result<Option<&'a Workspace>> {
    let actual = fs::metadata(backing_repo(root)?)?;
    for workspace in workspaces {
        let expected = fs::metadata(&workspace.jj_repo)?;
        if (actual.dev(), actual.ino()) == (expected.dev(), expected.ino()) {
            return Ok(Some(workspace));
        }
    }
    Ok(None)
}

pub struct MountPoint {
    directory: std::os::fd::OwnedFd,
    parent_only: bool,
    path: std::path::PathBuf,
}

/// Pin the server's mount destinations before restriction. Directory descriptors
/// keep mount aliases visible to overlap checks even if an ancestor is renamed.
pub fn mount_points() -> Result<Vec<MountPoint>> {
    use std::os::unix::ffi::OsStringExt;
    let table = fs::read_to_string("/proc/self/mountinfo")?;
    table.lines().map(|line| {
        let field = line.split_whitespace().nth(4).ok_or_else(|| color_eyre::eyre::eyre!("invalid mountinfo record"))?;
        let mut bytes = Vec::new();
        let mut input = field.as_bytes().iter().copied();
        while let Some(byte) = input.next() {
            if byte == b'\\' {
                let digits: Vec<_> = input.by_ref().take(3).collect();
                if digits.len() != 3 || digits.iter().any(|digit| !(b'0'..=b'7').contains(digit)) {
                    bail!("invalid mountinfo path escape");
                }
                let value = (digits[0] - b'0') as u16 * 64 + (digits[1] - b'0') as u16 * 8 + (digits[2] - b'0') as u16;
                bytes.push(u8::try_from(value)?);
            } else { bytes.push(byte); }
        }
        let path = std::path::PathBuf::from(std::ffi::OsString::from_vec(bytes));
        let directory_mount = path.is_dir();
        let target = if directory_mount { path.as_path() } else { path.parent().ok_or_else(|| color_eyre::eyre::eyre!("invalid file mount"))? };
        Ok(MountPoint { directory: fs::File::open(target)?.into(), parent_only: directory_mount, path })
    }).collect()
}

/// Refuse a linked child whose writable scope would include another protected
/// store or a nested mount alias. Mount destinations come from the trusted
/// server's immutable startup namespace, not a guest request.
pub fn validate_linked_scope(root: &std::os::fd::OwnedFd, selected: &Workspace,
    workspaces: &[Workspace], mounts: &[MountPoint]) -> Result<()> {
    use std::os::fd::{AsRawFd, OwnedFd, FromRawFd};
    use nix::{fcntl::{openat, OFlag}, sys::stat::{fstat, Mode}};
    fn parent(directory: &OwnedFd) -> nix::Result<OwnedFd> {
        let fd = openat(Some(directory.as_raw_fd()), "..", OFlag::O_RDONLY | OFlag::O_DIRECTORY | OFlag::O_CLOEXEC, Mode::empty())?;
        // SAFETY: openat returned an owned descriptor.
        Ok(unsafe { OwnedFd::from_raw_fd(fd) })
    }
    fn contains(root: &OwnedFd, target: &OwnedFd, strict: bool) -> Result<bool> {
        let wanted = fstat(root.as_raw_fd())?;
        let mut current = target.try_clone()?;
        let mut skip = strict;
        loop {
            let here = fstat(current.as_raw_fd())?;
            if !skip && (here.st_dev, here.st_ino) == (wanted.st_dev, wanted.st_ino) { return Ok(true); }
            skip = false;
            let above = match parent(&current) {
                Ok(parent) => parent,
                // All candidate write scopes already have inherited read access.
                // A forbidden parent therefore cannot be inside any such scope;
                // stop where the server's Landlock read boundary ends.
                Err(nix::errno::Errno::EACCES | nix::errno::Errno::EPERM) => return Ok(false),
                Err(error) => return Err(error.into()),
            };
            let stat = fstat(above.as_raw_fd())?;
            if (here.st_dev, here.st_ino) == (stat.st_dev, stat.st_ino) { return Ok(false); }
            current = above;
        }
    }
    let metadata = fs::metadata(&selected.jj_repo)?;
    let mut scopes = vec![root.try_clone()?];
    for path in [&selected.git_dir, &selected.common_dir, &selected.jj_repo] {
        scopes.push(fs::File::open(path)?.into());
    }
    for scope in &scopes {
        for mount in mounts {
            if contains(scope, &mount.directory, mount.parent_only)? {
                bail!("linked workspace write scope contains a nested mount: {}", mount.path.display());
            }
        }
        for workspace in workspaces {
            let other = fs::metadata(&workspace.jj_repo)?;
            if (metadata.dev(), metadata.ino()) == (other.dev(), other.ino()) { continue; }
            for path in [Path::new(&workspace.root).join(".jj"), Path::new(&workspace.git_dir).to_path_buf(),
                Path::new(&workspace.common_dir).to_path_buf(), Path::new(&workspace.jj_repo).to_path_buf()] {
                let protected = fs::File::open(&path)?.into();
                if contains(scope, &protected, false)? { bail!("linked workspace write scope overlaps another protected repository: {}", path.display()); }
            }
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
        validate_backing(&backing_repo(root)?, Path::new(&workspace.jj_repo))?;
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

    fn fixture_workspace(root: &Path, name: &str) -> Workspace {
        let directory = root.join(name);
        fs::create_dir_all(directory.join(".jj/repo")).unwrap();
        fs::create_dir_all(directory.join(".git")).unwrap();
        Workspace { root: directory.to_str().unwrap().into(),
            git_dir: directory.join(".git").to_str().unwrap().into(),
            common_dir: directory.join(".git").to_str().unwrap().into(),
            jj_repo: directory.join(".jj/repo").to_str().unwrap().into(),
            lock: root.join(format!("{name}.lock")).to_str().unwrap().into() }
    }

    #[test]
    fn linked_authority_follows_store_identity_not_root_nesting() {
        let root = std::env::temp_dir().join(format!("jj-linked-authority-{}", std::process::id()));
        let authority = vec![fixture_workspace(&root, "active")];
        let independent = fixture_workspace(&root, "active/independent");
        assert!(authority_for(Path::new(&independent.root), &authority).unwrap().is_none());
        for name in ["active/nested", "sibling"] {
            let linked = root.join(name);
            fs::create_dir_all(linked.join(".jj")).unwrap();
            fs::write(linked.join(".jj/repo"), &authority[0].jj_repo).unwrap();
            let selected = authority_for(&linked, &authority).unwrap().unwrap();
            assert_eq!(authority[0].lock, selected.lock);
            // Rebinding a mutable child pointer must not retain prior authority.
            fs::write(linked.join(".jj/repo"), &independent.jj_repo).unwrap();
            assert!(authority_for(&linked, &authority).unwrap().is_none());
        }
        let alias = root.join("store-alias");
        std::os::unix::fs::symlink(&authority[0].jj_repo, &alias).unwrap();
        let linked = root.join("sibling");
        fs::write(linked.join(".jj/repo"), alias.to_str().unwrap()).unwrap();
        assert!(authority_for(&linked, &authority).unwrap().is_some());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn linked_scope_rejects_nested_protected_metadata_and_moved_mount_aliases() {
        let root = std::env::temp_dir().join(format!("jj-linked-scope-{}", std::process::id()));
        let selected = fixture_workspace(&root, "active");
        let child = root.join("active/child");
        fs::create_dir_all(&child).unwrap();
        let fd = fs::File::open(&child).unwrap().into();
        assert!(validate_linked_scope(&fd, &selected, std::slice::from_ref(&selected), &[]).is_ok());
        let nested = fixture_workspace(&child, "protected");
        let authorities = [selected.clone(), nested];
        assert!(validate_linked_scope(&fd, &selected, &authorities, &[]).unwrap_err().to_string().contains("overlaps"));
        // A pinned alias still detects overlap after its ordinary ancestor moves
        // and a replacement directory appears at the original startup path.
        let container = root.join("alias-parent");
        let alias = container.join("metadata");
        fs::create_dir_all(&alias).unwrap();
        let mount = MountPoint { directory: fs::File::open(&alias).unwrap().into(), parent_only: true, path: alias.clone() };
        fs::rename(&container, child.join("moved-alias")).unwrap();
        fs::create_dir_all(&alias).unwrap();
        assert!(validate_linked_scope(&fd, &selected, std::slice::from_ref(&selected), &[mount]).unwrap_err().to_string().contains("nested mount"));
        fs::remove_dir_all(root).unwrap();
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
