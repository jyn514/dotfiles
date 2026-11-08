//! Shared Unix subprocess I/O and ownership for the JJ and TicGit brokers.
//! Included as a source module by both binaries; no separately deployed library.
use nix::fcntl::{fcntl, FcntlArg, OFlag};
use nix::sys::signal::{kill, Signal};
use nix::unistd::Pid;
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::thread;
use std::time::{Duration, Instant};

/// These are the two existing ownership contracts, not command authorization.
/// Session callers must establish a new session in pre_exec. On Linux the runner
/// adopts and reaps its descendants before returning (and before leases drop).
/// Child callers own only the direct child, with a TERM grace period on failure.
#[derive(Clone, Copy)]
#[allow(dead_code)] // Each broker compiles only its own ownership contract.
pub enum Ownership {
    Session,
    Child { grace: Duration },
}

#[derive(Clone, Copy)]
#[allow(dead_code)] // JJ has an admission deadline; TicGit starts a fresh budget.
pub enum Deadline {
    Absolute(Instant),
    AfterSpawn(Duration),
}

/// JJ retains at most limit+1 bytes, closes each saturated pipe, and leaves the
/// overflow decision to its caller. TicGit rejects overflow immediately. Read
/// failures discard that stream in JJ's capture mode, but fail TicGit requests.
#[derive(Clone, Copy)]
#[allow(dead_code)] // Consumers deliberately select different overflow policies.
pub enum OutputLimit {
    Capture(usize),
    Reject(usize),
}

pub struct Limits {
    pub ownership: Ownership,
    pub deadline: Deadline,
    pub stdout: OutputLimit,
    pub stderr: OutputLimit,
    pub tick: Duration,
}

pub struct Output {
    pub status: Option<ExitStatus>,
    pub timed_out: bool,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

fn transient(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
    )
}

fn nonblocking(fd: &impl AsRawFd) -> io::Result<()> {
    let flags = OFlag::from_bits_truncate(fcntl(fd.as_raw_fd(), FcntlArg::F_GETFL)?);
    fcntl(fd.as_raw_fd(), FcntlArg::F_SETFL(flags | OFlag::O_NONBLOCK))?;
    Ok(())
}

struct OwnedChild {
    child: Child,
    ownership: Ownership,
    tick: Duration,
    cleaned: bool,
}

impl OwnedChild {
    fn cleanup(&mut self) -> io::Result<()> {
        if self.cleaned {
            return Ok(());
        }
        match self.ownership {
            Ownership::Session => {
                let group = Pid::from_raw(-(self.child.id() as i32));
                let _ = kill(group, Signal::SIGKILL);
                let _ = self.child.wait();
                // Descendants retain the repository lease. Reap the whole group
                // even if the leader exited normally while they held its pipes.
                #[cfg(target_os = "linux")]
                loop {
                    match nix::sys::wait::waitpid(group, None) {
                        Ok(_) | Err(nix::errno::Errno::EINTR) => continue,
                        Err(nix::errno::Errno::ECHILD) => break,
                        Err(error) => return Err(error.into()),
                    }
                }
            }
            Ownership::Child { grace } => {
                if self.child.try_wait().ok().flatten().is_none() {
                    // Never signal a recorded/adopted PID in child-only mode.
                    let _ = kill(Pid::from_raw(self.child.id() as i32), Signal::SIGTERM);
                    let until = Instant::now() + grace;
                    while Instant::now() < until {
                        if self.child.try_wait().ok().flatten().is_some() {
                            self.cleaned = true;
                            return Ok(());
                        }
                        thread::sleep(self.tick);
                    }
                    let _ = self.child.kill();
                    let _ = self.child.wait();
                }
            }
        }
        self.cleaned = true;
        Ok(())
    }
}

impl Drop for OwnedChild {
    fn drop(&mut self) {
        let _ = self.cleanup();
    }
}

fn drain<R: Read>(
    pipe: &mut Option<R>,
    output: &mut Vec<u8>,
    limit: OutputLimit,
) -> io::Result<()> {
    let mut buf = [0; 16 * 1024];
    // Continuous writers must not starve deadlines, stdin, or cancellation.
    for _ in 0..16 {
        let Some(reader) = pipe.as_mut() else {
            return Ok(());
        };
        let capacity = match limit {
            OutputLimit::Capture(max) => buf.len().min(max + 1 - output.len()),
            OutputLimit::Reject(_) => buf.len(),
        };
        match reader.read(&mut buf[..capacity]) {
            Ok(0) => {
                pipe.take();
                return Ok(());
            }
            Ok(n) => {
                if let OutputLimit::Reject(max) = limit {
                    if output.len() + n > max {
                        return Err(io::Error::other("native output limit exceeded"));
                    }
                }
                output.extend_from_slice(&buf[..n]);
                if let OutputLimit::Capture(max) = limit {
                    if output.len() > max {
                        pipe.take();
                        return Ok(());
                    }
                }
            }
            Err(error) if transient(&error) => return Ok(()),
            Err(_) if matches!(limit, OutputLimit::Capture(_)) => {
                output.clear();
                pipe.take();
                return Ok(());
            }
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

/// Spawn the already-configured command, capture bounded byte streams, and own
/// cleanup through success, timeout, cancellation, and I/O failures. Environment,
/// cwd, confinement, session creation, identity, locks and protocol stay outside.
/// `input=None` preserves the caller's stdin configuration; `Some` pipes bytes and
/// closes stdin after writing. Cancellation runs while the process/pipes are live.
/// A timeout returns captured bytes and no status; callers choose response policy.
pub fn run(
    command: &mut Command,
    input: Option<&[u8]>,
    limits: Limits,
    mut check_cancellation: impl FnMut() -> io::Result<()>,
) -> io::Result<Output> {
    #[cfg(target_os = "linux")]
    if matches!(limits.ownership, Ownership::Session) {
        nix::sys::prctl::set_child_subreaper(true)?;
    }
    if let Deadline::Absolute(deadline) = limits.deadline {
        if Instant::now() >= deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "request deadline exceeded before starting jj",
            ));
        }
    }
    if input.is_some() {
        command.stdin(Stdio::piped());
    }
    let child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let deadline = match limits.deadline {
        Deadline::Absolute(deadline) => deadline,
        Deadline::AfterSpawn(timeout) => Instant::now() + timeout,
    };
    let mut child = OwnedChild {
        child,
        ownership: limits.ownership,
        tick: limits.tick,
        cleaned: false,
    };
    let mut stdin = if input.is_some() {
        child.child.stdin.take()
    } else {
        None
    };
    let mut stdout_pipe = child.child.stdout.take();
    let mut stderr_pipe = child.child.stderr.take();
    if let Some(pipe) = &stdin {
        nonblocking(pipe)?;
    }
    nonblocking(stdout_pipe.as_ref().unwrap())?;
    nonblocking(stderr_pipe.as_ref().unwrap())?;
    let mut written = 0;
    let mut result = Output {
        status: None,
        timed_out: false,
        stdout: Vec::new(),
        stderr: Vec::new(),
    };
    loop {
        check_cancellation()?;
        if !child.cleaned && matches!(limits.ownership, Ownership::Session) {
            result.status = child.child.try_wait()?;
            if result.status.is_some() {
                child.cleanup()?;
            }
        }
        // JJ's deadline bounds leader execution, not collection after cleanup.
        // TicGit's deadline also bounds pipes retained after the leader exits.
        if !child.cleaned && Instant::now() >= deadline {
            result.timed_out = true;
            child.cleanup()?;
            if matches!(limits.ownership, Ownership::Child { .. }) {
                return Ok(result);
            }
        }
        if let Some(pipe) = &mut stdin {
            let bytes = input.unwrap();
            if written == bytes.len() {
                stdin.take();
            } else {
                match pipe.write(&bytes[written..]) {
                    Ok(0) => {
                        stdin.take();
                    }
                    Ok(n) => written += n,
                    Err(error) if transient(&error) => {}
                    Err(error) if error.kind() == io::ErrorKind::BrokenPipe => {
                        stdin.take();
                    }
                    Err(error) => return Err(error),
                }
            }
        }
        drain(&mut stdout_pipe, &mut result.stdout, limits.stdout)?;
        drain(&mut stderr_pipe, &mut result.stderr, limits.stderr)?;
        if !result.timed_out && matches!(limits.ownership, Ownership::Child { .. }) {
            result.status = child.child.try_wait()?;
        }
        if (result.status.is_some() || result.timed_out)
            && stdout_pipe.is_none()
            && stderr_pipe.is_none()
        {
            child.cleanup()?;
            return Ok(result);
        }
        thread::sleep(limits.tick);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::os::unix::process::CommandExt;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            static SERIAL: AtomicUsize = AtomicUsize::new(0);
            let path = std::env::temp_dir().join(format!(
                "bounded-process-{}-{}",
                std::process::id(),
                SERIAL.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn command(&self, mode: &str) -> Command {
            let test = format!("{}::fixture", module_path!().split_once("::").unwrap().1);
            let mut command = Command::new(std::env::current_exe().unwrap());
            command
                .args(["--exact", &test, "--nocapture", "--quiet"])
                .env("BOUNDED_PROCESS_FIXTURE", mode)
                .env("BOUNDED_PROCESS_ROOT", &self.0);
            command
        }
        fn pid(&self, name: &str) -> i32 {
            fs::read_to_string(self.0.join(name))
                .unwrap()
                .parse()
                .unwrap()
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn fixture() {
        let Ok(mode) = std::env::var("BOUNDED_PROCESS_FIXTURE") else {
            return;
        };
        let root = PathBuf::from(std::env::var_os("BOUNDED_PROCESS_ROOT").unwrap());
        fs::write(root.join(&mode), std::process::id().to_string()).unwrap();
        match mode.as_str() {
            "echo" => {
                io::stdout().write_all(&vec![b'a'; 512 * 1024]).unwrap();
                io::stderr().write_all(&vec![b'b'; 512 * 1024]).unwrap();
                let mut bytes = Vec::new();
                io::stdin().read_to_end(&mut bytes).unwrap();
                io::stdout().write_all(&bytes).unwrap();
                std::process::exit(7);
            }
            "capture" => {
                io::stdout().write_all(&vec![b'a'; 2000]).unwrap();
                io::stderr().write_all(&vec![b'b'; 2000]).unwrap();
                std::process::exit(0);
            }
            "flood" => loop {
                let _ = io::stdout().write_all(&[b'a'; 16 * 1024]);
            },
            "leader" => {
                let this = Fixture(root.clone());
                let _descendant = this.command("descendant").spawn().unwrap();
                while !root.join("descendant").exists() {
                    thread::sleep(Duration::from_millis(1));
                }
                std::mem::forget(this);
                std::process::exit(0);
            }
            "ignore-term" => {
                unsafe {
                    nix::sys::signal::signal(Signal::SIGTERM, nix::sys::signal::SigHandler::SigIgn)
                        .unwrap();
                }
                // Publish readiness after installing the handler.
                fs::write(root.join("ready"), "").unwrap();
                loop {
                    thread::sleep(Duration::from_secs(1));
                }
            }
            "descendant" => loop {
                thread::sleep(Duration::from_secs(1));
            },
            _ => panic!("unknown fixture mode"),
        }
    }

    fn child_limits() -> Limits {
        Limits {
            ownership: Ownership::Child {
                grace: Duration::from_millis(30),
            },
            deadline: Deadline::AfterSpawn(Duration::from_secs(5)),
            stdout: OutputLimit::Reject(2 << 20),
            stderr: OutputLimit::Reject(2 << 20),
            tick: Duration::from_millis(1),
        }
    }
    fn assert_reaped(pid: i32) {
        assert_eq!(
            kill(Pid::from_raw(pid), None),
            Err(nix::errno::Errno::ESRCH)
        );
    }
    fn session(command: &mut Command) {
        unsafe {
            command.pre_exec(|| nix::unistd::setsid().map(|_| ()).map_err(io::Error::from));
        }
    }

    #[test]
    fn concurrent_stdin_stdout_stderr_and_eof_preserve_bytes_and_exit() {
        let fixture = Fixture::new();
        let input = vec![b'c'; 512 * 1024];
        let output = run(
            &mut fixture.command("echo"),
            Some(&input),
            child_limits(),
            || Ok(()),
        )
        .unwrap();
        assert!(!output.timed_out);
        assert_eq!(output.status.unwrap().code(), Some(7));
        assert!(output.stdout.ends_with(&input));
        assert!(output
            .stdout
            .windows(512 * 1024)
            .any(|bytes| bytes == vec![b'a'; 512 * 1024]));
        assert_eq!(output.stderr, vec![b'b'; 512 * 1024]);
        assert_reaped(fixture.pid("echo"));
    }

    #[test]
    fn capture_retains_overflow_sentinel_instead_of_rejecting() {
        let fixture = Fixture::new();
        let mut command = fixture.command("capture");
        session(&mut command);
        let output = run(
            &mut command,
            None,
            Limits {
                ownership: Ownership::Session,
                deadline: Deadline::Absolute(Instant::now() + Duration::from_secs(5)),
                stdout: OutputLimit::Capture(1024),
                stderr: OutputLimit::Capture(1024),
                tick: Duration::from_millis(1),
            },
            || Ok(()),
        )
        .unwrap();
        assert_eq!(output.status.unwrap().code(), Some(0));
        assert_eq!(output.stdout.len(), 1025);
        assert_eq!(output.stderr.len(), 1025);
    }

    #[test]
    fn rejecting_overflow_stops_a_continuous_writer_and_reaps_it() {
        let fixture = Fixture::new();
        let mut limits = child_limits();
        limits.stdout = OutputLimit::Reject(1024);
        let error = run(&mut fixture.command("flood"), None, limits, || Ok(()))
            .err()
            .unwrap();
        assert!(error.to_string().contains("output limit"));
        assert_reaped(fixture.pid("flood"));
    }

    #[test]
    fn cancellation_escalates_ignored_term_and_reaps_before_return() {
        let fixture = Fixture::new();
        let error = run(
            &mut fixture.command("ignore-term"),
            None,
            child_limits(),
            || {
                if fixture.0.join("ready").exists() {
                    Err(io::Error::other("cancelled"))
                } else {
                    Ok(())
                }
            },
        )
        .err()
        .unwrap();
        assert_eq!(error.to_string(), "cancelled");
        assert_reaped(fixture.pid("ignore-term"));
    }

    #[test]
    fn timeout_reaps_child_and_preserves_timeout_observation() {
        let fixture = Fixture::new();
        let mut limits = child_limits();
        limits.deadline = Deadline::AfterSpawn(Duration::from_millis(150));
        let output = run(&mut fixture.command("ignore-term"), None, limits, || Ok(())).unwrap();
        assert!(output.timed_out);
        assert!(output.status.is_none());
        assert_reaped(fixture.pid("ignore-term"));
    }

    #[test]
    fn expired_absolute_deadline_does_not_spawn() {
        let fixture = Fixture::new();
        let mut limits = child_limits();
        limits.deadline = Deadline::Absolute(Instant::now() - Duration::from_secs(1));
        assert_eq!(
            run(&mut fixture.command("capture"), None, limits, || Ok(()))
                .err()
                .unwrap()
                .kind(),
            io::ErrorKind::TimedOut
        );
        assert!(!fixture.0.join("capture").exists());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn session_reaps_descendants_after_successful_leader_exit() {
        let fixture = Fixture::new();
        let mut command = fixture.command("leader");
        session(&mut command);
        let mut limits = child_limits();
        limits.ownership = Ownership::Session;
        let output = run(&mut command, None, limits, || Ok(())).unwrap();
        assert!(!output.timed_out);
        assert_eq!(output.status.unwrap().code(), Some(0));
        assert_reaped(fixture.pid("leader"));
        assert_reaped(fixture.pid("descendant"));
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn child_only_timeout_does_not_signal_descendants() {
        nix::sys::prctl::set_child_subreaper(true).unwrap();
        let fixture = Fixture::new();
        let mut command = fixture.command("leader");
        session(&mut command);
        let mut limits = child_limits();
        limits.deadline = Deadline::AfterSpawn(Duration::from_millis(150));
        let output = run(&mut command, None, limits, || Ok(())).unwrap();
        let descendant = Pid::from_raw(fixture.pid("descendant"));
        let alive = kill(descendant, None);
        let _ = kill(descendant, Signal::SIGKILL);
        nix::sys::wait::waitpid(descendant, None).unwrap();
        assert!(output.timed_out, "descendant retains the pipes");
        assert_eq!(
            alive,
            Ok(()),
            "child-only mode must not acquire descendant ownership"
        );
        assert_reaped(fixture.pid("leader"));
    }
}
