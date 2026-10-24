//! Configuration-free repository support checks, before either native repository open.
//!
//! This is a restricted-layout admission check, not a filesystem sandbox. Accepted
//! metadata (including effective paths) must remain protected while native code runs.
//! The launcher must protect the accepted root's `.git` entry and administrative
//! paths with its metadata overlays; this check does not provide OS confinement.
//! No SQLite file is opened here; even legacy sidecars are inventoried with lstat.
use std::{
    collections::BTreeSet,
    fs,
    io::Read,
    os::unix::fs::MetadataExt,
    path::{Component, Path, PathBuf},
};

use anyhow::{bail, ensure, Context, Result};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RepositoryContext {
    pub workspace: PathBuf,
    pub common_dir: PathBuf,
}

const MAX_CONTROL: u64 = 64 * 1024;
const MAX_CONFIG: u64 = 4 * 1024 * 1024;
const MAX_OBJECT_ENTRIES: usize = 1_000_000;

/// Resolve actual invocation/common identity without gix::discover/open or Git helpers.
///
/// Accepts only discovered worktree roots, or the invocation git directory for
/// bare repositories; ordinary subdirectories are not fixed discovery authority.
/// Supports conventional, linked, bare, and separate-gitdir repositories. Refuses
/// all object-tree symlinks (even internal ones), special files, multiply linked
/// config/object/store files, deeply nested object layouts, and ambiguous
/// nonstandard common directories with a `.git` entry. This deliberately rejects
/// some layouts that native Git can use, including hardlink-sharing local clones.
pub fn preflight(workspace: &Path, expected_common: &Path) -> Result<RepositoryContext> {
    let workspace = fs::canonicalize(workspace).context("canonicalize accepted workspace")?;
    let expected_common =
        fs::canonicalize(expected_common).context("canonicalize expected common directory")?;
    ensure!(workspace.is_dir(), "workspace is not a directory");
    // is_git()/upwards_opts() open HEAD and layout controls before returning.
    // Derive only the accepted root candidate first, validating every control
    // before any public locator is allowed to read it. Never search parents:
    // failed recognition must not inspect an unchecked parent repository.
    let candidate;
    let invocation;
    if workspace == expected_common {
        candidate = workspace.clone();
        invocation = workspace.clone();
    } else {
        candidate = workspace.join(".git");
        let meta = entry(&candidate)?.context(
            "accepted workspace must be the discovered worktree root or the bare invocation git directory",
        )?;
        if meta.file_type().is_dir() {
            invocation = fs::canonicalize(&candidate)?;
        } else {
            control_file(&candidate)?;
            invocation = fs::canonicalize(gix_discover::path::from_gitdir_file(&candidate)?)
                .context("canonicalize invocation git directory")?;
        }
    }
    directory(&invocation)?;
    control_file(&invocation.join("HEAD"))?;
    let common = match entry(&invocation.join("commondir"))? {
        Some(_) => {
            control_file(&invocation.join("commondir"))?;
            let relative = gix_discover::path::from_plain_file(&invocation.join("commondir"))
                .context("missing commondir")??;
            // is_git() may also read gitdir for an administrative-directory
            // candidate with commondir. File-based linked-worktree candidates
            // do not need it, but validating a present entry is conservative.
            let gitdir = invocation.join("gitdir");
            if entry(&gitdir)?.is_some() {
                control_file(&gitdir)?;
            }
            fs::canonicalize(invocation.join(relative)).context("resolve commondir")?
        }
        None => invocation.clone(),
    };
    ensure!(
        common == expected_common,
        "repository common identity mismatch: discovered {}, expected {}",
        common.display(),
        expected_common.display()
    );
    directory(&common)?;
    if common != invocation {
        control_file(&common.join("HEAD"))?;
    }
    // Native common_repository reopens this path and git-meta's gix 0.83 does
    // likewise. Both versions prefer PATH/.git for non-.git/non-*.git names.
    let conventional = common
        .file_name()
        .and_then(|n| n.to_str())
        .is_some_and(|n| n == ".git" || n.ends_with(".git"));
    ensure!(
        conventional || entry(&common.join(".git"))?.is_none(),
        "ambiguous common repository {}; nested .git is unsupported",
        common.display()
    );
    ensure!(
        entry(&common.join("commondir"))?.is_none(),
        "common directory itself redirects through commondir"
    );
    let kind = gix_discover::is_git(&candidate)
        .context("locate root repository without loading configuration")?;
    let located = gix_discover::repository::Path::from_dot_git_dir(candidate, kind, &workspace)
        .context("resolve located repository paths")?;
    let (located_invocation, worktree) = located.into_repository_and_work_tree_directories();
    ensure!(
        fs::canonicalize(located_invocation)? == invocation,
        "configuration-free locator changed invocation identity"
    );
    if let Some(worktree) = worktree {
        ensure!(
            workspace == fs::canonicalize(worktree)?,
            "accepted workspace must be the discovered worktree root"
        );
    } else {
        ensure!(
            workspace == invocation,
            "accepted bare workspace must be the invocation git directory"
        );
    }
    gix_discover::is_git(&common)
        .context("common directory is not a reopenable native repository")?;

    let worktree_config = check_config(&common.join("config"))?;
    if worktree_config {
        check_config(&invocation.join("config.worktree"))?;
        if invocation != common {
            check_config(&common.join("config.worktree"))?;
        }
    }
    let objects = common.join("objects");
    directory(&objects)?;
    // lstat after rejecting parent symlinks: dangling entries are still refusal.
    if entry(&objects.join("info"))?.is_some() {
        directory(&objects.join("info"))?;
        ensure!(
            entry(&objects.join("info/alternates"))?.is_none(),
            "objects/info/alternates is unsupported (including dangling symlinks)"
        );
    }
    let mut remaining = MAX_OBJECT_ENTRIES;
    scan_objects(&objects, 0, &mut remaining)?;
    // A read-only metadata mount cannot protect another hard-link name in the
    // writable checkout. Ordinary native opens read common packed-refs too.
    // Neither packed-refs nor SQLite contents are opened or repaired here.
    for name in [
        "packed-refs",
        "git-meta.sqlite",
        "git-meta.sqlite-wal",
        "git-meta.sqlite-shm",
    ] {
        let path = common.join(name);
        if entry(&path)?.is_some() {
            regular(&path)?;
        }
    }
    inventory_legacy(&common, &invocation)?;
    Ok(RepositoryContext {
        workspace,
        common_dir: common,
    })
}

fn entry(path: &Path) -> Result<Option<fs::Metadata>> {
    match fs::symlink_metadata(path) {
        Ok(meta) => Ok(Some(meta)),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e).with_context(|| format!("inspect {}", path.display())),
    }
}

fn regular(path: &Path) -> Result<fs::Metadata> {
    let meta = entry(path)?.with_context(|| format!("missing {}", path.display()))?;
    ensure!(
        meta.file_type().is_file(),
        "unsupported non-regular file or symlink: {}",
        path.display()
    );
    single_link(path, &meta)?;
    Ok(meta)
}

fn single_link(path: &Path, meta: &fs::Metadata) -> Result<()> {
    // Reject even aliases that happen to be trusted today: readiness cannot
    // establish all names of an inode without scanning unrelated workspaces.
    ensure!(
        meta.nlink() == 1,
        "unsupported hard-linked repository file (expected one link): {}",
        path.display()
    );
    Ok(())
}

fn control_file(path: &Path) -> Result<()> {
    ensure!(
        regular(path)?.len() <= MAX_CONTROL,
        "repository discovery control exceeds preflight limit: {}",
        path.display()
    );
    Ok(())
}

fn directory(path: &Path) -> Result<()> {
    let meta = entry(path)?.with_context(|| format!("missing directory {}", path.display()))?;
    ensure!(
        meta.file_type().is_dir(),
        "unsupported directory redirection: {}",
        path.display()
    );
    Ok(())
}

fn check_config(path: &Path) -> Result<bool> {
    if entry(path)?.is_none() {
        return Ok(false);
    }
    ensure!(
        regular(path)?.len() <= MAX_CONFIG,
        "configuration exceeds preflight limit: {}",
        path.display()
    );
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take(MAX_CONFIG + 1)
        .read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 <= MAX_CONFIG,
        "configuration exceeds preflight limit"
    );
    let config = gix_config::File::from_bytes_no_includes(
        &bytes,
        gix_config::file::Metadata::api(),
        Default::default(),
    )
    .with_context(|| {
        format!(
            "parse config without following includes: {}",
            path.display()
        )
    })?;
    for section in config.sections() {
        let name: &[u8] = section.header().name().as_ref();
        ensure!(
            !name.eq_ignore_ascii_case(b"include") && !name.eq_ignore_ascii_case(b"includeIf"),
            "repository configuration includes are unsupported: {}",
            path.display()
        );
    }
    config
        .boolean("extensions.worktreeConfig")
        .transpose()
        .with_context(|| format!("invalid extensions.worktreeConfig in {}", path.display()))
        .map(|v| v.unwrap_or(false))
}

fn scan_objects(path: &Path, depth: usize, remaining: &mut usize) -> Result<()> {
    ensure!(
        depth <= 8,
        "object layout exceeds preflight depth limit: {}",
        path.display()
    );
    for item in fs::read_dir(path)? {
        let path = item?.path();
        ensure!(
            *remaining > 0,
            "object layout exceeds preflight entry limit"
        );
        *remaining -= 1;
        let meta = entry(&path)?.context("object entry disappeared during preflight")?;
        if meta.file_type().is_dir() {
            scan_objects(&path, depth + 1, remaining)?;
        } else {
            ensure!(
                meta.file_type().is_file(),
                "unsupported object symlink or special file: {}",
                path.display()
            );
            single_link(&path, &meta)?;
            if path.file_name().is_some_and(|n| n == "multi-pack-index") {
                let index = gix_pack::multi_index::File::at(&path)
                    .with_context(|| format!("parse multi-pack-index {}", path.display()))?;
                for name in index.index_names() {
                    ensure!(
                        safe_pack_name(name),
                        "unsupported multi-pack-index pack name: {}",
                        name.display()
                    );
                }
            }
        }
    }
    Ok(())
}

fn safe_pack_name(path: &Path) -> bool {
    let mut components = path.components();
    if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
        return false;
    }
    let Some(name) = path.to_str() else {
        return false;
    };
    let Some(hash) = name
        .strip_prefix("pack-")
        .and_then(|n| n.strip_suffix(".idx"))
    else {
        return false;
    };
    matches!(hash.len(), 40 | 64) && hash.bytes().all(|c| c.is_ascii_hexdigit())
}

fn inventory_legacy(common: &Path, invocation: &Path) -> Result<()> {
    let mut private = vec![invocation.to_owned()];
    let worktrees = common.join("worktrees");
    if entry(&worktrees)?.is_some() {
        directory(&worktrees)?;
        for item in fs::read_dir(&worktrees)? {
            private.push(item?.path());
        }
    }
    let mut legacy = BTreeSet::new();
    for dir in private {
        let canonical = fs::canonicalize(&dir).with_context(|| {
            format!(
                "resolve administrative worktree directory {}",
                dir.display()
            )
        })?;
        if canonical == common {
            continue;
        }
        directory(&dir)?;
        for name in [
            "git-meta.sqlite",
            "git-meta.sqlite-wal",
            "git-meta.sqlite-shm",
        ] {
            let path = dir.join(name);
            if entry(&path)?.is_some() {
                legacy.insert(path);
            }
        }
    }
    if !legacy.is_empty() {
        bail!("legacy worktree-local metadata stores found: {}. Refusing shared storage; stop all database users and inventory/preserve these stores offline before any manual relocation. No data was migrated", legacy.iter().map(|p| p.display().to_string()).collect::<Vec<_>>().join(", "));
    }
    Ok(())
}
