//! Guest-only file collection and one authenticated exchange. No native execution.
use crate::policy;
use crate::protocol::*;
use clap::{ArgMatches, FromArgMatches};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::sync::mpsc;
use std::time::{Duration, Instant};
use ticgit::cli::Cli;

type Failure = (i32, String);

/// Normalize exactly one native file operand. Clap indices count virtual short
/// options, not raw argv tokens (e.g. `-cFfile`). Instead try suffix replacements
/// and reparse each candidate. A candidate is accepted only if every native
/// parsed value and its source is unchanged except for the identified file field.
/// Thus `-F` inside title/body data and operands after `--` cannot be mistaken for
/// options. This uses Clap's public matches interface, not Debug formatting or a
/// second option grammar. Unknown future fields are included in the comparison.
pub fn normalize(argv: &[String]) -> Result<(Vec<String>, Option<PathBuf>), String> {
    validate_argv(argv).map_err(|e| e.to_string())?;
    let mut original = match policy::parse(argv) {
        Ok(cli) => cli,
        // Help/version (and errors) go to broker policy without native help output.
        Err(_) => {
            policy::classify(argv, "")?;
            return Ok((argv.to_vec(), None));
        }
    };
    let Some(file) = policy::file_mut(&mut original) else {
        policy::classify(argv, "")?;
        return Ok((argv.to_vec(), None));
    };
    let Some(path) = file.clone() else {
        policy::classify(argv, "")?;
        return Ok((argv.to_vec(), None));
    };
    if path == std::path::Path::new("-") {
        policy::classify(argv, "")?;
        return Ok((argv.to_vec(), Some(path)));
    }
    let text = path.to_str().ok_or("file path is not UTF-8")?;
    let expected = policy::parse_matches(argv).map_err(|_| "cannot parse native arguments")?;
    let mut found = None;
    for (index, token) in argv.iter().enumerate() {
        let Some(prefix) = token.strip_suffix(text) else {
            continue;
        };
        let mut candidate = argv.to_vec();
        candidate[index] = format!("{prefix}-");
        if let Ok(parsed) = policy::parse_matches(&candidate) {
            let mut typed =
                Cli::from_arg_matches(&parsed).map_err(|_| "cannot inspect native arguments")?;
            let replaced = policy::file_mut(&mut typed)
                .and_then(|f| f.as_ref())
                .is_some_and(|f| f == std::path::Path::new("-"));
            if replaced && same_except_file(&expected, &parsed) {
                if found.is_some() {
                    return Err("ambiguous native file operand".into());
                }
                found = Some(candidate);
            }
        }
    }
    let normalized = found.ok_or("cannot identify exact native file operand")?;
    policy::classify(&normalized, "")?;
    Ok((normalized, Some(path)))
}

fn same_except_file(left: &ArgMatches, right: &ArgMatches) -> bool {
    let mut left_ids: Vec<_> = left.ids().map(|id| id.as_str()).collect();
    let mut right_ids: Vec<_> = right.ids().map(|id| id.as_str()).collect();
    left_ids.sort_unstable();
    right_ids.sort_unstable();
    if left_ids != right_ids {
        return false;
    }
    for id in left_ids {
        if id == "file" {
            continue;
        }
        if left.value_source(id) != right.value_source(id)
            || left.get_raw(id).map(|v| v.collect::<Vec<_>>())
                != right.get_raw(id).map(|v| v.collect::<Vec<_>>())
        {
            return false;
        }
    }
    match (left.subcommand(), right.subcommand()) {
        (None, None) => true,
        (Some((ln, l)), Some((rn, r))) => ln == rn && same_except_file(l, r),
        _ => false,
    }
}

fn remaining(deadline: Instant) -> Result<Duration, Failure> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|d| !d.is_zero())
        .ok_or((
            125,
            "client exchange deadline exceeded; outcome may be unknown".into(),
        ))
}
fn collect(reader: &mut impl Read) -> Result<String, Failure> {
    let mut bytes = Vec::new();
    reader
        .take((MAX_REQUEST + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|e| (125, format!("cannot read guest input: {e}")))?;
    if bytes.len() > MAX_REQUEST {
        return Err((2, "input limit exceeded".into()));
    }
    String::from_utf8(bytes).map_err(|_| (2, "input is not UTF-8".into()))
}
fn exchange(
    argv: Vec<String>,
    endpoint: String,
    token: String,
    deadline: Instant,
) -> Result<Response, Failure> {
    let (argv, file) = normalize(&argv).map_err(|e| (2, e))?;
    let stdin = match file {
        None => String::new(),
        Some(path) if path == std::path::Path::new("-") => collect(&mut std::io::stdin().lock())?,
        Some(path) => {
            let mut file = std::fs::File::open(path)
                .map_err(|e| (125, format!("cannot open guest input: {e}")))?;
            collect(&mut file)?
        }
    };
    remaining(deadline)?;
    let request = AuthenticatedRequest {
        token,
        request: Request {
            version: WIRE_VERSION,
            command: COMMAND.into(),
            argv,
            stdin,
        },
    };
    let body = serde_json::to_vec(&request).map_err(|e| (125, e.to_string()))?;
    if body.len() > MAX_REQUEST {
        return Err((2, "encoded request limit exceeded".into()));
    }
    // Resolve only the launcher-projected endpoint. Never try a different address
    // after a connection attempt: even connection failure must not cause replay.
    let address = endpoint
        .to_socket_addrs()
        .map_err(|e| (125, format!("invalid endpoint: {e}")))?
        .next()
        .ok_or((125, "endpoint has no address".into()))?;
    let mut stream = TcpStream::connect_timeout(&address, remaining(deadline)?)
        .map_err(|e| (125, format!("cannot connect to broker: {e}")))?;
    // Keep the write side open while waiting. Ordinary readable EOF now means
    // client disappearance to the broker; neither half-close nor reset is part
    // of request framing. There is no retry after this single connection.
    stream
        .set_write_timeout(Some(remaining(deadline)?))
        .map_err(|e| (125, e.to_string()))?;
    write_frame(&mut stream, &body, MAX_REQUEST).map_err(|e| {
        (
            125,
            format!("request transport failed: {e}; inspect before retrying"),
        )
    })?;
    stream
        .set_read_timeout(Some(remaining(deadline)?))
        .map_err(|e| (125, e.to_string()))?;
    let bytes = read_frame(&mut stream, MAX_RESPONSE).map_err(|e| {
        (
            125,
            format!("response transport failed: {e}; outcome unknown; inspect before retrying"),
        )
    })?;
    remaining(deadline)?;
    let response: Response =
        serde_json::from_slice(&bytes).map_err(|e| (125, format!("invalid response: {e}")))?;
    if response.version != WIRE_VERSION
        || response.stdout.len() > MAX_STDOUT
        || response.stderr.len() > MAX_STDERR
    {
        return Err((125, "unsupported or oversized response".into()));
    }
    Ok(response)
}

pub fn main() -> i32 {
    // Starts BEFORE parsing/collecting files, including potentially blocked FIFO
    // opens or stdin reads. On expiry the binary exits, abandoning its worker;
    // there is no fallback or second request. A thread avoids platform-specific
    // file-read cancellation APIs; it never executes native TicGit.
    let deadline = Instant::now() + CLIENT_TIMEOUT;
    let argv = match std::env::args_os()
        .skip(1)
        .map(|s| s.into_string())
        .collect::<Result<Vec<_>, _>>()
    {
        Ok(argv) => argv,
        Err(_) => {
            eprintln!("tic proxy: arguments must be UTF-8");
            return 2;
        }
    };
    let endpoint = match std::env::var("SANDBOX_TIC_ENDPOINT") {
        Ok(s) if !s.is_empty() => s,
        _ => {
            eprintln!("tic proxy: missing launcher endpoint; no fallback");
            return 125;
        }
    };
    let token = match std::env::var("SANDBOX_TIC_TOKEN") {
        Ok(s) if !s.is_empty() => s,
        _ => {
            eprintln!("tic proxy: missing launcher token; no fallback");
            return 125;
        }
    };
    let (tx, rx) = mpsc::sync_channel(1);
    if let Err(error) = std::thread::Builder::new()
        .name("tic-proxy-exchange".into())
        .spawn(move || {
            let _ = tx.send(exchange(argv, endpoint, token, deadline));
        })
    {
        eprintln!("tic proxy: cannot start exchange: {error}");
        return 125;
    }
    let result = rx.recv_timeout(deadline.saturating_duration_since(Instant::now()));
    match result {
        Ok(Ok(response)) => {
            if std::io::stdout()
                .write_all(response.stdout.as_bytes())
                .is_err()
                || std::io::stderr()
                    .write_all(response.stderr.as_bytes())
                    .is_err()
            {
                return 125;
            }
            response.exit
        }
        Ok(Err((exit, error))) => {
            eprintln!("tic proxy: {error}");
            exit
        }
        Err(_) => {
            eprintln!("tic proxy: client exchange failed or exceeded 45 seconds; outcome unknown; inspect before retrying");
            125
        }
    }
}
