use std::io::Write;
use std::net::{Shutdown, TcpListener};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use tic_proxy::protocol::*;
fn command(dir: &std::path::Path) -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_ti-proxy"));
    cmd.env_clear()
        .current_dir(dir)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    cmd
}
fn server() -> (String, std::thread::JoinHandle<AuthenticatedRequest>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = listener.local_addr().unwrap().to_string();
    let handle = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        let request =
            serde_json::from_slice(&read_frame_body(&mut stream, MAX_REQUEST).unwrap()).unwrap();
        let response = Response {
            version: WIRE_VERSION,
            exit: 7,
            stdout: "native output\n".into(),
            stderr: "native error\n".into(),
        };
        write_frame(
            &mut stream,
            &serde_json::to_vec(&response).unwrap(),
            MAX_RESPONSE,
        )
        .unwrap();
        stream.shutdown(Shutdown::Write).unwrap();
        request
    });
    (endpoint, handle)
}
#[test]
fn relative_guest_only_files_and_literal_dash_cross_as_bytes_not_paths() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::create_dir(dir.path().join("guest-only")).unwrap();
    for (file, text) in [
        ("guest-only/draft", "new title\n\nbody 雪\n"),
        ("-", "literal dash"),
        ("empty", ""),
    ] {
        std::fs::write(dir.path().join(file), text).unwrap();
        let (endpoint, broker) = server();
        let operand = if file == "-" { "./-" } else { file };
        let output = command(dir.path())
            .env("SANDBOX_TIC_ENDPOINT", endpoint)
            .env("SANDBOX_TIC_TOKEN", "test-secret")
            .args(["edit", "-F", operand])
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(7),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(output.stdout, b"native output\n");
        assert_eq!(output.stderr, b"native error\n");
        let request = broker.join().unwrap();
        assert_eq!(request.token, "test-secret");
        assert_eq!(request.request.stdin, text);
        assert_eq!(request.request.argv, ["edit", "-F", "-"]);
    }
}
#[test]
fn caller_stdin_is_collected_only_for_native_stdin_file_operand() {
    let dir = tempfile::tempdir().unwrap();
    let (endpoint, broker) = server();
    let mut child = command(dir.path())
        .env("SANDBOX_TIC_ENDPOINT", endpoint)
        .env("SANDBOX_TIC_TOKEN", "secret")
        .args(["writeup", "edit", "id", "-F-"])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"title only\n")
        .unwrap();
    assert_eq!(child.wait_with_output().unwrap().status.code(), Some(7));
    let request = broker.join().unwrap();
    assert_eq!(request.request.stdin, "title only\n");
    assert_eq!(request.request.argv, ["writeup", "edit", "id", "-F-"]);
}
#[test]
fn collection_errors_and_encoded_overflow_never_connect_or_fall_back() {
    let dir = tempfile::tempdir().unwrap();
    // A nonblocking listener proves all these errors occur before a connection.
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    std::fs::write(dir.path().join("invalid"), [0xff, 0xfe]).unwrap();
    std::fs::write(dir.path().join("oversize"), vec![b'x'; 8 * 1024 * 1024 + 1]).unwrap();
    // Decoded input fits but JSON escaping cannot fit an 8 MiB frame.
    std::fs::write(dir.path().join("encoded"), vec![0; 2 * 1024 * 1024]).unwrap();
    for (file, code) in [
        ("missing", 125),
        ("invalid", 2),
        ("oversize", 2),
        ("encoded", 2),
    ] {
        let output = command(dir.path())
            .env(
                "SANDBOX_TIC_ENDPOINT",
                listener.local_addr().unwrap().to_string(),
            )
            .env("SANDBOX_TIC_TOKEN", "secret")
            .args(["edit", "-F", file])
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(code),
            "{file}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(
            listener.accept().unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
    }
    assert_eq!(
        command(dir.path())
            .arg("list")
            .output()
            .unwrap()
            .status
            .code(),
        Some(125)
    );
}
#[test]
fn lost_response_is_unknown_and_never_replayed() {
    let dir = tempfile::tempdir().unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = listener.local_addr().unwrap();
    let accepted = listener.try_clone().unwrap();
    let broker = std::thread::spawn(move || {
        let (mut stream, _) = accepted.accept().unwrap();
        read_frame_body(&mut stream, MAX_REQUEST).unwrap();
        // It may have mutated tickets before dying. No response can establish
        // success or failure, so the client must never send the request again.
    });
    let output = command(dir.path())
        .env("SANDBOX_TIC_ENDPOINT", endpoint.to_string())
        .env("SANDBOX_TIC_TOKEN", "secret")
        .args(["new", "-t", "title"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(125));
    assert!(String::from_utf8_lossy(&output.stderr).contains("outcome unknown"));
    broker.join().unwrap();
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
}

#[test]
fn invalid_response_fails_closed() {
    let dir = tempfile::tempdir().unwrap();
    for body in [
        br#"{"version":1,"exit":0,"stdout":"","stderr":""}"#.to_vec(),
        br#"{"version":1,"exit":0,"stdout":"","stderr":"","extra":true}"#.to_vec(),
        b"not JSON".to_vec(),
    ] {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = listener.local_addr().unwrap();
        let broker = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            read_frame_body(&mut stream, MAX_REQUEST).unwrap();
            write_frame(&mut stream, &body, MAX_RESPONSE).unwrap();
            stream.shutdown(Shutdown::Write).unwrap();
        });
        let output = command(dir.path())
            .env("SANDBOX_TIC_ENDPOINT", endpoint.to_string())
            .env("SANDBOX_TIC_TOKEN", "secret")
            .arg("list")
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(125));
        broker.join().unwrap();
    }
}
#[test]
fn blocked_stdin_collection_has_one_absolute_45_second_budget() {
    let dir = tempfile::tempdir().unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let start = Instant::now();
    let mut child = command(dir.path())
        .env(
            "SANDBOX_TIC_ENDPOINT",
            listener.local_addr().unwrap().to_string(),
        )
        .env("SANDBOX_TIC_TOKEN", "secret")
        .args(["edit", "-F-"])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    // Also exercise a FIFO blocked at open(), before any file read. Both must
    // consume the SAME absolute budget, not a socket timeout started afterward.
    #[cfg(unix)]
    let fifo_child = {
        nix::unistd::mkfifo(
            &dir.path().join("blocked"),
            nix::sys::stat::Mode::S_IRUSR | nix::sys::stat::Mode::S_IWUSR,
        )
        .unwrap();
        command(dir.path())
            .env(
                "SANDBOX_TIC_ENDPOINT",
                listener.local_addr().unwrap().to_string(),
            )
            .env("SANDBOX_TIC_TOKEN", "secret")
            .args(["edit", "-Fblocked"])
            .spawn()
            .unwrap()
    };
    // Keep the pipe writer alive: EOF cannot explain the client's exit.
    let writer = child.stdin.take().unwrap();
    let output = child.wait_with_output().unwrap();
    drop(writer);
    #[cfg(unix)]
    assert_eq!(
        fifo_child.wait_with_output().unwrap().status.code(),
        Some(125)
    );
    assert_eq!(output.status.code(), Some(125));
    assert!(start.elapsed() >= Duration::from_secs(44));
    assert!(start.elapsed() < Duration::from_secs(50));
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
}
