//! Host-native broker: fixed authority, bounded streams, and live child ownership.
//! Native stdout/stderr are pipes, stdin is closed at the end of request bytes;
//! broker stdout is reserved exclusively for one bounded readiness JSON line.
use crate::{policy, protocol::*, repository};
use anyhow::{bail, Context, Result};
use nix::fcntl::{fcntl, FcntlArg, FdFlag, OFlag};
use nix::sys::signal::{kill, Signal};
use nix::unistd::Pid;
use serde::{Deserialize, Serialize};
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::fd::{AsRawFd, FromRawFd, RawFd};
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread;
use std::time::{Duration, Instant};

pub const NATIVE_REVISION: &str = include_str!("../native-revision").trim_ascii();
// The file is the single pin authority; reject a malformed edited pin at build
// time instead of silently publishing a different or abbreviated build identity.
const _: () = {
    assert!(NATIVE_REVISION.len() == 40);
    let bytes = NATIVE_REVISION.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        assert!(matches!(bytes[index], b'0'..=b'9' | b'a'..=b'f'));
        index += 1;
    }
};
pub const POLICY_VERSION: u32 = 1;
const WORKERS: usize = 8;
const TICK: Duration = Duration::from_millis(5);

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub version: u32,
    pub workspace: PathBuf,
    pub common_dir: PathBuf,
    pub native_executable: PathBuf,
    pub native_sha256: String,
    pub user_name: String,
    pub user_email: String,
    pub namespace: String,
    pub token: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeManifest {
    native_revision: String,
    policy_version: u32,
    sha256: String,
}
#[derive(Serialize)]
struct Ready {
    version: u32,
    address: String,
    native_revision: &'static str,
    policy_version: u32,
}

pub fn load_config(path: &Path) -> Result<Config> {
    // The launcher creates this file outside guest mounts. Reject symlinks and
    // permissive files rather than silently repairing authority on startup.
    let meta = fs::symlink_metadata(path)?;
    if !meta.is_file()
        || meta.permissions().mode() & 0o777 != 0o600
        || meta.uid() != nix::unistd::geteuid().as_raw()
    {
        bail!("configuration must be an owner-only regular 0600 file");
    }
    let bytes = fs::read(path)?;
    if bytes.len() > 64 * 1024 {
        bail!("configuration too large");
    }
    Ok(serde_json::from_slice(&bytes)?)
}
fn validate(config: &Config) -> Result<()> {
    if config.version != CONFIG_VERSION || config.token.len() < 32 || config.token.len() > 4096 {
        bail!("invalid configuration version or authentication token");
    }
    for value in [&config.user_name, &config.user_email, &config.namespace] {
        if value.contains('\0') {
            bail!("invalid accepted identity or namespace");
        }
    }
    if !config.native_executable.is_absolute()
        || !config.workspace.is_absolute()
        || !config.common_dir.is_absolute()
    {
        bail!("accepted paths must be absolute");
    }
    let native = fs::canonicalize(&config.native_executable)?;
    let metadata = fs::metadata(&native)?;
    if native != config.native_executable
        || !metadata.is_file()
        || metadata.uid() != nix::unistd::geteuid().as_raw()
        || metadata.nlink() != 1
        || metadata.permissions().mode() & 0o022 != 0
        || metadata.permissions().mode() & 0o111 == 0
    {
        bail!("native executable must be a canonical launcher-owned regular executable");
    }
    let mut manifest_path = native.as_os_str().to_os_string();
    manifest_path.push(".tic-proxy.json");
    let manifest_path = PathBuf::from(manifest_path);
    let metadata = fs::symlink_metadata(&manifest_path)?;
    if !metadata.is_file()
        || metadata.uid() != nix::unistd::geteuid().as_raw()
        || metadata.nlink() != 1
        || metadata.permissions().mode() & 0o022 != 0
        || metadata.len() > 64 * 1024
    {
        bail!("native binding must be a bounded launcher-owned regular file");
    }
    let manifest: NativeManifest = serde_json::from_slice(&fs::read(manifest_path)?)?;
    // Publication checked artifact bytes outside guest-writable mounts. Runtime
    // checks retain path/pin/policy authority, not host-cache corruption checks.
    if manifest.native_revision != NATIVE_REVISION
        || manifest.policy_version != POLICY_VERSION
        || config.native_sha256.len() != 64
        || !config
            .native_sha256
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        || manifest.sha256 != config.native_sha256
    {
        bail!("installed native build/policy binding mismatch");
    }
    let context = repository::preflight(&config.workspace, &config.common_dir)?;
    if context.workspace != config.workspace || context.common_dir != config.common_dir {
        bail!("repository authority must be canonical");
    }
    Ok(())
}
fn nonblocking(fd: RawFd) -> Result<()> {
    let flags = OFlag::from_bits_truncate(fcntl(fd, FcntlArg::F_GETFL)?);
    fcntl(fd, FcntlArg::F_SETFL(flags | OFlag::O_NONBLOCK))?;
    Ok(())
}
fn cancelled(stop: &AtomicBool, deadline: Instant) -> bool {
    stop.load(Ordering::Acquire) || Instant::now() >= deadline
}
fn transient(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
    )
}
fn read_piece(
    stream: &mut TcpStream,
    bytes: &mut [u8],
    stop: &AtomicBool,
    deadline: Instant,
) -> Result<()> {
    let mut done = 0;
    while done < bytes.len() {
        if cancelled(stop, deadline) {
            bail!("admission cancelled or expired");
        }
        match stream.read(&mut bytes[done..]) {
            Ok(0) => bail!("incomplete request"),
            Ok(n) => done += n,
            Err(e) if transient(&e) => thread::sleep(TICK),
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}
#[derive(Debug)]
struct AdmissionRejection(&'static str);
impl std::fmt::Display for AdmissionRejection {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}
impl std::error::Error for AdmissionRejection {}

fn receive(
    stream: &mut TcpStream,
    stop: &AtomicBool,
    deadline: Instant,
) -> Result<AuthenticatedRequest> {
    let mut header = [0; 4];
    read_piece(stream, &mut header, stop, deadline)?;
    let size = u32::from_be_bytes(header) as usize;
    if size > MAX_REQUEST {
        return Err(AdmissionRejection("request frame limit exceeded").into());
    }
    let mut bytes = vec![0; size];
    read_piece(stream, &mut bytes, stop, deadline)?;
    Ok(serde_json::from_slice(&bytes).context("invalid authenticated request")?)
}
fn authenticated(actual: &str, expected: &str) -> bool {
    // Length is not secret; compare every byte for equal-length tokens.
    actual.len() == expected.len()
        && actual
            .as_bytes()
            .iter()
            .zip(expected.as_bytes())
            .fold(0u8, |a, (b, c)| a | (b ^ c))
            == 0
}
fn deliver(stream: &mut TcpStream, response: &Response, stop: &AtomicBool) -> Result<()> {
    let body = serde_json::to_vec(response)?;
    if body.len() > MAX_RESPONSE {
        bail!("response limit exceeded");
    }
    let mut frame = Vec::with_capacity(body.len() + 4);
    frame.extend_from_slice(&(body.len() as u32).to_be_bytes());
    frame.extend_from_slice(&body);
    let deadline = Instant::now() + DELIVERY_TIMEOUT;
    let mut done = 0;
    while done < frame.len() {
        if cancelled(stop, deadline) {
            bail!("response delivery cancelled or expired");
        }
        match stream.write(&frame[done..]) {
            Ok(0) => bail!("response connection closed"),
            Ok(n) => done += n,
            Err(e) if transient(&e) => thread::sleep(TICK),
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}
/// A request is already complete: any further input is terminal, never another
/// command. EOF (including a peer write-half-close), bytes, and socket errors
/// cancel the exchange. A racing close/byte may arrive after the single spawn;
/// cancellation cannot roll back native mutations.
fn peer_cancelled(stream: &TcpStream) -> bool {
    let mut byte = [0];
    match stream.peek(&mut byte) {
        Err(error) if transient(&error) => false,
        _ => true,
    }
}
struct OwnedChild(Child);
impl OwnedChild {
    fn terminate(&mut self) {
        if self.0.try_wait().ok().flatten().is_some() {
            return;
        }
        // Signal only the currently owned child, never a recorded or adopted PID.
        let _ = kill(Pid::from_raw(self.0.id() as i32), Signal::SIGTERM);
        let until = Instant::now() + TERMINATION_TIMEOUT;
        while Instant::now() < until {
            if self.0.try_wait().ok().flatten().is_some() {
                return;
            }
            thread::sleep(TICK);
        }
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
impl Drop for OwnedChild {
    fn drop(&mut self) {
        self.terminate();
    }
}
fn drain(reader: &mut impl Read, output: &mut Vec<u8>, limit: usize) -> Result<bool> {
    let mut buf = [0; 16 * 1024];
    // Bound per-tick work too: a continuous writer must not starve cancellation.
    for _ in 0..16 {
        match reader.read(&mut buf) {
            Ok(0) => return Ok(true),
            Ok(n) => {
                if output.len() + n > limit {
                    bail!("native output limit exceeded");
                }
                output.extend_from_slice(&buf[..n]);
            }
            Err(e) if transient(&e) => return Ok(false),
            Err(e) => return Err(e.into()),
        }
    }
    Ok(false)
}
fn execute(
    config: &Config,
    request: &Request,
    stream: &TcpStream,
    stop: &AtomicBool,
    admission_deadline: Instant,
) -> Result<Response> {
    let private = tempfile::Builder::new().prefix("tic-request-").tempdir()?;
    let home = private.path().join("home");
    let xdg = private.path().join("xdg");
    fs::create_dir(&home)?;
    fs::create_dir(&xdg)?;
    let mut command = Command::new(&config.native_executable);
    command
        .args(&request.argv)
        .current_dir(&config.workspace)
        .env_clear()
        .env("HOME", &home)
        .env("XDG_CONFIG_HOME", &xdg)
        .env("XDG_DATA_HOME", &xdg)
        .env("XDG_CACHE_HOME", &xdg)
        .env("XDG_STATE_HOME", &xdg)
        .env("TICGIT_STATE_FILE", private.path().join("state.json"))
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_COUNT", "3")
        .env("GIT_CONFIG_KEY_0", "user.name")
        .env("GIT_CONFIG_VALUE_0", &config.user_name)
        .env("GIT_CONFIG_KEY_1", "user.email")
        .env("GIT_CONFIG_VALUE_1", &config.user_email)
        .env("GIT_CONFIG_KEY_2", "meta.namespace")
        .env("GIT_CONFIG_VALUE_2", &config.namespace)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if cancelled(stop, admission_deadline) || peer_cancelled(stream) {
        bail!("cancelled before spawn");
    }
    let mut child = OwnedChild(command.spawn().context("native spawn failed")?);
    let deadline = Instant::now() + EXECUTION_TIMEOUT;
    let mut input = child.0.stdin.take();
    let mut output = child.0.stdout.take().unwrap();
    let mut error = child.0.stderr.take().unwrap();
    nonblocking(input.as_ref().unwrap().as_raw_fd())?;
    nonblocking(output.as_raw_fd())?;
    nonblocking(error.as_raw_fd())?;
    let mut written = 0;
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    let mut output_done = false;
    let mut error_done = false;
    let status;
    loop {
        if stop.load(Ordering::Acquire) || peer_cancelled(stream) {
            bail!("request cancelled; native outcome may be unknown");
        }
        if Instant::now() >= deadline {
            child.terminate();
            return Ok(Response::error(
                124,
                "native execution deadline exceeded; inspect results before retrying",
            ));
        }
        if let Some(pipe) = &mut input {
            if written == request.stdin.len() {
                input.take();
            } else {
                match pipe.write(&request.stdin.as_bytes()[written..]) {
                    Ok(0) => {
                        input.take();
                    }
                    Ok(n) => written += n,
                    Err(e) if transient(&e) => {}
                    Err(e) if e.kind() == io::ErrorKind::BrokenPipe => {
                        input.take();
                    }
                    Err(e) => return Err(e.into()),
                }
            }
        }
        if !output_done {
            output_done = drain(&mut output, &mut stdout, MAX_STDOUT)?;
        }
        if !error_done {
            error_done = drain(&mut error, &mut stderr, MAX_STDERR)?;
        }
        if let Some(exit) = child.0.try_wait()? {
            if output_done && error_done {
                status = exit;
                break;
            }
        }
        thread::sleep(TICK);
    }
    use std::os::unix::process::ExitStatusExt;
    Ok(Response {
        version: WIRE_VERSION,
        exit: status
            .code()
            .unwrap_or_else(|| 128 + status.signal().unwrap_or(0)),
        stdout: String::from_utf8(stdout).context("native stdout is not UTF-8")?,
        stderr: String::from_utf8(stderr).context("native stderr is not UTF-8")?,
    })
}
fn serve(mut stream: TcpStream, config: &Config, stop: &AtomicBool, accepted: Instant) {
    if stream.set_nonblocking(true).is_err() {
        return;
    }
    let admission_deadline = accepted + ADMISSION_TIMEOUT;
    let response = match receive(&mut stream, stop, admission_deadline) {
        Err(error) if error.is::<AdmissionRejection>() || error.is::<serde_json::Error>() => {
            Response::error(2, "invalid request framing or JSON")
        }
        Err(_) => Response::error(
            125,
            "request transport incomplete, cancelled, or expired; not executed",
        ),
        Ok(envelope) => {
            let request = envelope.request;
            if !authenticated(&envelope.token, &config.token) {
                Response::error(2, "unauthorized request")
            } else if let Err(error) = validate_request(&request) {
                Response::error(2, error.to_string())
            } else {
                match policy::classify(&request.argv, &request.stdin) {
                    Err(error) => Response::error(2, error),
                    Ok(_) if cancelled(stop, admission_deadline) => Response::error(125, "cancelled before execution"),
                    Ok(policy::Decision::Respond { exit, stdout, stderr }) => Response { version: WIRE_VERSION, exit, stdout, stderr },
                    Ok(policy::Decision::Execute) => match execute(config, &request, &stream, stop, admission_deadline) {
                        Ok(response) => response,
                        Err(_) => Response::error(125, "native transport/output failure or cancellation; outcome may be unknown; inspect before retrying"),
                    },
                }
            }
        }
    };
    let _ = deliver(&mut stream, &response, stop);
}
/// Lifetime FD ownership is transferred to this call. No other broker child may
/// inherit it. EOF closes admission, joins workers (which cancel/reap children),
/// and drops all private directories before returning.
///
/// # Safety
/// `lifetime_fd` must be a valid uniquely-owned inherited read descriptor.
pub unsafe fn run(config: Config, lifetime_fd: RawFd) -> Result<()> {
    if lifetime_fd < 3 {
        bail!("lifetime descriptor must not be standard I/O");
    }
    let flags = FdFlag::from_bits_truncate(fcntl(lifetime_fd, FcntlArg::F_GETFD)?);
    fcntl(lifetime_fd, FcntlArg::F_SETFD(flags | FdFlag::FD_CLOEXEC))?;
    let mut lifetime = unsafe { File::from_raw_fd(lifetime_fd) };
    nonblocking(lifetime_fd)?;
    validate(&config)?;
    let mut initial = [0; 64];
    match lifetime.read(&mut initial) {
        Ok(0) => bail!("owning launch ended before readiness"),
        Ok(_) => {}
        Err(e) if transient(&e) => {}
        Err(e) => return Err(e.into()),
    }
    let listener = TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))?;
    listener.set_nonblocking(true)?;
    let ready = serde_json::to_vec(&Ready {
        version: READINESS_VERSION,
        address: listener.local_addr()?.to_string(),
        native_revision: NATIVE_REVISION,
        policy_version: POLICY_VERSION,
    })?;
    if ready.len() > 1024 {
        bail!("readiness line limit exceeded");
    }
    io::stdout().write_all(&ready)?;
    io::stdout().write_all(b"\n")?;
    io::stdout().flush()?;
    let config = Arc::new(config);
    let stop = Arc::new(AtomicBool::new(false));
    let mut workers: Vec<thread::JoinHandle<()>> = Vec::new();
    let mut failure = None;
    loop {
        let mut byte = [0; 64];
        match lifetime.read(&mut byte) {
            Ok(0) => break,
            Ok(_) => {}
            Err(e) if transient(&e) => {}
            Err(e) => {
                failure = Some(e);
                break;
            }
        }
        let mut index = 0;
        while index < workers.len() {
            if workers[index].is_finished() {
                let _ = workers.swap_remove(index).join();
            } else {
                index += 1;
            }
        }
        // Accept promptly even at capacity: do not let a request wait behind
        // a live command and acquire a fresh admission deadline afterward.
        // Overload has no execution authority and gets a best-effort 125 frame.
        match listener.accept() {
            Ok((mut stream, _)) if workers.len() >= WORKERS => {
                if stream.set_nonblocking(true).is_ok() {
                    if let Ok(body) = serde_json::to_vec(&Response::error(
                        125,
                        "broker at capacity; request not executed",
                    )) {
                        let _ = write_frame(&mut stream, &body, MAX_RESPONSE);
                    }
                }
            }
            Ok((stream, _)) => {
                let accepted = Instant::now();
                let config = Arc::clone(&config);
                let stop = Arc::clone(&stop);
                workers.push(thread::spawn(move || {
                    serve(stream, &config, &stop, accepted)
                }));
            }
            Err(e) if transient(&e) => {}
            Err(e) => {
                failure = Some(e);
                break;
            }
        }
        thread::sleep(TICK);
    }
    stop.store(true, Ordering::Release);
    drop(listener);
    for worker in workers {
        let _ = worker.join();
    }
    if let Some(error) = failure {
        return Err(error.into());
    }
    Ok(())
}
