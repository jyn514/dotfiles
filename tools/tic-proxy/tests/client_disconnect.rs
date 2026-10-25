//! A real binary deadline closes its still-open request side with ordinary EOF.
use std::io::Read;
use std::net::TcpListener;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use tic_proxy::protocol::*;

#[test]
fn absolute_client_deadline_closes_quiet_connection_with_readable_eof() {
    let owned = tempfile::tempdir().unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = listener.local_addr().unwrap().to_string();
    let (tx, rx) = std::sync::mpsc::channel();
    let observer = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_millis(100)))
            .unwrap();
        let envelope: AuthenticatedRequest =
            serde_json::from_slice(&read_frame_body(&mut stream, MAX_REQUEST).unwrap()).unwrap();
        assert_eq!(envelope.request.argv, ["list"]);
        assert_eq!(envelope.request.version, WIRE_VERSION);
        let mut byte = [0];
        // Before the deadline there must be neither EOF nor more request bytes.
        assert!(stream.read(&mut byte).is_err());
        tx.send(()).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(46)))
            .unwrap();
        assert_eq!(stream.read(&mut byte).unwrap(), 0);
    });
    let start = Instant::now();
    let child = Command::new(env!("CARGO_BIN_EXE_ti-proxy"))
        .env_clear()
        .current_dir(owned.path())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("SANDBOX_TIC_ENDPOINT", endpoint)
        .env("SANDBOX_TIC_TOKEN", "owned-test-token")
        .arg("list")
        .spawn()
        .unwrap();
    rx.recv_timeout(Duration::from_secs(5))
        .expect("client did not keep request side open");
    let output = child.wait_with_output().unwrap();
    assert_eq!(output.status.code(), Some(125));
    assert!(start.elapsed() >= Duration::from_secs(44));
    assert!(start.elapsed() < Duration::from_secs(50));
    observer.join().unwrap();
}
