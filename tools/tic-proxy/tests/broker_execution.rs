//! Contract regressions: real native store sharing, strict direct requests, and
//! process ownership. Fake executables are used only for execution-bound edges.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{Read, Write},
    net::{Shutdown, TcpStream},
    os::{
        fd::{AsRawFd, OwnedFd},
        unix::fs::PermissionsExt,
    },
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};
use tempfile::TempDir;
use tic_proxy::{broker::NATIVE_REVISION, protocol::*};

const TOKEN: &str = "0123456789abcdef0123456789abcdef";
struct Repos {
    _root: TempDir,
    main: PathBuf,
    linked: PathBuf,
}
impl Repos {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let main = root.path().join("main");
        let linked = root.path().join("linked");
        fs::create_dir(&main).unwrap();
        let this = Self {
            _root: root,
            main,
            linked,
        };
        this.git(&["init", "-qb", "main"]);
        this.git(&[
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "initial",
        ]);
        this.git(&[
            "worktree",
            "add",
            "-qb",
            "linked",
            this.linked.to_str().unwrap(),
        ]);
        this
    }
    fn git(&self, args: &[&str]) {
        let output = Command::new("git")
            .current_dir(&self.main)
            .env("GIT_CONFIG_NOSYSTEM", "1")
            .env("GIT_CONFIG_GLOBAL", "/dev/null")
            .args(args)
            .output()
            .unwrap();
        assert!(output.status.success(), "git {args:?}: {output:?}");
    }
    fn fake(&self, mode: &str) -> PathBuf {
        fs::write(self.main.join("fixture-mode"), mode).unwrap();
        let native = self._root.path().join("fixture-native");
        fs::copy(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/broker-fixtures/native.py"),
            &native,
        )
        .unwrap();
        fs::set_permissions(&native, fs::Permissions::from_mode(0o700)).unwrap();
        manifest(&native);
        native
    }
}
fn manifest(native: &Path) {
    let sha256 = format!("{:x}", Sha256::digest(fs::read(native).unwrap()));
    fs::write(
        format!("{}.tic-proxy.json", native.display()),
        serde_json::to_vec(
            &json!({"native_revision":NATIVE_REVISION,"policy_version":1,"sha256":sha256}),
        )
        .unwrap(),
    )
    .unwrap();
}
fn native() -> PathBuf {
    std::env::var_os("TIC_PROXY_TEST_NATIVE")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../target/tic-proxy-build/cargo/debug/ti")
        })
        .canonicalize()
        .expect("build pinned native first with build-local")
}
struct Broker {
    child: Child,
    lifetime: Option<OwnedFd>,
    address: String,
}
impl Broker {
    fn command(repos: &Repos, workspace: &Path, native: &Path) -> (Command, OwnedFd, OwnedFd) {
        let sha256 = format!("{:x}", Sha256::digest(fs::read(native).unwrap()));
        let path = repos._root.path().join(format!(
            "config-{}.json",
            workspace.file_name().unwrap().to_string_lossy()
        ));
        fs::write(&path, serde_json::to_vec(&json!({"version":1,"workspace":workspace,"common_dir":repos.main.join(".git"),"native_executable":native,"native_sha256":sha256,"user_name":"Broker Fixture","user_email":"broker@example.invalid","namespace":"tickets","token":TOKEN})).unwrap()).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        let (read, write) = nix::unistd::pipe().unwrap();
        // Keep only the broker read end inheritable; parent owns the write end.
        nix::fcntl::fcntl(
            write.as_raw_fd(),
            nix::fcntl::FcntlArg::F_SETFD(nix::fcntl::FdFlag::FD_CLOEXEC),
        )
        .unwrap();
        let mut command = Command::new(env!("CARGO_BIN_EXE_tic-broker"));
        command
            .args([
                "--config",
                path.to_str().unwrap(),
                "--lifetime-fd",
                &read.as_raw_fd().to_string(),
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("SECRET_CREDENTIAL", "must-not-cross")
            .env("GIT_CONFIG_COUNT", "1")
            .env("GIT_CONFIG_KEY_0", "user.email")
            .env("GIT_CONFIG_VALUE_0", "attacker@example.invalid")
            .env("EDITOR", "/host/helper")
            .env("SSH_AUTH_SOCK", "/host/socket");
        (command, read, write)
    }
    fn start(repos: &Repos, workspace: &Path, native: &Path) -> Self {
        let (mut command, read, write) = Self::command(repos, workspace, native);
        let mut child = command.spawn().unwrap();
        drop(read);
        let mut out = child.stdout.take().unwrap();
        let (tx, rx) = std::sync::mpsc::channel();
        thread::spawn(move || {
            let mut line = Vec::new();
            let mut byte = [0];
            while out.read(&mut byte).unwrap_or(0) != 0 {
                line.push(byte[0]);
                if byte[0] == b'\n' || line.len() > 1024 {
                    break;
                }
            }
            let _ = tx.send(line);
        });
        let mut this = Self {
            child,
            lifetime: Some(write),
            address: String::new(),
        };
        let line = rx
            .recv_timeout(Duration::from_secs(10))
            .expect("readiness deadline");
        let ready: Value =
            serde_json::from_slice(&line).unwrap_or_else(|e| panic!("readiness {line:?}: {e}"));
        assert_eq!(ready["version"], 1);
        assert_eq!(ready["native_revision"], NATIVE_REVISION);
        assert_eq!(ready["policy_version"], 1);
        this.address = ready["address"].as_str().unwrap().into();
        assert!(this.address.starts_with("127.0.0.1:"));
        this
    }
    fn raw(&self, bytes: &[u8]) -> Response {
        let mut stream = TcpStream::connect(&self.address).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(40)))
            .unwrap();
        write_frame(&mut stream, bytes, MAX_REQUEST).unwrap();
        stream.shutdown(Shutdown::Write).unwrap();
        let body = read_frame(&mut stream, MAX_RESPONSE).unwrap();
        serde_json::from_slice(&body).unwrap()
    }
    fn request(&self, argv: &[&str], stdin: &str) -> Response {
        self.raw(&serde_json::to_vec(&json!({"token":TOKEN,"request":{"version":1,"command":"tic","argv":argv,"stdin":stdin}})).unwrap())
    }
    fn stop(&mut self) {
        self.lifetime.take();
        let until = Instant::now() + Duration::from_secs(5);
        while Instant::now() < until {
            if self.child.try_wait().unwrap().is_some() {
                return;
            }
            thread::sleep(Duration::from_millis(10));
        }
        self.child.kill().unwrap();
        self.child.wait().unwrap();
        panic!("broker failed lifetime shutdown bound");
    }
}
impl Drop for Broker {
    fn drop(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            self.lifetime.take();
            let until = Instant::now() + Duration::from_secs(5);
            while Instant::now() < until {
                if self.child.try_wait().ok().flatten().is_some() {
                    return;
                }
                thread::sleep(Duration::from_millis(10));
            }
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}
fn success(response: Response) -> String {
    assert_eq!(response.exit, 0, "{}", response.stderr);
    response.stdout
}

#[test]
fn real_native_main_linked_human_share_store_and_readiness_never_creates_it() {
    let repos = Repos::new();
    let native = native();
    let mut main = Broker::start(&repos, &repos.main, &native);
    let linked = Broker::start(&repos, &repos.linked, &native);
    assert!(
        !repos.main.join(".git/git-meta.sqlite").exists(),
        "readiness must not open SQLite"
    );
    let id = success(main.request(&["new", "--title", "broker main", "--id-only"], ""))
        .trim()
        .to_string();
    success(linked.request(&["new", "--title", "broker linked", "--id-only"], ""));
    let human = Command::new(&native)
        .current_dir(&repos.linked)
        .env_clear()
        .env("HOME", repos._root.path())
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_COUNT", "3")
        .env("GIT_CONFIG_KEY_0", "user.name")
        .env("GIT_CONFIG_VALUE_0", "Human Fixture")
        .env("GIT_CONFIG_KEY_1", "user.email")
        .env("GIT_CONFIG_VALUE_1", "human@example.invalid")
        .env("GIT_CONFIG_KEY_2", "meta.namespace")
        .env("GIT_CONFIG_VALUE_2", "tickets")
        .env(
            "TICGIT_STATE_FILE",
            repos._root.path().join("human-ui.json"),
        )
        .args(["new", "--title", "human linked", "--id-only"])
        .output()
        .unwrap();
    assert!(human.status.success(), "{human:?}");
    for broker in [&main, &linked] {
        let list = success(broker.request(&["list", "--json"], ""));
        for title in ["broker main", "broker linked", "human linked"] {
            assert!(list.contains(title), "{list}");
        }
    }
    let history = success(linked.request(&["history", "--ticket", &id, "--json"], ""));
    assert!(
        history.contains("Broker Fixture") || history.contains("broker@example.invalid"),
        "{history}"
    );
    assert!(repos.main.join(".git/git-meta.sqlite").exists());
    assert!(!repos
        .main
        .join(".git/worktrees/linked/git-meta.sqlite")
        .exists());
    assert!(!repos.linked.join(".ticgit-state.json").exists());
    main.stop();
    success(linked.request(&["list", "--json"], ""));
}

#[test]
fn direct_auth_framing_and_policy_rejections_do_not_spawn() {
    let repos = Repos::new();
    let native = repos.fake("environment");
    let broker = Broker::start(&repos, &repos.main, &native);
    for (argv, input) in [
        (vec!["setup"], ""),
        (vec!["mine"], ""),
        (vec!["edit", "-F", "/etc/passwd"], ""),
        (vec!["list"], "unexpected"),
        (vec!["new"], ""),
    ] {
        assert_eq!(broker.request(&argv, input).exit, 2);
    }
    assert_eq!(broker.raw(br#"{"token":"wrong","request":{"version":1,"command":"tic","argv":[],"stdin":""}}"#).exit, 2);
    assert_eq!(broker.raw(format!(r#"{{"token":"{TOKEN}","token":"{TOKEN}","request":{{"version":1,"command":"tic","argv":[],"stdin":""}}}}"#).as_bytes()).exit, 2);
    assert!(!repos.main.join("fixture-started").exists());
    let mut stream = TcpStream::connect(&broker.address).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(12)))
        .unwrap();
    let bytes = serde_json::to_vec(
        &json!({"token":TOKEN,"request":{"version":1,"command":"tic","argv":[],"stdin":""}}),
    )
    .unwrap();
    write_frame(&mut stream, &bytes, MAX_REQUEST).unwrap();
    stream.write_all(b"x").unwrap();
    stream.shutdown(Shutdown::Write).unwrap();
    let response: Response =
        serde_json::from_slice(&read_frame(&mut stream, MAX_RESPONSE).unwrap()).unwrap();
    assert_eq!(response.exit, 2);
    assert!(!repos.main.join("fixture-started").exists());
}

#[test]
fn fixed_environment_exact_stdin_and_argv_and_native_status() {
    let repos = Repos::new();
    let native = repos.fake("environment");
    let broker = Broker::start(&repos, &repos.main, &native);
    let response = success(broker.request(&["new", "-F", "-"], "title\n\nbody α\n"));
    let value: Value = serde_json::from_str(&response).unwrap();
    assert_eq!(value["argv"], json!(["new", "-F", "-"]));
    assert_eq!(value["stdin"], "title\n\nbody α\n");
    assert_eq!(value["cwd"], repos.main.to_str().unwrap());
    let env = value["env"].as_object().unwrap();
    for key in [
        "SECRET_CREDENTIAL",
        "EDITOR",
        "SSH_AUTH_SOCK",
        "PATH",
        "GIT_DIR",
        "GIT_WORK_TREE",
    ] {
        assert!(!env.contains_key(key), "inherited {key}");
    }
    assert_eq!(env["GIT_CONFIG_COUNT"], "3");
    assert_eq!(env["GIT_CONFIG_VALUE_0"], "Broker Fixture");
    assert_eq!(env["GIT_CONFIG_VALUE_1"], "broker@example.invalid");
    assert_eq!(env["GIT_CONFIG_GLOBAL"], "/dev/null");
    let home = Path::new(env["HOME"].as_str().unwrap());
    assert!(
        !home.exists(),
        "request-private directory must be removed before response"
    );
    fs::write(repos.main.join("fixture-mode"), "exit").unwrap();
    let response = broker.request(&["list"], "");
    assert_eq!(response.exit, 17);
    assert_eq!(response.stdout, "native stdout\n");
    assert_eq!(response.stderr, "native stderr\n");
}

#[test]
fn output_limits_and_invalid_utf8_fail_without_wedging_later_requests() {
    let repos = Repos::new();
    let native = repos.fake("output");
    let broker = Broker::start(&repos, &repos.main, &native);
    for mode in ["output", "stderr", "invalid-utf8"] {
        fs::write(repos.main.join("fixture-mode"), mode).unwrap();
        assert_eq!(broker.request(&["list"], "").exit, 125);
    }
    fs::write(repos.main.join("fixture-mode"), "exit").unwrap();
    assert_eq!(broker.request(&["list"], "").exit, 17);
}

#[test]
fn lifetime_eof_cancels_reaps_native_and_closes_listener_without_affecting_other_launch() {
    let repos = Repos::new();
    let native = repos.fake("sleep");
    let mut broker = Broker::start(&repos, &repos.main, &native);
    let other = Broker::start(&repos, &repos.main, &native);
    let mut stream = TcpStream::connect(&broker.address).unwrap();
    let bytes = serde_json::to_vec(
        &json!({"token":TOKEN,"request":{"version":1,"command":"tic","argv":["list"],"stdin":""}}),
    )
    .unwrap();
    write_frame(&mut stream, &bytes, MAX_REQUEST).unwrap();
    stream.shutdown(Shutdown::Write).unwrap();
    let until = Instant::now() + Duration::from_secs(5);
    while !repos.main.join("fixture-started").exists() {
        assert!(Instant::now() < until);
        thread::sleep(Duration::from_millis(10));
    }
    let pid: i32 = fs::read_to_string(repos.main.join("fixture-started"))
        .unwrap()
        .parse()
        .unwrap();
    let before = Instant::now();
    broker.stop();
    assert!(before.elapsed() < Duration::from_secs(5));
    assert!(
        nix::sys::signal::kill(nix::unistd::Pid::from_raw(pid), None).is_err(),
        "owned child not reaped"
    );
    assert!(TcpStream::connect(&broker.address).is_err());
    fs::write(repos.main.join("fixture-mode"), "exit").unwrap();
    assert_eq!(other.request(&["list"], "").exit, 17);
}

#[test]
fn readiness_rejects_wrong_build_hash_or_policy_binding_without_opening_store() {
    for field in ["sha256", "native_revision", "policy_version"] {
        let repos = Repos::new();
        let native = repos.fake("exit");
        let manifest_path = format!("{}.tic-proxy.json", native.display());
        let mut value: Value = serde_json::from_slice(&fs::read(&manifest_path).unwrap()).unwrap();
        value[field] = if field == "policy_version" {
            json!(2)
        } else {
            json!("wrong")
        };
        fs::write(&manifest_path, serde_json::to_vec(&value).unwrap()).unwrap();
        let (mut command, _read, _write) = Broker::command(&repos, &repos.main, &native);
        let output = command.output().unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        assert!(!repos.main.join(".git/git-meta.sqlite").exists());
    }
}

#[test]
fn admission_absolute_deadline_does_not_spawn_and_later_requests_work() {
    let repos = Repos::new();
    let native = repos.fake("exit");
    let broker = Broker::start(&repos, &repos.main, &native);
    let mut stream = TcpStream::connect(&broker.address).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(12)))
        .unwrap();
    stream.write_all(&[0, 0]).unwrap();
    let started = Instant::now();
    let response: Response =
        serde_json::from_slice(&read_frame(&mut stream, MAX_RESPONSE).unwrap()).unwrap();
    assert_eq!(response.exit, 125);
    assert!(started.elapsed() >= Duration::from_secs(9));
    assert!(started.elapsed() < Duration::from_secs(12));
    assert!(!repos.main.join("fixture-started").exists());
    assert_eq!(broker.request(&["list"], "").exit, 17);
}

#[test]
fn execution_deadline_includes_blocked_native_stdin_then_reaps() {
    let repos = Repos::new();
    let native = repos.fake("sleep");
    let broker = Broker::start(&repos, &repos.main, &native);
    let started = Instant::now();
    let response = broker.request(&["new", "-F", "-"], &"x".repeat(1024 * 1024));
    assert_eq!(response.exit, 124);
    assert!(started.elapsed() >= Duration::from_secs(30));
    assert!(started.elapsed() < Duration::from_secs(35));
    let pid: i32 = fs::read_to_string(repos.main.join("fixture-started"))
        .unwrap()
        .parse()
        .unwrap();
    assert!(nix::sys::signal::kill(nix::unistd::Pid::from_raw(pid), None).is_err());
    fs::write(repos.main.join("fixture-mode"), "exit").unwrap();
    assert_eq!(broker.request(&["list"], "").exit, 17);
}

#[test]
fn lifetime_eof_during_incomplete_admission_never_spawns() {
    let repos = Repos::new();
    let native = repos.fake("exit");
    let mut broker = Broker::start(&repos, &repos.main, &native);
    let mut stream = TcpStream::connect(&broker.address).unwrap();
    stream.write_all(&[0, 0]).unwrap();
    let before = Instant::now();
    broker.stop();
    assert!(before.elapsed() < Duration::from_secs(2));
    assert!(!repos.main.join("fixture-started").exists());
}

#[test]
fn concurrent_real_native_brokers_and_human_retain_native_outcomes() {
    let repos = Repos::new();
    let native = native();
    let main = Broker::start(&repos, &repos.main, &native);
    let linked = Broker::start(&repos, &repos.linked, &native);
    success(main.request(&["list", "--json"], ""));
    let barrier = std::sync::Barrier::new(3);
    let outcomes = thread::scope(|scope| {
        let a = scope.spawn(|| {
            barrier.wait();
            (
                "parallel main",
                main.request(&["new", "--title", "parallel main", "--id-only"], "")
                    .exit,
            )
        });
        let b = scope.spawn(|| {
            barrier.wait();
            (
                "parallel linked",
                linked
                    .request(&["new", "--title", "parallel linked", "--id-only"], "")
                    .exit,
            )
        });
        let c = scope.spawn(|| {
            barrier.wait();
            let output = Command::new(&native)
                .current_dir(&repos.linked)
                .env_clear()
                .env("HOME", repos._root.path())
                .env("GIT_CONFIG_NOSYSTEM", "1")
                .env("GIT_CONFIG_GLOBAL", "/dev/null")
                .env("GIT_CONFIG_COUNT", "3")
                .env("GIT_CONFIG_KEY_0", "user.name")
                .env("GIT_CONFIG_VALUE_0", "Human")
                .env("GIT_CONFIG_KEY_1", "user.email")
                .env("GIT_CONFIG_VALUE_1", "human@example.invalid")
                .env("GIT_CONFIG_KEY_2", "meta.namespace")
                .env("GIT_CONFIG_VALUE_2", "tickets")
                .env(
                    "TICGIT_STATE_FILE",
                    repos._root.path().join("human-private-state"),
                )
                .args(["new", "--title", "parallel human", "--id-only"])
                .output()
                .unwrap();
            ("parallel human", output.status.code().unwrap_or(128))
        });
        vec![a.join().unwrap(), b.join().unwrap(), c.join().unwrap()]
    });
    assert!(outcomes.iter().any(|(_, code)| *code == 0), "{outcomes:?}");
    let list = success(linked.request(&["list", "--json"], ""));
    for (title, status) in outcomes {
        // Native SQLite contention/partial mutations retain native semantics.
        // The broker must neither add serialization nor replay a failed create.
        assert!(
            ![2, 124, 125].contains(&status),
            "non-native outcome {status}"
        );
        if status == 0 {
            assert_eq!(list.matches(title).count(), 1, "{list}");
        }
    }
}

#[test]
fn reset_disconnect_cancels_and_reaps_live_child() {
    let repos = Repos::new();
    let native = repos.fake("sleep");
    let broker = Broker::start(&repos, &repos.main, &native);
    let mut stream = TcpStream::connect(&broker.address).unwrap();
    let bytes = serde_json::to_vec(
        &json!({"token":TOKEN,"request":{"version":1,"command":"tic","argv":["list"],"stdin":""}}),
    )
    .unwrap();
    write_frame(&mut stream, &bytes, MAX_REQUEST).unwrap();
    stream.shutdown(Shutdown::Write).unwrap();
    let until = Instant::now() + Duration::from_secs(5);
    while !repos.main.join("fixture-started").exists() {
        assert!(Instant::now() < until);
        thread::sleep(Duration::from_millis(10));
    }
    let pid: i32 = fs::read_to_string(repos.main.join("fixture-started"))
        .unwrap()
        .parse()
        .unwrap();
    let linger = nix::libc::linger {
        l_onoff: 1,
        l_linger: 0,
    };
    // A reset is observable after request half-close; a second graceful FIN is
    // not. Do not mislabel this as universal graceful-disconnect detection.
    assert_eq!(
        unsafe {
            nix::libc::setsockopt(
                stream.as_raw_fd(),
                nix::libc::SOL_SOCKET,
                nix::libc::SO_LINGER,
                &linger as *const _ as *const nix::libc::c_void,
                std::mem::size_of_val(&linger) as nix::libc::socklen_t,
            )
        },
        0
    );
    drop(stream);
    let until = Instant::now() + Duration::from_secs(5);
    while nix::sys::signal::kill(nix::unistd::Pid::from_raw(pid), None).is_ok() {
        assert!(Instant::now() < until, "reset child was not reaped");
        thread::sleep(Duration::from_millis(10));
    }
    fs::write(repos.main.join("fixture-mode"), "exit").unwrap();
    assert_eq!(broker.request(&["list"], "").exit, 17);
}

#[test]
fn blocked_response_delivery_expires_instead_of_retaining_worker() {
    let repos = Repos::new();
    let native = repos.fake("maximum");
    let broker = Broker::start(&repos, &repos.main, &native);
    let mut blocked = Vec::new();
    // Fill the bounded worker set with non-reading peers. Reading their partial
    // frames afterward would measure TCP receive-window draining, not the
    // broker's delivery deadline. A ninth successful request proves release.
    for _ in 0..8 {
        let mut stream = TcpStream::connect(&broker.address).unwrap();
        let size: nix::libc::c_int = 4096;
        assert_eq!(
            unsafe {
                nix::libc::setsockopt(
                    stream.as_raw_fd(),
                    nix::libc::SOL_SOCKET,
                    nix::libc::SO_RCVBUF,
                    &size as *const _ as *const nix::libc::c_void,
                    std::mem::size_of_val(&size) as nix::libc::socklen_t,
                )
            },
            0
        );
        let bytes = serde_json::to_vec(&json!({"token":TOKEN,"request":{"version":1,"command":"tic","argv":["list"],"stdin":""}})).unwrap();
        write_frame(&mut stream, &bytes, MAX_REQUEST).unwrap();
        stream.shutdown(Shutdown::Write).unwrap();
        blocked.push(stream);
    }
    thread::sleep(Duration::from_secs(6));
    fs::write(repos.main.join("fixture-mode"), "exit").unwrap();
    let mut stream = TcpStream::connect(&broker.address).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    let bytes = serde_json::to_vec(
        &json!({"token":TOKEN,"request":{"version":1,"command":"tic","argv":["list"],"stdin":""}}),
    )
    .unwrap();
    write_frame(&mut stream, &bytes, MAX_REQUEST).unwrap();
    stream.shutdown(Shutdown::Write).unwrap();
    let response: Response =
        serde_json::from_slice(&read_frame(&mut stream, MAX_RESPONSE).unwrap()).unwrap();
    assert_eq!(response.exit, 17);
    drop(blocked);
}

#[test]
fn saturated_workers_reject_new_requests_without_queueing_or_spawning() {
    let repos = Repos::new();
    let native = repos.fake("sleep");
    let mut broker = Broker::start(&repos, &repos.main, &native);
    let mut active = Vec::new();
    let bytes = serde_json::to_vec(
        &json!({"token":TOKEN,"request":{"version":1,"command":"tic","argv":["list"],"stdin":""}}),
    )
    .unwrap();
    for _ in 0..8 {
        let mut stream = TcpStream::connect(&broker.address).unwrap();
        write_frame(&mut stream, &bytes, MAX_REQUEST).unwrap();
        stream.shutdown(Shutdown::Write).unwrap();
        active.push(stream);
    }
    let until = Instant::now() + Duration::from_secs(5);
    while fs::read_to_string(repos.main.join("fixture-pids"))
        .unwrap_or_default()
        .lines()
        .count()
        != 8
    {
        assert!(Instant::now() < until);
        thread::sleep(Duration::from_millis(10));
    }
    let mut excess = TcpStream::connect(&broker.address).unwrap();
    excess
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    // Do not send a request: rejection at capacity must not depend on receiving
    // it, and must not reserve another admission worker or native child.
    let response: Response =
        serde_json::from_slice(&read_frame(&mut excess, MAX_RESPONSE).unwrap()).unwrap();
    assert_eq!(response.exit, 125);
    assert_eq!(
        fs::read_to_string(repos.main.join("fixture-pids"))
            .unwrap()
            .lines()
            .count(),
        8
    );
    broker.stop();
    drop(active);
}

#[test]
fn ordinary_subdirectory_startup_rejects_and_root_cwd_ignores_later_nested_repository() {
    let repos = Repos::new();
    let native = native();
    let subdir = repos.main.join("ordinary-subdirectory");
    fs::create_dir(&subdir).unwrap();
    let (mut command, _read, _write) = Broker::command(&repos, &subdir, &native);
    let output = command.output().unwrap();
    assert!(
        !output.status.success(),
        "ordinary subdirectory must not become accepted cwd"
    );
    assert!(
        output.stdout.is_empty(),
        "rejected startup must not publish readiness"
    );
    assert!(!repos.main.join(".git/git-meta.sqlite").exists());

    let broker = Broker::start(&repos, &repos.main, &native);
    // The guest may create a repository in ordinary checkout contents after
    // readiness. A fixed root invocation cannot rediscover that descendant.
    let output = Command::new("git")
        .args(["init", "-qb", "nested"])
        .current_dir(&subdir)
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
    success(broker.request(&["new", "--title", "fixed root context", "--id-only"], ""));
    let list = success(broker.request(&["list", "--json"], ""));
    assert!(list.contains("fixed root context"), "{list}");
    assert!(repos.main.join(".git/git-meta.sqlite").exists());
    assert!(
        !subdir.join(".git/git-meta.sqlite").exists(),
        "native cwd/store authority was redirected into descendant repository"
    );
}
