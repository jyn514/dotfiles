use color_eyre::eyre::{bail, eyre, Result, WrapErr};
use jj_proxy::{execution_policy, policy};
use serde::{Deserialize, Serialize};
use nix::fcntl::{openat, OFlag};
use nix::sys::resource::{setrlimit, Resource};
use nix::sys::signal::{kill, Signal};
use nix::sys::stat::Mode;
use nix::unistd::{close, dup, fchdir, setsid, Pid};
use std::collections::HashSet;
use std::env;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::net::Shutdown;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::os::unix::process::CommandExt;
use std::path::Path;
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

fn prepare_jj_config(repo: &str, scope: &str, jj: &Path, trusted_config: &Path, config_home: &Path) -> Result<()> {
    let output = Command::new(jj)
        .arg("--config-file").arg(trusted_config)
        .args(["--repository", repo, "--ignore-working-copy", "config", "path", scope])
        .env_clear()
        .env("HOME", "/nonexistent")
        .env("XDG_CONFIG_HOME", config_home)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .wrap_err("cannot initialize per-repository Jujutsu config")?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr[..output.stderr.len().min(8192)]);
        let stderr = stderr.trim();
        let detail = if stderr.is_empty() {
            String::new()
        } else {
            format!(": {stderr}")
        };
        bail!(
            "cannot initialize per-repository Jujutsu config: jj exited with {}{detail}",
            output.status,
        );
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

fn prepare_inspection_config(workspace: &Path, jj: &Path, trusted_config: &Path, config_home: &Path) -> Result<()> {
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
        prepare_jj_config(workspace, "--repo", jj, trusted_config, config_home)?;
    }
    if workspace_has_config {
        prepare_jj_config(workspace, "--workspace", jj, trusted_config, config_home)?;
    }
    Ok(())
}

fn open_cwd(root: RawFd, path: &str, inspect: bool) -> Result<OwnedFd> {
    if path.contains('\0') || (!inspect && path.starts_with('/')) || (inspect && path != "/src" && !path.starts_with("/src/")) {
        bail!("cwd is outside the protected /src workspace");
    }
    let path = if inspect { path.strip_prefix("/src").unwrap_or("") } else { path };
    let mut current = dup(root).wrap_err("could not duplicate repository descriptor")?;
    for component in path.split('/').filter(|part| !part.is_empty() && *part != ".") {
        if component == ".." { bail!("cwd escapes the repository"); }
        let next = openat(
            Some(current), component,
            OFlag::O_RDONLY | OFlag::O_DIRECTORY | OFlag::O_NOFOLLOW | OFlag::O_CLOEXEC,
            Mode::empty(),
        ).wrap_err_with(|| format!("invalid cwd component {component:?}"))?;
        close(current).wrap_err("could not close cwd descriptor")?;
        current = next;
    }
    // SAFETY: `current` came from `dup` or `openat`, so it is a valid, open
    // descriptor. Each superseded descriptor was closed above, and no other
    // owning Rust value was constructed from `current`; ownership can
    // therefore be transferred exactly once to `OwnedFd` here.
    Ok(unsafe { OwnedFd::from_raw_fd(current) })
}

fn jj_command() -> Command {
    let mut command = Command::new("/trusted/bin/jj");
    // Command-line config has higher precedence than repository config. Keep
    // jj.toml as the single declaration instead of repeating protected keys.
    command.args([
        "--no-pager",
        "--color=never",
        "--config-file",
        TRUSTED_JJ_CONFIG,
    ]);
    command
}

fn agent_jj_command(user: &str, email: &str) -> Command {
    let mut command = jj_command();
    // The trusted file contains the human identity used when returning control.
    // Agent attribution must therefore override it at the same CLI precedence.
    command
        .arg("--config")
        .arg(format!("user.name={user}"))
        .arg("--config")
        .arg(format!("user.email={email}"));
    command
}

fn workspace_for(path: &Path) -> Option<&Path> {
    path.ancestors().find(|ancestor| ancestor.join(".jj").is_dir())
}

fn select_repository(request: &Request, selected_repo: &Path, source_root: &Path, selector: Option<&str>) -> Result<(std::path::PathBuf, bool)> {
    let invocation = if matches!(request.mode, RequestMode::Inspect) {
        Path::new(&request.cwd).to_path_buf()
    } else {
        selected_repo.join(&request.cwd)
    };
    let target = match selector {
        Some(value) => fs::canonicalize(invocation.join(value)).wrap_err("cannot resolve repository selector")?,
        None => invocation,
    };
    if selector.is_some() && !target.starts_with(source_root) && target != selected_repo {
        bail!("repository selector is outside /src");
    }
    let workspace = if selector.is_some() || matches!(request.mode, RequestMode::Inspect) {
        workspace_for(&target).ok_or_else(|| eyre!("repository selector is not inside a Jujutsu workspace"))?
    } else {
        selected_repo
    };
    let inspect = matches!(request.mode, RequestMode::Inspect) || workspace != selected_repo;
    Ok((workspace.to_path_buf(), inspect))
}

fn author_update_command(user: &str, email: &str) -> Command {
    let mut command = agent_jj_command(user, email);
    command.args(["metaedit", "--update-author", "-r", "@", "--quiet"]);
    command
}

fn reset_author_command() -> Command {
    let mut command = jj_command();
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

fn limits_and_cwd(fd: RawFd) -> impl FnMut() -> io::Result<()> {
    move || {
        let io_error = |error: nix::errno::Errno| io::Error::from_raw_os_error(error as i32);
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

fn execute(
    request: &Request,
    command_policy: &policy::Policy,
    root: RawFd,
    selected_repo: &Path,
    remotes: &HashSet<String>,
    temporary_directory: &str,
) -> Response {
    let failure = |message: String| Response { version: 1, exit: 2, stdout: String::new(), stderr: format!("jj proxy: {message}\n") };
    if request.version != 1 { return failure("unsupported protocol version".into()); }
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
    if request.argv.as_slice() == [":ready"] && request.agent_split.is_none() {
        return Response { version: 1, exit: 0, stdout: String::new(), stderr: String::new() };
    }
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
        if let Err(error) = fs::write(format!("{CONFIG_HOME}/agent-split.patch"), &split.patch) {
            return failure(format!("could not stage split patch: {error}"));
        }
    }
    let cwd = match open_cwd(root, &request.cwd, matches!(request.mode, RequestMode::Inspect)) { Ok(fd) => fd, Err(error) => return failure(error.to_string()) };
    let (workspace, inspect) = match select_repository(request, selected_repo, Path::new("/src"), repository_selector.as_deref()) {
        Ok(selection) => selection,
        Err(error) => return failure(error.to_string()),
    };
    let decision = if request.agent_split.is_none() {
        let validation = if inspect { command_policy.validate_inspect(&argv) } else { command_policy.validate(&argv, remotes) };
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
        if let Err(error) = prepare_inspection_config(&workspace, Path::new("/trusted/bin/jj"), Path::new(TRUSTED_JJ_CONFIG), Path::new(CONFIG_HOME)) {
            return failure(format!("cannot prepare inspection repository config: {error}"));
        }
    }

    if !inspect && updates_author {
        let mut update = author_update_command(user, email);
        update.env_clear().envs(command_environment(user, email, temporary_directory))
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        // Match the local wrapper's best-effort update: failure must not block the
        // requested command, but successful commits must not inherit jyn's author.
        unsafe { update.pre_exec(limits_and_cwd(cwd.as_raw_fd())); }
        let _ = update.status();
    }

    let mut command = if inspect {
        let mut command = Command::new(TRUSTED_PROXY);
        command.args(["inspect-jj", user, email]);
        command
    } else {
        agent_jj_command(user, email)
    };
    if repository_selector.is_some() {
        command.arg("--repository").arg(&workspace);
    }
    if let Some(split) = &request.agent_split {
        command.args([
            "split", "--tool", "agent-split", "-m", split.message.as_str(),
            "-r", split.revision.as_str(),
        ]);
    } else {
        command.args(&argv);
    }
    command.env_clear().envs(command_environment(user, email, temporary_directory))
        .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    if inspect {
        for key in ["JJ_PROXY_REPO", "JJ_PROXY_GIT_DIR", "JJ_PROXY_COMMON_DIR", "JJ_PROXY_JJ_REPO"] {
            if let Ok(value) = env::var(key) { command.env(key, value); }
        }
    }
    // SAFETY: the callback captures only the copied descriptor number and
    // performs the async-signal-safe `setsid`, `fchdir`, and `setrlimit`
    // syscalls. No proxy reader threads exist while `spawn` forks, and `cwd`
    // remains alive until after `spawn` returns, so the descriptor is valid in
    // the child. The callback does not allocate, lock, or access shared state.
    unsafe { command.pre_exec(limits_and_cwd(cwd.as_raw_fd())); }
    let mut child = match command.spawn() { Ok(child) => child, Err(error) => return failure(format!("could not start jj: {error}")) };
    let pid = child.id();
    let child_stdout = child.stdout.take().unwrap();
    let child_stderr = child.stderr.take().unwrap();
    let out_thread = thread::spawn(move || collect(child_stdout));
    let err_thread = thread::spawn(move || collect(child_stderr));
    let started = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status.code().unwrap_or(128),
            Ok(None) if started.elapsed() < TIMEOUT => thread::sleep(Duration::from_millis(20)),
            Ok(None) => { kill_group(pid); let _ = child.wait(); break 124; }
            Err(error) => { kill_group(pid); let _ = child.wait(); return failure(format!("could not wait for jj: {error}")); }
        }
    };
    // A successful leader must not be allowed to leave inherited-pipe holders
    // or other descendants behind in the proxy container.
    kill_group(pid);
    let stdout = out_thread.join().ok().and_then(Result::ok).unwrap_or_default();
    let stderr = err_thread.join().ok().and_then(Result::ok).unwrap_or_default();
    if stdout.len() > MAX_OUTPUT || stderr.len() > MAX_OUTPUT {
        return failure("output limit exceeded".into());
    }
    if status == 0 && !inspect && updates_author {
        let mut reset = reset_author_command();
        reset.env_clear().envs(trusted_environment(temporary_directory))
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        // A successful agent command may create or snapshot a new working-copy
        // commit. Return its author to the repository identity so later human
        // work is not attributed to the agent that happened to create `@`.
        unsafe { reset.pre_exec(limits_and_cwd(cwd.as_raw_fd())); }
        let _ = reset.status();
    }
    Response { version: 1, exit: status, stdout: String::from_utf8_lossy(&stdout).into_owned(), stderr: String::from_utf8_lossy(&stderr).into_owned() }
}

fn serve() -> Result<()> {
    let command_policy = policy::Policy::load(Path::new(TRUSTED_COMMAND_POLICY))?;
    // The server retains its mutation policy; inspection children add a
    // read-only policy before executing Jujutsu.
    let repo = env::var("JJ_PROXY_REPO").unwrap_or_else(|_| "/src/work".to_owned());
    // Keep both roots available: request mode, not the server's startup
    // environment, selects the cwd namespace.
    let source_root = File::open("/src").wrap_err("cannot open source")?;
    let repository_root = File::open(&repo).wrap_err("cannot open repository")?;
    let remotes = HashSet::from(["origin".to_owned()]);
    fs::create_dir_all(CONFIG_HOME).wrap_err("cannot create secure config directory")?;
    fs::set_permissions(CONFIG_HOME, fs::Permissions::from_mode(0o700)).wrap_err("cannot secure config directory")?;
    fs::create_dir_all(TEMP_HOME).wrap_err("cannot create Jujutsu temporary directory")?;
    fs::set_permissions(TEMP_HOME, fs::Permissions::from_mode(0o700))
        .wrap_err("cannot secure Jujutsu temporary directory")?;
    execution_policy::install(&repo)?;
    prepare_jj_config(&repo, "--repo", Path::new("/trusted/bin/jj"), Path::new(TRUSTED_JJ_CONFIG), Path::new(CONFIG_HOME))?;
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
                if matches!(request.mode, RequestMode::Inspect) {
                    source_root.as_raw_fd()
                } else {
                    repository_root.as_raw_fd()
                },
                Path::new(&repo),
                &remotes,
                TEMP_HOME,
            ),
            Err(error) => Response { version: 1, exit: 2, stdout: String::new(), stderr: format!("jj proxy: invalid request: {error}\n") },
        };
        if let Ok(body) = serde_json::to_vec(&response) { let _ = write_frame(&mut stream, &body); }
    }
    Ok(())
}

fn client(args: Vec<String>) -> Result<i32> {
    let repo = env::var("JJ_PROXY_REPO").unwrap_or_else(|_| "/src/work".into());
    let cwd = env::current_dir().wrap_err("cannot read current directory")?;
    let repo_path = fs::canonicalize(&repo).wrap_err("repository unavailable")?;
    let cwd = fs::canonicalize(cwd).wrap_err("cannot resolve current directory")?;
    let inspect = env::var_os("JJ_PROXY_INSPECT").is_some()
        || (cwd.starts_with("/src") && cwd.strip_prefix(&repo_path).is_err());
    let cwd = if inspect {
        cwd.to_string_lossy().into_owned()
    } else {
        cwd.strip_prefix(&repo_path)
            .map_err(|_| eyre!("current directory is outside the protected repository"))?
            .to_string_lossy().into_owned()
    };
    let request = Request {
        version: 1,
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
    if response.version != 1 { bail!("unsupported response version"); }
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
    let repo = env::var("JJ_PROXY_REPO").wrap_err("repository unavailable")?;
    execution_policy::install_inspect(&repo)?;
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
        let jj = env::var_os("JJ_PROXY_TEST_JJ").map(PathBuf::from).or_else(|| {
            ["/trusted/bin/jj", "/opt/agent-tools/bin/jj", "/opt/homebrew/bin/jj"]
                .into_iter().map(PathBuf::from).find(|path| {
                    fs::symlink_metadata(path).is_ok_and(|metadata| metadata.file_type().is_file())
                })
        });
        let Some(jj) = jj else {
            eprintln!("skipping inspection config test: set JJ_PROXY_TEST_JJ to a real jj binary");
            return;
        };
        let root = env::temp_dir().join(format!("jj-proxy-inspect-config-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
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
            .args(["workspace", "add", "--no-colocate"]).arg(&linked)
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
        fs::remove_dir_all(root).unwrap();
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
            version: 1, mode: RequestMode::Mutate, cwd: "nested".into(),
            argv: vec!["status".into()], agent_split: None, user: None, email: None,
        };
        assert_eq!((selected.clone(), false), select_repository(&request, &selected, &source, Some(".")).unwrap());
        assert_eq!((other.clone(), true), select_repository(&request, &selected, &source, Some("../../other")).unwrap());
        assert!(select_repository(&request, &selected, &source, Some(outside.to_str().unwrap())).is_err());
        assert!(select_repository(&request, &selected, &source, Some("escape")).is_err());
        request.mode = RequestMode::Inspect;
        request.cwd = other.to_string_lossy().into_owned();
        assert_eq!((selected, true), select_repository(&request, &source.join("selected"), &source, Some("../selected")).unwrap());
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
        let remotes = HashSet::new();
        assert!(policy.validate(&["commit".into()], &remotes).unwrap().updates_author);
        assert!(policy.validate(&["split".into()], &remotes).unwrap().updates_author);
        assert!(!policy.validate(&["status".into()], &remotes).unwrap().updates_author);

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
            version: 1,
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
        let response = execute(&request, &policy, root.as_raw_fd(), Path::new("/tmp"), &HashSet::new(), "/tmp");
        assert_eq!(2, response.exit);
        assert!(response.stderr.contains("agent split is not allowed"));
    }
}
