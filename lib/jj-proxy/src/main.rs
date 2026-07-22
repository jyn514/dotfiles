mod policy;

use color_eyre::eyre::{bail, eyre, Result, WrapErr};
use landlock::{
    make_bitflags, AccessFs, CompatLevel, Compatible, PathBeneath, PathFd, Ruleset,
    RulesetAttr, RulesetCreatedAttr, RulesetStatus,
};
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
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const SOCKET: &str = "/run/sandbox-proxy/socket";
const CONFIG_HOME: &str = "/tmp/jj-config";
const MAX_REQUEST: usize = 1 << 20;
const MAX_OUTPUT: usize = 8 << 20;
const TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request { version: u8, cwd: String, argv: Vec<String> }

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Response { version: u8, exit: i32, stdout: String, stderr: String }

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

fn install_execution_policy(repo: &str) -> Result<()> {
    let trusted = PathFd::new("/trusted").wrap_err("cannot open trusted directory")?;
    let trusted_bin = PathFd::new("/trusted/bin").wrap_err("cannot open trusted executable directory")?;
    let repository = PathFd::new(repo).wrap_err("cannot open repository directory")?;
    let git_path = env::var("JJ_PROXY_GIT_DIR").wrap_err("Git directory is not configured")?;
    let common_path = env::var("JJ_PROXY_COMMON_DIR").wrap_err("Git common directory is not configured")?;
    let jj_repo_path = env::var("JJ_PROXY_JJ_REPO").wrap_err("Jujutsu repository directory is not configured")?;
    let git = PathFd::new(&git_path).wrap_err("cannot open Git metadata directory")?;
    let common = PathFd::new(&common_path).wrap_err("cannot open Git common directory")?;
    let jj = PathFd::new(format!("{repo}/.jj")).wrap_err("cannot open Jujutsu metadata directory")?;
    let jj_repo = PathFd::new(&jj_repo_path).wrap_err("cannot open Jujutsu repository directory")?;
    let config = PathFd::new(CONFIG_HOME).wrap_err("cannot open secure config directory")?;
    let socket = PathFd::new("/run/sandbox-proxy").wrap_err("cannot open proxy socket directory")?;
    let system_config = PathFd::new("/etc").wrap_err("cannot open system configuration directory")?;
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
        .add_rule(PathBeneath::new(repository, read_access))
        .wrap_err("cannot add repository read rule")?
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
    if !matches!(status.ruleset, RulesetStatus::FullyEnforced | RulesetStatus::PartiallyEnforced)
        || !status.no_new_privs
    {
        bail!("Landlock execution policy was not enforced: {status:?}");
    }
    Ok(())
}

fn prepare_repo_config(repo: &str) -> Result<()> {
    let output = Command::new("/trusted/bin/jj")
        .args(["--repository", repo, "--ignore-working-copy", "config", "path", "--repo"])
        .env_clear()
        .envs([
            ("JJ_CONFIG", "/trusted/jj.toml"),
            ("HOME", "/nonexistent"),
            ("XDG_CONFIG_HOME", CONFIG_HOME),
    ])
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

fn open_cwd(root: RawFd, path: &str) -> Result<OwnedFd> {
    if path.contains('\0') || path.starts_with('/') {
        bail!("cwd must be relative to the repository");
    }
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

fn execute(request: &Request, root: RawFd, repo: &str, remotes: &HashSet<String>) -> Response {
    let failure = |message: String| Response { version: 1, exit: 2, stdout: String::new(), stderr: format!("jj proxy: {message}\n") };
    if request.version != 1 { return failure("unsupported protocol version".into()); }
    if request.argv.as_slice() == [":ready"] {
        return Response { version: 1, exit: 0, stdout: String::new(), stderr: String::new() };
    }
    if let Err(error) = policy::validate(&request.argv, remotes) { return failure(error.to_string()); }
    let cwd = match open_cwd(root, &request.cwd) { Ok(fd) => fd, Err(error) => return failure(error.to_string()) };

    let mut command = Command::new("/trusted/bin/jj");
    command.args([
        "--no-pager", "--color=never",
        "--config", "ui.editor=[\"/trusted/bin/jj-proxy\",\"reject-editor\"]",
        "--config", "ui.diff-editor=:builtin",
        "--config", "ui.merge-editor=:builtin",
        "--config", "signing.behavior=drop",
        "--repository", repo,
    ]);
    if matches!(request.argv.first().map(String::as_str), Some("diff" | "show")) {
        command.args(["--config", "ui.diff-formatter=:git"]);
    }
    command.args(&request.argv);
    if request.argv.as_slice().starts_with(&["git".into(), "fetch".into()])
        && !request.argv.iter().any(|arg| arg == "--remote" || arg.starts_with("--remote="))
    {
        for remote in remotes { command.args(["--remote", remote]); }
    }
    command.env_clear().envs([
        ("PATH", "/trusted/bin"), ("JJ_CONFIG", "/trusted/jj.toml"),
        ("HOME", "/nonexistent"), ("XDG_CONFIG_HOME", CONFIG_HOME),
        ("PAGER", "false"), ("GIT_PAGER", "false"), ("EDITOR", "false"),
        ("VISUAL", "false"), ("GIT_CONFIG_NOSYSTEM", "1"),
        ("GIT_CONFIG_GLOBAL", "/dev/null"), ("GIT_TERMINAL_PROMPT", "0"),
        ("GIT_CONFIG_COUNT", "1"), ("GIT_CONFIG_KEY_0", "core.excludesFile"),
        ("GIT_CONFIG_VALUE_0", "/trusted/gitignore"),
        ("JJ_USER", "Codex"), ("JJ_EMAIL", "breq@jyn.dev"),
        ("RUST_BACKTRACE", "1"),
    ]).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
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
    Response { version: 1, exit: status, stdout: String::from_utf8_lossy(&stdout).into_owned(), stderr: String::from_utf8_lossy(&stderr).into_owned() }
}

fn serve() -> Result<()> {
    let repo = env::var("JJ_PROXY_REPO").unwrap_or_else(|_| "/src/work".to_owned());
    let root = File::open(&repo).wrap_err("cannot open repository")?;
    let remotes = HashSet::from(["origin".to_owned()]);
    fs::create_dir_all(CONFIG_HOME).wrap_err("cannot create secure config directory")?;
    fs::set_permissions(CONFIG_HOME, fs::Permissions::from_mode(0o700)).wrap_err("cannot secure config directory")?;
    install_execution_policy(&repo)?;
    prepare_repo_config(&repo)?;
    let _ = fs::remove_file(SOCKET);
    let listener = UnixListener::bind(SOCKET).wrap_err("cannot bind proxy socket")?;
    fs::set_permissions(SOCKET, fs::Permissions::from_mode(0o666)).wrap_err("cannot set proxy socket permissions")?;
    for connection in listener.incoming() {
        let mut stream = match connection { Ok(stream) => stream, Err(error) => { eprintln!("jj proxy: accept: {error}"); continue; } };
        let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
        let response = match read_frame(&mut stream, MAX_REQUEST)
            .and_then(|bytes| { require_eof(&mut stream)?; Ok(bytes) })
            .and_then(|bytes| serde_json::from_slice::<Request>(&bytes).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))) {
            Ok(request) => execute(&request, root.as_raw_fd(), &repo, &remotes),
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
    let relative = cwd.strip_prefix(&repo_path).map_err(|_| eyre!("current directory is outside the protected repository"))?;
    let request = Request { version: 1, cwd: relative.to_string_lossy().into_owned(), argv: args };
    let body = serde_json::to_vec(&request).wrap_err("cannot encode request")?;
    let proxy_dir = env::var("SANDBOX_PROXY_DIR").wrap_err("sandbox proxy directory is not configured")?;
    let mut stream = UnixStream::connect(format!("{proxy_dir}/jj/socket")).wrap_err("proxy unavailable")?;
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
    let mut stream = UnixStream::connect(SOCKET).wrap_err("proxy unavailable")?;
    let stdin = io::stdin();
    let mut input = stdin.lock();
    io::copy(&mut input, &mut stream).wrap_err("cannot forward proxy request")?;
    stream.shutdown(Shutdown::Write).wrap_err("cannot finish proxy request")?;
    let stdout = io::stdout();
    let mut output = stdout.lock();
    io::copy(&mut stream, &mut output).wrap_err("cannot forward proxy response")?;
    Ok(0)
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
    } else {
        client(std::mem::take(&mut args))
    };
    match result { Ok(code) => std::process::exit(code), Err(error) => { eprintln!("jj proxy: {error:?}"); std::process::exit(125); } }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
