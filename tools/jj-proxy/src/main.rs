use color_eyre::eyre::{bail, eyre, Result, WrapErr};
use jj_proxy::{execution_policy, policy, workspaces::{self, Workspace}};
#[allow(deprecated)]
use nix::fcntl::{flock, FlockArg};
use serde::{Deserialize, Serialize};
use nix::fcntl::{openat, OFlag};
use nix::sys::resource::{setrlimit, Resource};
use nix::sys::signal::{kill, Signal};
use nix::sys::stat::Mode;
use nix::unistd::{dup, fchdir, setsid, Pid};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::net::Shutdown;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const DEFAULT_SOCKET: &str = "/run/sandbox-proxy/socket";
const TRUSTED_PROXY: &str = "/trusted/bin/jj-proxy";
const TRUSTED_JJ_CONFIG: &str = "/trusted/jj.toml";
const TRUSTED_COMMAND_POLICY: &str = "/trusted/policy.toml";

fn socket_path() -> String {
    std::env::var("SANDBOX_PROXY_SOCKET").unwrap_or_else(|_| DEFAULT_SOCKET.to_owned())
}
const CONFIG_HOME: &str = "/tmp/jj-config";
const TEMP_HOME: &str = "/run/sandbox-proxy/jj-tmp";
const MAX_REQUEST: usize = 1 << 20;
const MAX_OUTPUT: usize = 8 << 20;
const TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum RequestMode { Mutate, Inspect }

impl Default for RequestMode { fn default() -> Self { Self::Mutate } }

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    version: u8,
    #[serde(default)]
    mode: RequestMode,
    cwd: String,
    argv: Vec<String>,
    #[serde(default)]
    agent_split: Option<AgentSplit>,
    #[serde(default)]
    user: Option<String>,
    #[serde(default)]
    email: Option<String>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Response { version: u8, exit: i32, stdout: String, stderr: String }

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct AgentSplit { patch: String, message: String, revision: String }

fn read_frame(stream: &mut UnixStream, limit: usize) -> io::Result<Vec<u8>> {
    let mut header = [0; 4];
    stream.read_exact(&mut header)?;
    let length = u32::from_be_bytes(header) as usize;
    if length > limit {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "message is too large"));
    }
    let mut body = vec![0; length];
    stream.read_exact(&mut body)?;
    Ok(body)
}

fn write_frame(stream: &mut UnixStream, body: &[u8]) -> io::Result<()> {
    let length = u32::try_from(body.len()).map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "message is too large"))?;
    stream.write_all(&length.to_be_bytes())?;
    stream.write_all(body)
}

fn require_eof(stream: &mut UnixStream) -> io::Result<()> {
    let mut trailing = [0u8; 1];
    match stream.read(&mut trailing)? {
        0 => Ok(()),
        _ => Err(io::Error::new(io::ErrorKind::InvalidData, "trailing bytes after request")),
    }
}

#[cfg(test)]
fn prepare_jj_config(repo: &str, scope: &str, jj: &Path, trusted_config: &Path, config_home: &Path) -> Result<()> {
    prepare_jj_config_deadline(repo, scope, jj, trusted_config, config_home, Instant::now() + TIMEOUT)
}

fn prepare_jj_config_deadline(repo: &str, scope: &str, jj: &Path, trusted_config: &Path, config_home: &Path, deadline: Instant) -> Result<()> {
    let mut command = Command::new(jj);
    command.arg("--config-file").arg(trusted_config)
        .args(["--repository", repo, "--ignore-working-copy", "config", "path", scope])
        .env_clear().env("HOME", "/nonexistent").env("XDG_CONFIG_HOME", config_home)
        .stdin(Stdio::null());
    // SAFETY: setsid is async-signal-safe and captures no shared state.
    unsafe { command.pre_exec(|| setsid().map(|_| ()).map_err(|error| io::Error::from_raw_os_error(error as i32))); }
    let (status, _, stderr) = run_bounded(&mut command, deadline).wrap_err("cannot initialize per-repository Jujutsu config")?;
    if status != 0 {
        bail!("cannot initialize per-repository Jujutsu config: jj exited with {status}: {}", String::from_utf8_lossy(&stderr[..stderr.len().min(8192)]).trim());
    }
    Ok(())
}

fn seed_inspection_config(config_id_path: &Path, kind: &str, config_home: &Path) -> Result<bool> {
    let config_id = match fs::read_to_string(config_id_path) {
        Ok(id) => id,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error).wrap_err("cannot read inspection repository config ID"),
    };
    if config_id.len() != 20 || !config_id.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        bail!("invalid inspection repository config ID");
    }
    let config_dir = config_home.join("jj").join(kind).join(config_id);
    fs::create_dir_all(&config_dir).wrap_err("cannot create inspection config cache")?;
    let metadata = config_dir.join("metadata.binpb");
    if !metadata.exists() {
        // An empty protobuf is a valid ConfigMetadata with no previous path.
        // Pinned jj fills in the path without rewriting the repo's config-id.
        fs::write(&metadata, []).wrap_err("cannot seed inspection config metadata")?;
    }
    Ok(true)
}

#[cfg(test)]
fn prepare_inspection_config(workspace: &Path, jj: &Path, trusted_config: &Path, config_home: &Path) -> Result<()> {
    prepare_inspection_config_deadline(workspace, jj, trusted_config, config_home, Instant::now() + TIMEOUT)
}

fn prepare_inspection_config_deadline(workspace: &Path, jj: &Path, trusted_config: &Path, config_home: &Path, deadline: Instant) -> Result<()> {
    let jj_dir = workspace.join(".jj");
    let repo_entry = jj_dir.join("repo");
    let repo_dir = if repo_entry.is_dir() {
        repo_entry
    } else {
        let pointer = fs::read_to_string(&repo_entry).wrap_err("cannot read linked workspace repository pointer")?;
        fs::canonicalize(jj_dir.join(pointer.trim_end()))
            .wrap_err("cannot resolve linked workspace repository pointer")?
    };
    let repo_has_config = seed_inspection_config(&repo_dir.join("config-id"), "repos", config_home)?;
    let workspace_has_config = seed_inspection_config(&jj_dir.join("workspace-config-id"), "workspaces", config_home)?;
    let workspace = workspace.to_str().ok_or_else(|| eyre!("non-UTF-8 workspace path"))?;
    if repo_has_config {
        prepare_jj_config_deadline(workspace, "--repo", jj, trusted_config, config_home, deadline)?;
    }
    if workspace_has_config {
        prepare_jj_config_deadline(workspace, "--workspace", jj, trusted_config, config_home, deadline)?;
    }
    Ok(())
}

fn open_cwd(root: RawFd, path: &str, source: &Path) -> Result<OwnedFd> {
    if path.contains('\0') || !Path::new(path).starts_with(source) {
        bail!("cwd is outside the protected /src workspace");
    }
    // Protocol v2 carries canonical absolute paths, not a mode-dependent namespace.
    if Path::new(path).components().any(|part| matches!(part, std::path::Component::ParentDir | std::path::Component::CurDir))
        || path.split('/').any(|part| part == "." || part == "..") || path.contains("//") || (Path::new(path) != source && path.ends_with('/')) {
        bail!("cwd must be canonical absolute");
    }
    let mut current = dup_owned(root)?;
    for component in Path::new(path).strip_prefix(source).unwrap().to_str().unwrap().split('/').filter(|part| !part.is_empty()) {
        let next = openat(Some(current.as_raw_fd()), component,
            OFlag::O_RDONLY | OFlag::O_DIRECTORY | OFlag::O_NOFOLLOW | OFlag::O_CLOEXEC,
            Mode::empty()).wrap_err_with(|| format!("invalid cwd component {component:?}"))?;
        // SAFETY: openat returned a fresh owned descriptor.
        current = unsafe { OwnedFd::from_raw_fd(next) };
    }
    Ok(current)
}

fn dup_owned(fd: RawFd) -> Result<OwnedFd> {
    // SAFETY: dup returns a fresh owned descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(dup(fd)?) })
}

#[cfg(test)]
fn jj_command() -> Command {
    Runtime::trusted().command(None)
}

fn agent_jj_command(user: &str, email: &str) -> Command {
    Runtime::trusted().command(Some((user, email)))
}

fn workspace_for(path: &Path) -> Option<&Path> {
    path.ancestors().find(|ancestor| ancestor.join(".jj").is_dir())
}

fn select_repository(request: &Request, workspaces: &[Workspace], source_root: &Path, selector: Option<&str>) -> Result<(PathBuf, bool)> {
    let invocation = Path::new(&request.cwd);
    let target = match selector {
        Some(value) => fs::canonicalize(invocation.join(value)).wrap_err("cannot resolve repository selector")?,
        None => invocation.to_path_buf(),
    };
    if !target.starts_with(source_root) { bail!("repository selector is outside /src"); }
    let workspace = workspace_for(&target).ok_or_else(|| eyre!("repository selector is not inside a Jujutsu workspace"))?;
    if !workspace.starts_with(source_root) { bail!("repository workspace is outside /src"); }
    let inspect = matches!(request.mode, RequestMode::Inspect)
        || !workspaces.iter().any(|entry| Path::new(&entry.root) == workspace);
    Ok((workspace.to_path_buf(), inspect))
}

#[cfg(test)]
fn author_update_command(user: &str, email: &str) -> Command {
    let mut command = agent_jj_command(user, email);
    command.args(["metaedit", "--update-author", "-r", "@", "--quiet"]);
    command
}


fn trusted_environment(temporary_directory: &str) -> Vec<(&str, &str)> {
    vec![
        ("PATH", "/trusted/bin"),
        ("HOME", "/nonexistent"), ("XDG_CONFIG_HOME", CONFIG_HOME),
        ("TMPDIR", temporary_directory),
        ("PAGER", "false"), ("GIT_PAGER", "false"), ("EDITOR", "false"),
        ("VISUAL", "false"), ("GIT_CONFIG_NOSYSTEM", "1"),
        ("GIT_CONFIG_GLOBAL", "/dev/null"), ("GIT_TERMINAL_PROMPT", "0"),
        ("GIT_CONFIG_COUNT", "1"), ("GIT_CONFIG_KEY_0", "core.excludesFile"),
        ("GIT_CONFIG_VALUE_0", "/trusted/gitignore"),
        ("RUST_BACKTRACE", "1"),
    ]
}

fn command_environment<'a>(
    user: &'a str,
    email: &'a str,
    temporary_directory: &'a str,
) -> Vec<(&'a str, &'a str)> {
    let mut environment = trusted_environment(temporary_directory);
    environment.extend([("JJ_USER", user), ("JJ_EMAIL", email)]);
    environment
}

fn collect<R: Read>(file: R) -> io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    file.take((MAX_OUTPUT + 1) as u64).read_to_end(&mut bytes)?;
    Ok(bytes)
}

fn kill_group(pid: u32) { let _ = kill(Pid::from_raw(-(pid as i32)), Signal::SIGKILL); }

/// Request framing requires shutdown(Write), so read EOF/RDHUP is normal.
/// Only a full Unix-stream disconnect or socket error cancels a queued request.
fn check_peer(peer: Option<&UnixStream>) -> Result<()> {
    let Some(peer) = peer else { return Ok(()); };
    let mut descriptor = nix::libc::pollfd { fd: peer.as_raw_fd(), events: 0, revents: 0 };
    loop {
        // SAFETY: descriptor is a live single pollfd, and timeout zero cannot block.
        let status = unsafe { nix::libc::poll(&mut descriptor, 1, 0) };
        if status < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted { continue; }
            return Err(error).wrap_err("cannot check request peer");
        }
        if descriptor.revents & (nix::libc::POLLHUP | nix::libc::POLLERR | nix::libc::POLLNVAL) != 0 {
            bail!("request canceled: peer disconnected before mutation");
        }
        return Ok(());
    }
}

/// Open, don't create: the launcher owns persistent inode identity across services.
fn acquire_lock(path: &Path, deadline: Instant) -> Result<File> {
    acquire_lock_checked(path, deadline, || Ok(()))
}

fn acquire_lock_checked(path: &Path, deadline: Instant, mut check_cancellation: impl FnMut() -> Result<()>) -> Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    let file = OpenOptions::new().read(true).write(true)
        .custom_flags(nix::libc::O_NOFOLLOW | nix::libc::O_CLOEXEC).open(path)
        .wrap_err("cannot open repository request lock")?;
    if !file.metadata()?.is_file() { bail!("repository request lock is not a regular file"); }
    loop {
        check_cancellation()?;
        if Instant::now() >= deadline { bail!("repository request lock deadline exceeded"); }
        #[allow(deprecated)]
        match flock(file.as_raw_fd(), FlockArg::LockExclusiveNonblock) {
            Ok(()) => {
                // Cancellation may have raced with successful flock. Do not
                // admit the request merely because ownership became available.
                check_cancellation()?;
                // Trusted JJ descendants retain the lease if the server dies.
                // Normal requests reap the whole group before dropping it.
                nix::fcntl::fcntl(file.as_raw_fd(), nix::fcntl::FcntlArg::F_SETFD(nix::fcntl::FdFlag::empty()))?;
                return Ok(file);
            },
            Err(nix::errno::Errno::EWOULDBLOCK) | Err(nix::errno::Errno::EINTR) =>
                thread::sleep(Duration::from_millis(10).min(deadline.saturating_duration_since(Instant::now()))),
            Err(error) => return Err(error).wrap_err("cannot acquire repository request lock"),
        }
    }
}

/// The caller gives every child its own session. No child may outlive ownership
/// of the request lock, even when the leader exits while descendants hold pipes.
fn run_bounded(command: &mut Command, deadline: Instant) -> Result<(i32, Vec<u8>, Vec<u8>)> {
    #[cfg(target_os = "linux")]
    nix::sys::prctl::set_child_subreaper(true).wrap_err("cannot adopt command descendants")?;
    if Instant::now() >= deadline { bail!("request deadline exceeded before starting jj"); }
    let mut child = command.stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()?;
    let pid = child.id();
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    let out_thread = thread::spawn(move || collect(stdout));
    let err_thread = thread::spawn(move || collect(stderr));
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status.code().unwrap_or(128)),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(10)),
            Ok(None) => { kill_group(pid); let _ = child.wait(); break Ok(124); }
            Err(error) => { kill_group(pid); let _ = child.wait(); break Err(error); }
        }
    };
    kill_group(pid);
    // Adopted descendants remain in the child's process group. Wait until all
    // are dead and reaped before the caller can drop its request lock.
    #[cfg(target_os = "linux")]
    loop {
        match nix::sys::wait::waitpid(Pid::from_raw(-(pid as i32)), None) {
            Ok(_) | Err(nix::errno::Errno::EINTR) => continue,
            Err(nix::errno::Errno::ECHILD) => break,
            Err(error) => return Err(error).wrap_err("cannot reap command descendants"),
        }
    }
    let stdout = out_thread.join().ok().and_then(Result::ok).unwrap_or_default();
    let stderr = err_thread.join().ok().and_then(Result::ok).unwrap_or_default();
    Ok((status?, stdout, stderr))
}

fn limits_and_cwd(fd: RawFd) -> impl FnMut() -> io::Result<()> {
    let parent = std::process::id();
    move || {
        let io_error = |error: nix::errno::Errno| io::Error::from_raw_os_error(error as i32);
        #[cfg(target_os = "linux")]
        {
            nix::sys::prctl::set_pdeathsig(Signal::SIGKILL).map_err(io_error)?;
            if nix::unistd::getppid().as_raw() != parent as i32 { return Err(io::Error::from_raw_os_error(nix::libc::ESRCH)); }
        }
        setsid().map_err(io_error)?;
        fchdir(fd).map_err(io_error)?;
        let limits = [
            (Resource::RLIMIT_CPU, 120), (Resource::RLIMIT_FSIZE, 64 << 20),
            (Resource::RLIMIT_NOFILE, 64),
        ];
        for (resource, value) in limits {
            setrlimit(resource, value, value).map_err(io_error)?;
        }
        Ok(())
    }
}

struct Runtime<'a> {
    source: &'a Path,
    jj: &'a Path,
    config: &'a Path,
    config_home: &'a Path,
    #[cfg(test)]
    after_author_update: Option<&'a dyn Fn()>,
}

impl Runtime<'_> {
    fn trusted() -> Runtime<'static> {
        Runtime { source: Path::new("/src"), jj: Path::new("/trusted/bin/jj"), config: Path::new(TRUSTED_JJ_CONFIG), config_home: Path::new(CONFIG_HOME),
            #[cfg(test)]
            after_author_update: None,
        }
    }

    fn command(&self, identity: Option<(&str, &str)>) -> Command {
        let mut command = Command::new(self.jj);
        command.args(["--no-pager", "--color=never", "--config-file"]).arg(self.config);
        if let Some((user, email)) = identity {
            command.arg("--config").arg(format!("user.name={user}"))
                .arg("--config").arg(format!("user.email={email}"));
        }
        command
    }
}

fn execute(
    request: &Request,
    command_policy: &policy::Policy,
    root: RawFd,
    workspaces: &[Workspace],
    temporary_directory: &str,
    peer: Option<&UnixStream>,
) -> Response {
    execute_with_runtime(request, command_policy, root, workspaces, temporary_directory, &Runtime::trusted(), Instant::now() + TIMEOUT, peer)
}

fn execute_with_runtime(
    request: &Request, command_policy: &policy::Policy, root: RawFd,
    workspaces: &[Workspace], temporary_directory: &str, runtime: &Runtime<'_>, deadline: Instant, peer: Option<&UnixStream>,
) -> Response {
    let failure = |message: String| Response { version: 2, exit: 2, stdout: String::new(), stderr: format!("jj proxy: {message}\n") };
    if request.version != 2 { return failure("unsupported protocol version".into()); }
    let valid_identity = |value: &str, limit: usize| {
        !value.is_empty() && value.len() <= limit && !value.chars().any(char::is_control)
    };
    let (user, email) = match (&request.user, &request.email) {
        (Some(user), Some(email))
            if valid_identity(user, 128) && valid_identity(email, 254) =>
        {
            (user.as_str(), email.as_str())
        }
        (None, None) => ("Codex", "breq@jyn.dev"),
        _ => return failure("invalid agent identity".into()),
    };
    if matches!(request.mode, RequestMode::Inspect) && request.agent_split.is_some() {
        return failure("agent split is not allowed in inspection mode".into());
    }
    let (repository_selector, argv) = if request.agent_split.is_some() {
        (None, Vec::new())
    } else {
        match policy::extract_repository(&request.argv) {
            Ok(parsed) => parsed,
            Err(error) => return failure(error.to_string()),
        }
    };
    if let Some(split) = &request.agent_split {
        if !request.argv.is_empty() {
            return failure("agent split cannot include Jujutsu arguments".into());
        }
        if split.patch.is_empty() || split.patch.len() > MAX_REQUEST / 2
            || split.message.is_empty() || split.message.len() > 4096
            || split.revision.is_empty() || split.revision.len() > 4096
            || split.message.contains('\0') || split.revision.contains('\0')
        {
            return failure("invalid agent split request".into());
        }
    }
    let cwd = match open_cwd(root, &request.cwd, runtime.source) { Ok(fd) => fd, Err(error) => return failure(error.to_string()) };
    if request.argv.as_slice() == [":ready"] && request.agent_split.is_none() {
        return Response { version: 2, exit: 0, stdout: String::new(), stderr: String::new() };
    }
    let (workspace, inspect) = match select_repository(request, workspaces, runtime.source, repository_selector.as_deref()) {
        Ok(selection) => selection,
        Err(error) => return failure(error.to_string()),
    };
    let decision = if request.agent_split.is_none() {
        let validation = if inspect { command_policy.validate_inspect(&argv) } else { command_policy.validate(&argv) };
        match validation {
            Ok(decision) => Some(decision),
            Err(error) => return failure(error.to_string()),
        }
    } else { None };
    let argv = decision.as_ref().map_or(argv, |decision| decision.argv.clone());
    let updates_author = request.agent_split.as_ref().is_some_and(|split| split.revision == "@")
        || decision.is_some_and(|decision| decision.updates_author);
    if inspect {
        if request.agent_split.is_some() { return failure("agent split is not allowed in inspection mode".into()); }
        if let Err(error) = prepare_inspection_config_deadline(&workspace, runtime.jj, runtime.config, runtime.config_home, deadline) {
            return failure(format!("cannot prepare inspection repository config: {error}"));
        }
    }

    // An owned descriptor covers every mutating action, including commands
    // without an author hook. Never acquire a second repository lock.
    let _request_lock = if inspect { None } else {
        let authority = workspaces.iter().find(|entry| Path::new(&entry.root) == workspace).unwrap();
        match acquire_lock_checked(Path::new(&authority.lock), deadline, || check_peer(peer)) {
            Ok(lock) => Some(lock), Err(error) => return failure(error.to_string()),
        }
    };
    if !inspect {
        if let Err(error) = check_peer(peer) { return failure(error.to_string()); }
    }
    if let Some(split) = &request.agent_split {
        if let Err(error) = fs::write(runtime.config_home.join("agent-split.patch"), &split.patch) {
            return failure(format!("could not stage split patch: {error}"));
        }
    }
    if !inspect && updates_author {
        if let Err(error) = check_peer(peer) { return failure(error.to_string()); }
        let mut update = runtime.command(Some((user, email)));
        update.args(["metaedit", "--update-author", "-r", "@", "--quiet"]);
        update.arg("--repository").arg(&workspace);
        update.env_clear().envs(command_environment(user, email, temporary_directory))
            .env("XDG_CONFIG_HOME", runtime.config_home)
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        // Match the local wrapper's best-effort update: failure must not block the
        // requested command, but successful commits must not inherit jyn's author.
        unsafe { update.pre_exec(limits_and_cwd(cwd.as_raw_fd())); }
        if let Err(error) = check_peer(peer) { return failure(error.to_string()); }
        match run_bounded(&mut update, deadline) {
            Ok((124, _, _)) => return Response { version: 2, exit: 124, stdout: String::new(), stderr: "jj proxy: author update deadline exceeded\n".into() },
            Err(error) if Instant::now() >= deadline => return failure(format!("author update deadline exceeded: {error}")),
            _ => {}
        }
        #[cfg(test)]
        if let Some(callback) = runtime.after_author_update { callback(); }
    }

    let mut command = if inspect {
        let mut command = Command::new(TRUSTED_PROXY);
        command.args(["inspect-jj", user, email]);
        command
    } else {
        runtime.command(Some((user, email)))
    };
    if repository_selector.is_some() || request.agent_split.is_some() {
        command.arg("--repository").arg(&workspace);
    }
    if let Some(split) = &request.agent_split {
        command.args([
            "split", "--tool", "agent-split", &format!("--message={}", split.message),
            "-r", split.revision.as_str(),
        ]);
    } else {
        command.args(&argv);
    }
    command.env_clear().envs(command_environment(user, email, temporary_directory))
        .env("XDG_CONFIG_HOME", runtime.config_home)
        .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    if inspect {
        for key in ["JJ_PROXY_REPO", "JJ_PROXY_WORKSPACES"] {
            if let Ok(value) = env::var(key) { command.env(key, value); }
        }
    }
    // SAFETY: the callback captures only the copied descriptor number and
    // performs only async-signal-safe process-control syscalls (including
    // Linux prctl for parent-death signalling). No proxy reader threads exist while `spawn` forks, and `cwd`
    // remains alive until after `spawn` returns, so the descriptor is valid in
    // the child. The callback does not allocate, lock, or access shared state.
    unsafe { command.pre_exec(limits_and_cwd(cwd.as_raw_fd())); }
    if !inspect && !updates_author {
        if let Err(error) = check_peer(peer) { return failure(error.to_string()); }
    }
    let output = match run_bounded(&mut command, deadline) {
        Ok(output) => output,
        Err(error) => return failure(format!("could not execute jj: {error}")),
    };
    let (status, stdout, stderr) = output;
    if stdout.len() > MAX_OUTPUT || stderr.len() > MAX_OUTPUT {
        return failure("output limit exceeded".into());
    }
    if status == 0 && !inspect && updates_author {
        let mut reset = runtime.command(None);
        reset.args(["metaedit", "--update-author", "-r", "@", "--quiet"]);
        reset.arg("--repository").arg(&workspace);
        reset.env_clear().envs(trusted_environment(temporary_directory))
            .env("XDG_CONFIG_HOME", runtime.config_home)
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        // A successful agent command may create or snapshot a new working-copy
        // commit. Return its author to the repository identity so later human
        // work is not attributed to the agent that happened to create `@`.
        unsafe { reset.pre_exec(limits_and_cwd(cwd.as_raw_fd())); }
        match run_bounded(&mut reset, deadline) {
            Ok((124, _, _)) => return Response { version: 2, exit: 124, stdout: String::from_utf8_lossy(&stdout).into_owned(), stderr: "jj proxy: author reset deadline exceeded\n".into() },
            Err(error) if Instant::now() >= deadline => return failure(format!("author reset deadline exceeded: {error}")),
            _ => {}
        }
    }
    Response { version: 2, exit: status, stdout: String::from_utf8_lossy(&stdout).into_owned(), stderr: String::from_utf8_lossy(&stderr).into_owned() }
}

fn startup_timeout(value: Option<&str>) -> Result<Duration> {
    let Some(value) = value else { return Ok(TIMEOUT); };
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        bail!("JJ_PROXY_STARTUP_TIMEOUT_SECS must be a positive integer");
    }
    let seconds: u64 = value.parse().wrap_err("invalid JJ_PROXY_STARTUP_TIMEOUT_SECS")?;
    if seconds == 0 { bail!("JJ_PROXY_STARTUP_TIMEOUT_SECS must be a positive integer"); }
    Ok(Duration::from_secs(seconds))
}

fn serve() -> Result<()> {
    let command_policy = policy::Policy::load(Path::new(TRUSTED_COMMAND_POLICY))?;
    // The server retains its mutation policy; inspection children add a
    // read-only policy before executing Jujutsu.
    let workspaces = workspaces::load()?;
    let source_root = File::open("/src").wrap_err("cannot open source")?;
    fs::create_dir_all(CONFIG_HOME).wrap_err("cannot create secure config directory")?;
    fs::set_permissions(CONFIG_HOME, fs::Permissions::from_mode(0o700)).wrap_err("cannot secure config directory")?;
    fs::create_dir_all(TEMP_HOME).wrap_err("cannot create Jujutsu temporary directory")?;
    fs::set_permissions(TEMP_HOME, fs::Permissions::from_mode(0o700))
        .wrap_err("cannot secure Jujutsu temporary directory")?;
    execution_policy::install_workspaces(&workspaces, true)?;
    let startup_budget = match env::var("JJ_PROXY_STARTUP_TIMEOUT_SECS") {
        Ok(value) => startup_timeout(Some(&value))?,
        Err(env::VarError::NotPresent) => startup_timeout(None)?,
        Err(error) => return Err(error).wrap_err("invalid JJ_PROXY_STARTUP_TIMEOUT_SECS"),
    };
    // One startup budget covers all stores, not one full timeout per root.
    let deadline = Instant::now().checked_add(startup_budget).ok_or_else(|| eyre!("startup deadline is out of range"))?;
    for workspace in &workspaces {
        let _lock = acquire_lock(Path::new(&workspace.lock), deadline)?;
        prepare_jj_config_deadline(&workspace.root, "--repo", Path::new("/trusted/bin/jj"), Path::new(TRUSTED_JJ_CONFIG), Path::new(CONFIG_HOME), deadline)?;
        prepare_jj_config_deadline(&workspace.root, "--workspace", Path::new("/trusted/bin/jj"), Path::new(TRUSTED_JJ_CONFIG), Path::new(CONFIG_HOME), deadline)?;
    }
    let socket = socket_path();
    let _ = fs::remove_file(&socket);
    let listener = UnixListener::bind(&socket).wrap_err("cannot bind proxy socket")?;
    fs::set_permissions(&socket, fs::Permissions::from_mode(0o666)).wrap_err("cannot set proxy socket permissions")?;
    for connection in listener.incoming() {
        let mut stream = match connection { Ok(stream) => stream, Err(error) => { eprintln!("jj proxy: accept: {error}"); continue; } };
        let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
        let response = match read_frame(&mut stream, MAX_REQUEST)
            .and_then(|bytes| { require_eof(&mut stream)?; Ok(bytes) })
            .and_then(|bytes| serde_json::from_slice::<Request>(&bytes).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))) {
            Ok(request) => execute(
                &request,
                &command_policy,
                source_root.as_raw_fd(),
                &workspaces,
                TEMP_HOME,
                Some(&stream),
            ),
            Err(error) => Response { version: 2, exit: 2, stdout: String::new(), stderr: format!("jj proxy: invalid request: {error}\n") },
        };
        if let Ok(body) = serde_json::to_vec(&response) { let _ = write_frame(&mut stream, &body); }
    }
    Ok(())
}

fn client(args: Vec<String>) -> Result<i32> {
    let cwd = fs::canonicalize(env::current_dir().wrap_err("cannot read current directory")?).wrap_err("cannot resolve current directory")?;
    if !cwd.starts_with("/src") { bail!("current directory is outside /src"); }
    let inspect = env::var_os("JJ_PROXY_INSPECT").is_some();
    let cwd = cwd.to_str().ok_or_else(|| eyre!("non-UTF-8 current directory"))?.to_owned();
    let request = Request {
        version: 2,
        mode: if inspect { RequestMode::Inspect } else { RequestMode::Mutate },
        cwd,
        argv: args,
        agent_split: None,
        user: env::var("JJ_USER").ok(),
        email: env::var("JJ_EMAIL").ok(),
    };
    let body = serde_json::to_vec(&request).wrap_err("cannot encode request")?;
    let proxy_dir = env::var("SANDBOX_PROXY_DIR").wrap_err("sandbox proxy directory is not configured")?;
    let configured_socket = socket_path();
    let socket = if Path::new(&configured_socket).exists() {
        configured_socket
    } else {
        format!("{proxy_dir}/jj/socket")
    };
    let mut stream = UnixStream::connect(socket).wrap_err("proxy unavailable")?;
    stream.set_read_timeout(Some(TIMEOUT + Duration::from_secs(5))).wrap_err("cannot configure proxy socket")?;
    stream.set_write_timeout(Some(Duration::from_secs(5))).wrap_err("cannot configure proxy socket")?;
    write_frame(&mut stream, &body).wrap_err("cannot send proxy request")?;
    stream.shutdown(Shutdown::Write).wrap_err("cannot finish proxy request")?;
    let response: Response = serde_json::from_slice(&read_frame(&mut stream, MAX_OUTPUT * 3).wrap_err("cannot read proxy response")?).wrap_err("cannot decode proxy response")?;
    if response.version != 2 { bail!("unsupported response version"); }
    print!("{}", response.stdout); eprint!("{}", response.stderr);
    Ok(response.exit)
}

fn forward() -> Result<i32> {
    let configured_socket = socket_path();
    let socket = if Path::new(&configured_socket).exists() {
        configured_socket
    } else {
        DEFAULT_SOCKET.to_owned()
    };
    let mut stream = UnixStream::connect(socket).wrap_err("proxy unavailable")?;
    let stdin = io::stdin();
    let mut input = stdin.lock();
    io::copy(&mut input, &mut stream).wrap_err("cannot forward proxy request")?;
    stream.shutdown(Shutdown::Write).wrap_err("cannot finish proxy request")?;
    let stdout = io::stdout();
    let mut output = stdout.lock();
    io::copy(&mut stream, &mut output).wrap_err("cannot forward proxy response")?;
    Ok(0)
}

fn inspect_jj(args: &[String]) -> Result<i32> {
    if args.len() < 3 {
        bail!("invalid inspection invocation");
    }
    let workspaces = workspaces::load()?;
    execution_policy::install_workspaces(&workspaces, false)?;
    let mut command = agent_jj_command(&args[0], &args[1]);
    command.arg("--ignore-working-copy").args(&args[2..]);
    Err(command.exec().into())
}

fn main() {
    color_eyre::install().expect("could not install error reporter");
    let executable = env::args().next().unwrap_or_default();
    let mut args: Vec<String> = env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("reject-editor") {
        eprintln!("jj proxy: interactive editors are disabled; pass a message with -m");
        std::process::exit(1);
    }
    let result = if executable.ends_with("sandbox-proxy-forward") {
        forward()
    } else if args.first().map(String::as_str) == Some("serve") {
        serve().map(|_| 0)
    } else if args.first().map(String::as_str) == Some("inspect-jj") {
        inspect_jj(&args[1..])
    } else {
        client(std::mem::take(&mut args))
    };
    match result { Ok(code) => std::process::exit(code), Err(error) => { eprintln!("jj proxy: {error:?}"); std::process::exit(125); } }
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::path::PathBuf;

    #[test]
    fn accepts_frame_followed_by_eof() {
        let (mut sender, mut receiver) = UnixStream::pair().unwrap();
        write_frame(&mut sender, b"request").unwrap();
        sender.shutdown(Shutdown::Write).unwrap();
        assert_eq!(b"request", read_frame(&mut receiver, 32).unwrap().as_slice());
        require_eof(&mut receiver).unwrap();
    }

    #[test]
    fn rejects_trailing_request_bytes() {
        let (mut sender, mut receiver) = UnixStream::pair().unwrap();
        write_frame(&mut sender, b"request").unwrap();
        sender.write_all(b"trailing").unwrap();
        sender.shutdown(Shutdown::Write).unwrap();
        read_frame(&mut receiver, 32).unwrap();
        assert_eq!(io::ErrorKind::InvalidData, require_eof(&mut receiver).unwrap_err().kind());
    }

    #[test]
    fn jj_command_discovers_the_workspace_and_applies_trusted_config_at_cli_precedence() {
        let command = jj_command();
        let args: Vec<_> = command.get_args().collect();
        assert!(!args.iter().any(|arg| *arg == "--repository"));
        assert!(args.windows(2).any(|args| {
            args[0] == "--config-file" && args[1] == TRUSTED_JJ_CONFIG
        }));
    }

    #[test]
    fn agent_command_overrides_the_trusted_human_identity() {
        let command = agent_jj_command("Pi gpt-test", "pi@example.test");
        let args: Vec<_> = command.get_args().collect();
        assert!(args.windows(2).any(|args| {
            args[0] == "--config" && args[1] == "user.name=Pi gpt-test"
        }));
        assert!(args.windows(2).any(|args| {
            args[0] == "--config" && args[1] == "user.email=pi@example.test"
        }));
    }

    #[test]
    fn inspection_prepares_config_without_changing_repository_metadata() {
        let jj = env::var_os("JJ_PROXY_TEST_JJ").or_else(|| env::var_os("DOTFILES_TEST_JJ_REAL")).map(PathBuf::from).or_else(|| {
            ["/trusted/bin/jj", "/opt/agent-tools/bin/jj", "/opt/homebrew/bin/jj"]
                .into_iter().map(PathBuf::from).find(|path| {
                    fs::symlink_metadata(path).is_ok_and(|metadata| metadata.file_type().is_file())
                })
        });
        let Some(jj) = jj else {
            eprintln!("skipping inspection config test: set JJ_PROXY_TEST_JJ to a real jj binary");
            return;
        };
        let child_root = env::var_os("JJ_PROXY_INSPECTION_TEST_ROOT");
        if child_root.is_none() {
            let root = env::temp_dir().join(format!("jj-proxy-inspect-config-{}", std::process::id()));
            fs::create_dir(&root).unwrap();
            let root = fs::canonicalize(root).unwrap();
            // Configuration helpers also spawn JJ. Isolate the whole case
            // without changing the working directory of parallel tests.
            let output = Command::new(env::current_exe().unwrap())
                .args(["--exact", "tests::inspection_prepares_config_without_changing_repository_metadata", "--nocapture"])
                .current_dir(&root)
                .env("JJ_PROXY_INSPECTION_TEST_ROOT", &root)
                .env("JJ_PROXY_TEST_JJ", &jj)
                .output().unwrap();
            assert!(output.status.success(), "inspection child failed:\n{}\n{}",
                String::from_utf8_lossy(&output.stdout), String::from_utf8_lossy(&output.stderr));
            assert!(root.join("linked/.jj/repo").is_file(), "inspection child did not run the linked-workspace case");
            fs::remove_dir_all(root).unwrap();
            return;
        }
        let root = PathBuf::from(child_root.unwrap());
        assert_eq!(root, env::current_dir().unwrap());
        let repo = root.join("repo");
        let original_home = root.join("original-config");
        let inspection_home = root.join("inspection-config");
        let trusted_config = root.join("trusted.toml");
        fs::write(&trusted_config, include_str!("../jj.toml")).unwrap();
        let output = Command::new(&jj).args(["git", "init"]).arg(&repo)
            .env_clear().env("HOME", "/nonexistent").env("XDG_CONFIG_HOME", &original_home)
            .output().unwrap();
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        prepare_jj_config(repo.to_str().unwrap(), "--repo", &jj, &trusted_config, &original_home).unwrap();
        let config_id = repo.join(".jj/repo/config-id");
        let before = fs::read(&config_id).unwrap();
        fs::set_permissions(config_id.parent().unwrap(), fs::Permissions::from_mode(0o500)).unwrap();
        prepare_inspection_config(&repo, &jj, &trusted_config, &inspection_home).unwrap();
        assert_eq!(before, fs::read(&config_id).unwrap());
        let metadata = inspection_home.join("jj/repos").join(String::from_utf8(before).unwrap()).join("metadata.binpb");
        assert!(!fs::read(metadata).unwrap().is_empty());
        fs::set_permissions(&inspection_home, fs::Permissions::from_mode(0o500)).unwrap();
        let output = Command::new(&jj).args(["--config-file"]).arg(&trusted_config)
            .args(["--repository"]).arg(&repo).args(["--ignore-working-copy", "status"])
            .env_clear().env("HOME", "/nonexistent").env("XDG_CONFIG_HOME", &inspection_home)
            .output().unwrap();
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        fs::set_permissions(&inspection_home, fs::Permissions::from_mode(0o700)).unwrap();
        fs::set_permissions(config_id.parent().unwrap(), fs::Permissions::from_mode(0o700)).unwrap();
        let linked = root.join("linked");
        let output = Command::new(&jj).args(["--repository"]).arg(&repo)
            .args(["workspace", "add"]).arg(&linked)
            .env_clear().env("HOME", "/nonexistent").env("XDG_CONFIG_HOME", &original_home)
            .output().unwrap();
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        assert!(linked.join(".jj/repo").is_file());
        let linked_home = root.join("linked-config");
        fs::set_permissions(config_id.parent().unwrap(), fs::Permissions::from_mode(0o500)).unwrap();
        prepare_inspection_config(&linked, &jj, &trusted_config, &linked_home).unwrap();
        let output = Command::new(&jj).args(["--config-file"]).arg(&trusted_config)
            .args(["--repository"]).arg(&linked).args(["--ignore-working-copy", "status"])
            .env_clear().env("HOME", "/nonexistent").env("XDG_CONFIG_HOME", &linked_home)
            .output().unwrap();
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        fs::set_permissions(config_id.parent().unwrap(), fs::Permissions::from_mode(0o700)).unwrap();
    }

    #[test]
    fn repository_selector_grants_writes_only_to_the_selected_workspace() {
        let root = env::temp_dir().join(format!("jj-proxy-selector-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let source = root.join("src");
        let selected = source.join("selected");
        let other = source.join("other");
        let outside = root.join("outside");
        for path in [&selected, &other, &outside] { fs::create_dir_all(path.join(".jj")).unwrap(); }
        let source = fs::canonicalize(source).unwrap();
        let selected = source.join("selected");
        let other = source.join("other");
        fs::create_dir_all(selected.join("nested")).unwrap();
        std::os::unix::fs::symlink(&outside, selected.join("nested/escape")).unwrap();
        let mut request = Request {
            version: 2, mode: RequestMode::Mutate, cwd: selected.join("nested").to_str().unwrap().into(),
            argv: vec!["status".into()], agent_split: None, user: None, email: None,
        };
        let authority = vec![Workspace { root: selected.to_str().unwrap().into(), git_dir: String::new(), common_dir: String::new(), jj_repo: String::new(), lock: String::new() }];
        assert_eq!((selected.clone(), false), select_repository(&request, &authority, &source, Some(".")).unwrap());
        assert_eq!((other.clone(), true), select_repository(&request, &authority, &source, Some("../../other")).unwrap());
        assert!(select_repository(&request, &authority, &source, Some(outside.to_str().unwrap())).is_err());
        assert!(select_repository(&request, &authority, &source, Some("escape")).is_err());
        let mut both = authority.clone();
        both.push(Workspace { root: other.to_str().unwrap().into(), ..authority[0].clone() });
        assert_eq!((other.clone(), false), select_repository(&request, &both, &source, Some("../../other")).unwrap());
        request.mode = RequestMode::Inspect;
        assert_eq!((other.clone(), true), select_repository(&request, &both, &source, Some("../../other")).unwrap());
        request.cwd = other.to_string_lossy().into_owned();
        assert_eq!((selected, true), select_repository(&request, &authority, &source, Some("../selected")).unwrap());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn trusted_config_preserves_the_effective_security_settings() {
        let config = include_str!("../jj.toml");
        for setting in [
            r#"editor = ["/trusted/bin/jj-proxy", "reject-editor"]"#,
            r#"diff-editor = ":builtin""#,
            r#"merge-editor = ":builtin""#,
            r#"diff-formatter = ":git""#,
            r#"behavior = "drop""#,
        ] {
            assert!(
                config.lines().any(|line| line == setting),
                "trusted config is missing {setting:?}",
            );
        }
    }

    #[test]
    fn jj_uses_the_private_proxy_volume_for_temporary_files() {
        let environment: std::collections::HashMap<_, _> =
            command_environment("agent", "agent@example.test", TEMP_HOME)
                .into_iter()
                .collect();
        assert_eq!(Some(&TEMP_HOME), environment.get("TMPDIR"));
        assert!(!environment.contains_key("JJ_CONFIG"));
        assert_eq!(Some(&"agent"), environment.get("JJ_USER"));

        let trusted: std::collections::HashMap<_, _> =
            trusted_environment(TEMP_HOME).into_iter().collect();
        assert!(!trusted.contains_key("JJ_USER"));
        assert!(!trusted.contains_key("JJ_EMAIL"));
    }

    #[test]
    fn command_policy_declares_author_update_effects() {
        let policy = policy::Policy::load(Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/policy.toml"))).unwrap();
        assert!(policy.validate(&["commit".into()]).unwrap().updates_author);
        assert!(policy.validate(&["split".into()]).unwrap().updates_author);
        assert!(!policy.validate(&["status".into()]).unwrap().updates_author);

        let command = author_update_command("agent", "agent@example.test");
        let args: Vec<_> = command
            .get_args()
            .map(|arg| arg.to_string_lossy().into_owned())
            .collect();
        assert!(args.ends_with(&[
            "metaedit".into(),
            "--update-author".into(),
            "-r".into(),
            "@".into(),
            "--quiet".into(),
        ]));
    }

    #[test]
    fn inspection_rejects_agent_split_before_staging_a_patch() {
        let policy = policy::Policy::load(Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/policy.toml"))).unwrap();
        let root = File::open("/tmp").unwrap();
        let request = Request {
            version: 2,
            mode: RequestMode::Inspect,
            cwd: "/src/other".into(),
            argv: Vec::new(),
            agent_split: Some(AgentSplit {
                patch: "patch".into(),
                message: "message".into(),
                revision: "@".into(),
            }),
            user: None,
            email: None,
        };
        let response = execute(&request, &policy, root.as_raw_fd(), &[], "/tmp", None);
        assert_eq!(2, response.exit);
        assert!(response.stderr.contains("agent split is not allowed"));
    }

    fn real_jj() -> Option<PathBuf> {
        env::var_os("JJ_PROXY_TEST_JJ").or_else(|| env::var_os("DOTFILES_TEST_JJ_REAL"))
            .map(PathBuf::from)
    }

    fn native(jj: &Path, root: &Path, args: &[&str]) -> String {
        let output = Command::new(jj).args(args).current_dir(env::temp_dir())
            .env_clear().env("HOME", root).env("XDG_CONFIG_HOME", root.join("config"))
            .output().unwrap();
        assert!(output.status.success(), "{args:?}: {}", String::from_utf8_lossy(&output.stderr));
        String::from_utf8(output.stdout).unwrap()
    }

    fn test_authority(root: &Path, name: &str) -> Workspace {
        let repo = root.join(name);
        Workspace { root: repo.to_str().unwrap().into(), git_dir: repo.join(".jj/repo/store/git").to_str().unwrap().into(),
            common_dir: repo.join(".jj/repo/store/git").to_str().unwrap().into(),
            jj_repo: repo.join(".jj/repo").to_str().unwrap().into(), lock: root.join(format!("{name}.lock")).to_str().unwrap().into() }
    }

    /// Two independent request-owner processes exercise the real orchestration,
    /// real JJ attribution and the same flock inode. Container mount enforcement
    /// remains the container suite's responsibility.
    #[test]
    fn real_jj_cross_workspace_and_cross_process_sequences() {
        let Some(jj) = real_jj() else { eprintln!("SKIP real JJ sequence: no JJ_PROXY_TEST_JJ or DOTFILES_TEST_JJ_REAL"); return; };
        let child = env::var("JJ_PROXY_SEQUENCE_CHILD").ok();
        let root = if let Some(path) = env::var_os("JJ_PROXY_SEQUENCE_ROOT") { PathBuf::from(path) } else {
            env::temp_dir().join(format!("jj-proxy-sequence-{}", std::process::id()))
        };
        if let Some(role) = child {
            let workspaces = vec![test_authority(&root, "project"), test_authority(&root, "relocated")];
            let policy = policy::Policy::load(Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/policy.toml"))).unwrap();
            let config = root.join("trusted.toml");
            let config_home = root.join("config");
            let pause = || {
                fs::write(root.join("paused"), "author hook complete").unwrap();
                while !root.join("release").exists() { thread::sleep(Duration::from_millis(10)); }
            };
            let runtime = Runtime { source: &root, jj: &jj, config: &config, config_home: &config_home,
                after_author_update: if role == "A" { Some(&pause) } else { None } };
            let argv: Vec<String> = match role.as_str() {
                "A" => ["-R", "../relocated", "commit", "root:selected", "-m", "A commit"].into_iter().map(str::to_owned).collect(),
                "B" => ["-R", "../relocated", "commit", "root:second", "-m", "B commit"].into_iter().map(str::to_owned).collect(),
                "new" => ["-R", "../relocated", "bookmark", "create", "nonhook"].into_iter().map(str::to_owned).collect(),
                "independent" => ["new", "-m", "independent"].into_iter().map(str::to_owned).collect(),
                _ => panic!("unknown role"),
            };
            let request = Request { version: 2, mode: RequestMode::Mutate, cwd: root.join("project").to_str().unwrap().into(),
                argv, agent_split: None, user: Some(format!("Agent {role}")), email: Some(format!("{role}@example.test")) };
            let source = File::open(&root).unwrap();
            let response = execute_with_runtime(&request, &policy, source.as_raw_fd(), &workspaces,
                root.to_str().unwrap(), &runtime, Instant::now() + Duration::from_secs(20), None);
            assert_eq!(0, response.exit, "{}", response.stderr);
            fs::write(root.join(format!("done-{role}")), "done").unwrap();
            return;
        }
        fs::create_dir_all(&root).unwrap();
        let root = fs::canonicalize(root).unwrap();
        fs::write(root.join("trusted.toml"), include_str!("../jj.toml")).unwrap();
        for name in ["project", "relocated"] {
            native(&jj, &root, &["git", "init", root.join(name).to_str().unwrap()]);
            fs::write(root.join(format!("{name}.lock")), "").unwrap();
        }
        for name in ["selected", "second", "unrelated"] { fs::write(root.join("relocated").join(name), name).unwrap(); }
        fs::write(root.join("project/project-only"), "project").unwrap();
        let workspaces = vec![test_authority(&root, "project"), test_authority(&root, "relocated")];
        let source = File::open(&root).unwrap();
        let config = root.join("trusted.toml");
        let config_home = root.join("config");
        fs::create_dir_all(&config_home).unwrap();
        let runtime = Runtime { source: &root, jj: &jj, config: &config, config_home: &config_home, after_author_update: None };
        let policy = policy::Policy::load(Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/policy.toml"))).unwrap();
        let request_for = |cwd: &str, args: &[&str]| Request { version: 2, mode: RequestMode::Mutate,
            cwd: root.join(cwd).to_str().unwrap().into(), argv: args.iter().map(|arg| (*arg).into()).collect(),
            agent_split: None, user: Some("Agent selector".into()), email: Some("selector@example.test".into()) };
        // Native JJ interprets a plain fileset from the invocation cwd, not -R.
        // Preserve that error rather than silently committing target-relative files.
        let relative = request_for("project", &["-R", "../relocated", "commit", "selected", "-m", "must not commit"]);
        let native_failure = Command::new(&jj).args(["--no-pager", "--color=never", "--config-file"])
            .arg(&config).args(&relative.argv).current_dir(root.join("project"))
            .env_clear().env("HOME", &root).env("XDG_CONFIG_HOME", &config_home).output().unwrap();
        let proxy_failure = execute_with_runtime(&relative, &policy, source.as_raw_fd(), &workspaces,
            root.to_str().unwrap(), &runtime, Instant::now() + Duration::from_secs(5), None);
        assert!(!native_failure.status.success(), "native JJ unexpectedly accepted invocation-relative fileset");
        assert_ne!(0, proxy_failure.exit);
        assert_eq!(String::from_utf8(native_failure.stderr).unwrap(), proxy_failure.stderr);
        // Reverse direction, absolute selector, relocated invocation cwd. Hooks
        // must not snapshot or reattribute the invoking dotfiles workspace.
        let relocated_before = native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]);
        let reverse = request_for("relocated", &["-R", root.join("project").to_str().unwrap(), "commit", "root:project-only", "-m", "reverse selector"]);
        let response = execute_with_runtime(&reverse, &policy, source.as_raw_fd(), &workspaces,
            root.to_str().unwrap(), &runtime, Instant::now() + Duration::from_secs(5), None);
        assert_eq!(0, response.exit, "{}", response.stderr);
        assert_eq!(relocated_before, native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]));
        let launch = |role: &str| Command::new(env::current_exe().unwrap())
            .args(["--exact", "tests::real_jj_cross_workspace_and_cross_process_sequences", "--nocapture"])
            .env("JJ_PROXY_SEQUENCE_CHILD", role).env("JJ_PROXY_SEQUENCE_ROOT", &root)
            .env("JJ_PROXY_TEST_JJ", &jj).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().unwrap();
        let project_before = native(&jj, &root, &["-R", root.join("project").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]);
        let a = launch("A");
        let until = Instant::now() + Duration::from_secs(10);
        while !root.join("paused").exists() { assert!(Instant::now() < until, "A did not reach post-prehook state"); thread::sleep(Duration::from_millis(10)); }
        let target_before = native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]);
        let waiting = request_for("project", &["-R", "../relocated", "commit", "root:second", "-m", "timed out waiter"]);
        let started = Instant::now();
        let timeout = execute_with_runtime(&waiting, &policy, source.as_raw_fd(), &workspaces,
            root.to_str().unwrap(), &runtime, started + Duration::from_millis(60), None);
        assert_ne!(0, timeout.exit);
        assert!(timeout.stderr.contains("lock deadline exceeded"), "{}", timeout.stderr);
        assert!(started.elapsed() < Duration::from_secs(1));
        assert_eq!(target_before, native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]), "timed-out waiter ran a prehook or command");
        let mut b = launch("B");
        let mut nonhook = launch("new");
        thread::sleep(Duration::from_millis(150));
        assert!(b.try_wait().unwrap().is_none(), "B entered while A held the sequence");
        assert!(nonhook.try_wait().unwrap().is_none(), "non-hook mutation entered while A held the sequence");
        assert_eq!(target_before, native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]));
        assert_eq!(project_before, native(&jj, &root, &["-R", root.join("project").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]), "target hooks mutated the invocation repository");
        let independent = launch("independent").wait_with_output().unwrap();
        assert!(independent.status.success(), "independent repository blocked: {}", String::from_utf8_lossy(&independent.stderr));
        // Independent mutation intentionally changes project history; hooks for
        // A/B must not do so. Compare before starting that explicit mutation.
        assert_ne!(project_before, native(&jj, &root, &["-R", root.join("project").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]));
        fs::write(root.join("release"), "go").unwrap();
        for owner in [a, b, nonhook] {
            let output = owner.wait_with_output().unwrap();
            assert!(output.status.success(), "request failed: {}", String::from_utf8_lossy(&output.stderr));
        }
        for (message, author, file) in [("A commit", "Agent A", "selected"), ("B commit", "Agent B", "second")] {
            let rev = format!("description(substring:{message:?})");
            assert_eq!(author, native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "log", "--no-graph", "-r", &rev, "-T", "author.name()"]));
            let files = native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "diff", "--from", &format!("({rev})-"), "--to", &rev, "--summary"]);
            assert!(files.contains(file), "missing scoped commit content: {files}");
            assert!(!files.contains("unrelated"), "scoped commit included unrelated file: {files}");
        }
        // Exercise private split through its real editor, relocating only the
        // fixture's trusted tool/config paths (the production script stays the oracle).
        if ["/bin/sh", "/bin/rm", "/bin/cp", "/usr/bin/git"].iter().all(|path| Path::new(path).is_file()) {
            let editor = root.join("split-editor");
            let script = include_str!("../agent-split-editor")
                .replace("patch=/tmp/jj-config/agent-split.patch", &format!("patch={}", config_home.join("agent-split.patch").display()))
                .replace("rm -rf", "/bin/rm -rf").replace("cp -a", "/bin/cp -a").replace("git -C", "/usr/bin/git -C");
            fs::write(&editor, script).unwrap();
            let config_text = include_str!("../jj.toml").replace("program = \"/trusted/bin/sh\"", "program = \"/bin/sh\"")
                .replace("\"/trusted/bin/agent-split-editor\"", &serde_json::to_string(editor.to_str().unwrap()).unwrap());
            fs::write(&config, config_text).unwrap();
            fs::write(root.join("relocated/split-selected"), "split this file\n").unwrap();
            let patch = native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "diff", "--git", "root:split-selected"]);
            let project_before_split = native(&jj, &root, &["-R", root.join("project").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]);
            let mut split_request = request_for("relocated", &[]);
            split_request.agent_split = Some(AgentSplit { patch, message: "--private dotfiles split".into(), revision: "@".into() });
            let response = execute_with_runtime(&split_request, &policy, source.as_raw_fd(), &workspaces,
                root.to_str().unwrap(), &runtime, Instant::now() + Duration::from_secs(5), None);
            assert_eq!(0, response.exit, "{}", response.stderr);
            assert_eq!(project_before_split, native(&jj, &root, &["-R", root.join("project").to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]));
            let revision = "description(substring:\"private dotfiles split\")";
            assert_eq!("--private dotfiles split\n", native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "log", "--no-graph", "-r", revision, "-T", "description"]));
            assert_eq!("Agent selector", native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "log", "--no-graph", "-r", revision, "-T", "author.name()"]));
            let files = native(&jj, &root, &["-R", root.join("relocated").to_str().unwrap(), "diff", "--from", &format!("({revision})-"), "--to", revision, "--summary"]);
            assert!(files.contains("split-selected")); assert!(!files.contains("unrelated"));
        } else { eprintln!("SKIP native private split: /bin/sh, /bin/rm, /bin/cp or /usr/bin/git unavailable"); }
        fs::remove_dir_all(root).unwrap();
    }


    #[test]
    fn checked_cwd_rejects_relative_and_symlink_namespaces_in_both_modes() {
        let root = env::temp_dir().join(format!("jj-cwd-{}", std::process::id()));
        fs::create_dir_all(root.join("workspace/nested")).unwrap();
        std::os::unix::fs::symlink("workspace", root.join("alias")).unwrap();
        let source = File::open(&root).unwrap();
        assert!(open_cwd(source.as_raw_fd(), "/src/workspace/nested", Path::new("/src")).is_ok());
        for path in ["workspace", "/tmp", "/src/../tmp", "/src/workspace/./nested", "/src//workspace", "/src/alias", "/src/workspace/"] {
            assert!(open_cwd(source.as_raw_fd(), path, Path::new("/src")).is_err(), "accepted {path}");
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn lock_wait_timeout_and_owner_death_preserve_persistent_inode() {
        if let Some(path) = env::var_os("JJ_PROXY_LOCK_CHILD") {
            let _lock = acquire_lock(Path::new(&path), Instant::now() + Duration::from_secs(5)).unwrap();
            fs::write(Path::new(&path).with_extension("ready"), "locked").unwrap();
            loop { thread::sleep(Duration::from_secs(1)); }
        }
        use std::os::unix::fs::MetadataExt;
        let root = env::temp_dir().join(format!("jj-lock-death-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let path = root.join("persistent.lock");
        fs::write(&path, "").unwrap();
        let inode = fs::metadata(&path).unwrap().ino();
        let mut owner = Command::new(env::current_exe().unwrap())
            .args(["--exact", "tests::lock_wait_timeout_and_owner_death_preserve_persistent_inode"])
            .env("JJ_PROXY_LOCK_CHILD", &path).stdout(Stdio::null()).spawn().unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while !path.with_extension("ready").exists() { assert!(Instant::now() < deadline); thread::sleep(Duration::from_millis(10)); }
        let started = Instant::now();
        assert!(acquire_lock(&path, started + Duration::from_millis(60)).is_err());
        assert!(started.elapsed() < Duration::from_secs(1));
        owner.kill().unwrap(); owner.wait().unwrap();
        let lock = acquire_lock(&path, Instant::now() + Duration::from_secs(1)).unwrap();
        assert_eq!(inode, lock.metadata().unwrap().ino());
        drop(lock);
        fs::remove_dir_all(root).unwrap();
    }


    #[cfg(target_os = "linux")]
    #[test]
    fn deadline_kills_and_reaps_descendants_before_lease_release() {
        if let Ok(role) = env::var("JJ_PROXY_DEADLINE_CHILD") {
            let root = PathBuf::from(env::var_os("JJ_PROXY_DEADLINE_ROOT").unwrap());
            fs::write(root.join(format!("{role}.pid")), std::process::id().to_string()).unwrap();
            if role == "leader" {
                let _descendant = Command::new(env::current_exe().unwrap())
                    .args(["--exact", "tests::deadline_kills_and_reaps_descendants_before_lease_release"])
                    .env("JJ_PROXY_DEADLINE_CHILD", "descendant").spawn().unwrap();
            }
            loop { thread::sleep(Duration::from_secs(1)); }
        }
        let root = env::temp_dir().join(format!("jj-deadline-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let lock_path = root.join("lease.lock"); fs::write(&lock_path, "").unwrap();
        let deadline = Instant::now() + Duration::from_millis(500);
        let lease = acquire_lock(&lock_path, deadline).unwrap();
        let cwd = File::open(&root).unwrap();
        let mut command = Command::new(env::current_exe().unwrap());
        command.args(["--exact", "tests::deadline_kills_and_reaps_descendants_before_lease_release"])
            .env("JJ_PROXY_DEADLINE_CHILD", "leader").env("JJ_PROXY_DEADLINE_ROOT", &root);
        unsafe { command.pre_exec(limits_and_cwd(cwd.as_raw_fd())); }
        let (status, _, _) = run_bounded(&mut command, deadline).unwrap();
        assert_eq!(124, status);
        for role in ["leader", "descendant"] {
            let pid: i32 = fs::read_to_string(root.join(format!("{role}.pid"))).unwrap().parse().unwrap();
            assert_eq!(Err(nix::errno::Errno::ESRCH), kill(Pid::from_raw(pid), None), "{role} survived or was not reaped");
        }
        drop(lease);
        let _next = acquire_lock(&lock_path, Instant::now() + Duration::from_secs(1)).unwrap();
        fs::remove_dir_all(root).unwrap();
    }


    #[test]
    fn startup_budget_is_positive_and_shared_between_lock_acquisitions() {
        assert_eq!(TIMEOUT, startup_timeout(None).unwrap());
        assert_eq!(Duration::from_secs(120), startup_timeout(Some("120")).unwrap());
        for value in ["", "0", "-1", "+1", " 120", "1.5", "18446744073709551616"] {
            assert!(startup_timeout(Some(value)).is_err(), "accepted {value:?}");
        }
        let root = env::temp_dir().join(format!("jj-startup-budget-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let first = root.join("first.lock"); let second = root.join("second.lock");
        fs::write(&first, "").unwrap(); fs::write(&second, "").unwrap();
        let held = acquire_lock(&second, Instant::now() + Duration::from_secs(1)).unwrap();
        let deadline = Instant::now() + Duration::from_millis(80);
        let first_lease = acquire_lock(&first, deadline).unwrap();
        // Model configuration preparation consuming the entire shared budget.
        while Instant::now() < deadline { thread::sleep(Duration::from_millis(5)); }
        drop(first_lease);
        let started = Instant::now();
        assert!(acquire_lock(&second, deadline).is_err());
        assert!(started.elapsed() < Duration::from_millis(40));
        drop(held); fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cancellation_racing_with_lock_admission_releases_the_lease() {
        let root = env::temp_dir().join(format!("jj-lock-admission-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let lock_path = root.join("request.lock"); fs::write(&lock_path, "").unwrap();
        let mut checks = 0;
        let result = acquire_lock_checked(&lock_path, Instant::now() + Duration::from_secs(1), || {
            checks += 1;
            if checks == 2 { bail!("request canceled after acquiring ownership"); }
            Ok(())
        });
        assert!(result.is_err()); assert_eq!(2, checks);
        let _next = acquire_lock(&lock_path, Instant::now() + Duration::from_secs(1)).unwrap();
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn disconnected_queued_request_cannot_mutate_but_write_half_close_can() {
        use std::sync::mpsc;
        let Some(jj) = real_jj() else { eprintln!("SKIP queued disconnect: no real JJ"); return; };
        let root = env::temp_dir().join(format!("jj-peer-cancel-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let root = fs::canonicalize(root).unwrap();
        let repo = root.join("repository");
        native(&jj, &root, &["git", "init", repo.to_str().unwrap()]);
        let authority = test_authority(&root, "repository");
        fs::write(&authority.lock, "").unwrap();
        fs::write(root.join("trusted.toml"), include_str!("../jj.toml")).unwrap();
        fs::create_dir(root.join("config")).unwrap();
        for disconnect in [false, true] {
            let filename = if disconnect { "canceled-file" } else { "normal-file" };
            fs::write(repo.join(filename), "selected contents").unwrap();
            let before = native(&jj, &root, &["-R", repo.to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]);
            let lease = acquire_lock(Path::new(&authority.lock), Instant::now() + Duration::from_secs(1)).unwrap();
            let (mut client, mut server) = UnixStream::pair().unwrap();
            let request = Request { version: 2, mode: RequestMode::Mutate, cwd: repo.to_str().unwrap().into(),
                argv: vec!["commit".into(), format!("root:{filename}"), "-m".into(), filename.into()],
                agent_split: None, user: Some("Agent cancellation".into()), email: Some("cancel@example.test".into()) };
            write_frame(&mut client, &serde_json::to_vec(&request).unwrap()).unwrap();
            client.shutdown(Shutdown::Write).unwrap();
            let (decoded_tx, decoded_rx) = mpsc::channel();
            let (done_tx, done_rx) = mpsc::channel();
            let worker_root = root.clone(); let worker_jj = jj.clone(); let worker_authority = authority.clone();
            let worker = thread::spawn(move || {
                let request: Request = serde_json::from_slice(&read_frame(&mut server, MAX_REQUEST).unwrap()).unwrap();
                require_eof(&mut server).unwrap();
                let source = File::open(&worker_root).unwrap();
                let config = worker_root.join("trusted.toml"); let config_home = worker_root.join("config");
                let runtime = Runtime { source: &worker_root, jj: &worker_jj, config: &config, config_home: &config_home, after_author_update: None };
                let policy = policy::Policy::load(Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/policy.toml"))).unwrap();
                // The complete half-closed request is decoded while another
                // owner holds the target lock. No JJ mutation can yet be admitted.
                decoded_tx.send(()).unwrap();
                let response = execute_with_runtime(&request, &policy, source.as_raw_fd(), &[worker_authority],
                    worker_root.to_str().unwrap(), &runtime, Instant::now() + Duration::from_secs(5), Some(&server));
                done_tx.send(response).unwrap();
            });
            decoded_rx.recv_timeout(Duration::from_secs(1)).unwrap();
            if disconnect {
                drop(client);
                // Cancellation must finish while ownership is STILL unavailable,
                // not run an orphan prehook after the previous owner releases it.
                let response = done_rx.recv_timeout(Duration::from_secs(1)).expect("disconnected waiter did not cancel while blocked");
                assert_ne!(0, response.exit); assert!(response.stderr.contains("request canceled"), "{}", response.stderr);
                assert_eq!(before, native(&jj, &root, &["-R", repo.to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]));
                drop(lease); worker.join().unwrap();
                assert_eq!(before, native(&jj, &root, &["-R", repo.to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]));
            } else {
                assert!(matches!(done_rx.recv_timeout(Duration::from_millis(80)), Err(mpsc::RecvTimeoutError::Timeout)), "write half-close canceled a valid waiter");
                drop(lease);
                let response = done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
                assert_eq!(0, response.exit, "{}", response.stderr);
                worker.join().unwrap(); drop(client);
                assert_ne!(before, native(&jj, &root, &["-R", repo.to_str().unwrap(), "--ignore-working-copy", "op", "log", "--no-graph", "-T", "id"]));
            }
        }
        // A disconnect after the actual prehook has started the operation is
        // outcome-unknown to the client, not permission to interrupt its sequence.
        fs::write(repo.join("started-file"), "started contents").unwrap();
        let (client, server) = UnixStream::pair().unwrap();
        client.shutdown(Shutdown::Write).unwrap();
        let client = std::cell::RefCell::new(Some(client));
        let disconnect_after_hook = || { drop(client.borrow_mut().take()); };
        let source = File::open(&root).unwrap();
        let config = root.join("trusted.toml"); let config_home = root.join("config");
        let runtime = Runtime { source: &root, jj: &jj, config: &config, config_home: &config_home,
            after_author_update: Some(&disconnect_after_hook) };
        let policy = policy::Policy::load(Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/policy.toml"))).unwrap();
        let started = Request { version: 2, mode: RequestMode::Mutate, cwd: repo.to_str().unwrap().into(),
            argv: ["commit", "root:started-file", "-m", "started request"].into_iter().map(str::to_owned).collect(),
            agent_split: None, user: Some("Agent started".into()), email: Some("started@example.test".into()) };
        let response = execute_with_runtime(&started, &policy, source.as_raw_fd(), &[authority], root.to_str().unwrap(),
            &runtime, Instant::now() + Duration::from_secs(5), Some(&server));
        assert_eq!(0, response.exit, "started operation was canceled: {}", response.stderr);
        assert_eq!("Agent started", native(&jj, &root, &["-R", repo.to_str().unwrap(), "log", "--no-graph", "-r", "description(substring:\"started request\")", "-T", "author.name()"]));
        let trusted_config: toml::Value = toml::from_str(include_str!("../jj.toml")).unwrap();
        assert_eq!(trusted_config["user"]["name"].as_str().unwrap(), native(&jj, &root, &["-R", repo.to_str().unwrap(), "log", "--no-graph", "-r", "@", "-T", "author.name()"]), "started disconnect skipped author reset");
        fs::remove_dir_all(root).unwrap();
    }

}
