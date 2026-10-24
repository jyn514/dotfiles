//! A real binary deadline after strict request EOF must still reach its peer.
use std::net::TcpListener;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use tic_proxy::protocol::*;

#[test]
fn absolute_client_deadline_resets_quiet_connection_after_normal_request_eof() {
    let owned = tempfile::tempdir().unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = listener.local_addr().unwrap().to_string();
    let (tx, rx) = std::sync::mpsc::channel();
    let observer = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let envelope: AuthenticatedRequest =
            serde_json::from_slice(&read_frame(&mut stream, MAX_REQUEST).unwrap()).unwrap();
        assert_eq!(envelope.request.argv, ["list"]);
        tx.send(()).unwrap(); // Complete strict frame + write-half-close + EOF.
                              // No response traffic: the reset itself must be observable after EOF.
        let until = Instant::now() + Duration::from_secs(48);
        loop {
            if let Some(error) = stream.take_error().unwrap() {
                assert!(
                    [Some(nix::libc::EPIPE), Some(nix::libc::ECONNRESET)]
                        .contains(&error.raw_os_error()),
                    "{error:?}"
                );
                return;
            }
            assert!(
                Instant::now() < until,
                "client exit silently became normal framing EOF"
            );
            std::thread::sleep(Duration::from_millis(10));
        }
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
        .expect("client did not finish strict request EOF");
    let output = child.wait_with_output().unwrap();
    assert_eq!(output.status.code(), Some(125));
    assert!(start.elapsed() >= Duration::from_secs(44));
    assert!(start.elapsed() < Duration::from_secs(50));
    observer.join().unwrap();
}
