//! Version-one typed command wire protocol. One frame per half-closed connection.
use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::time::Duration;

pub const VERSION: u32 = 1;
pub const COMMAND: &str = "tic";
pub const MAX_REQUEST: usize = 8 * 1024 * 1024;
pub const MAX_RESPONSE: usize = 32 * 1024 * 1024;
pub const MAX_STDOUT: usize = 4 * 1024 * 1024;
pub const MAX_STDERR: usize = 256 * 1024;
pub const MAX_ARGC: usize = 128;
pub const MAX_ARG: usize = 64 * 1024;
pub const MAX_ARGS: usize = 256 * 1024;
pub const ADMISSION_TIMEOUT: Duration = Duration::from_secs(10);
pub const EXECUTION_TIMEOUT: Duration = Duration::from_secs(30);
pub const DELIVERY_TIMEOUT: Duration = Duration::from_secs(3);
pub const CLIENT_TIMEOUT: Duration = Duration::from_secs(45);
pub const TERMINATION_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub version: u32,
    pub command: String,
    pub argv: Vec<String>,
    pub stdin: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AuthenticatedRequest {
    pub token: String,
    pub request: Request,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Response {
    pub version: u32,
    pub exit: i32,
    pub stdout: String,
    pub stderr: String,
}
impl Response {
    pub fn error(exit: i32, message: impl Into<String>) -> Self {
        Self {
            version: VERSION,
            exit,
            stdout: String::new(),
            stderr: format!("tic proxy: {}\n", message.into()),
        }
    }
}
pub fn validate_request(request: &Request) -> Result<()> {
    if request.version != VERSION || request.command != COMMAND {
        bail!("unsupported request version or command");
    }
    validate_argv(&request.argv)?;
    if request.stdin.len() > MAX_REQUEST {
        bail!("stdin limit exceeded");
    }
    Ok(())
}
pub fn validate_argv(argv: &[String]) -> Result<()> {
    if argv.len() > MAX_ARGC
        || argv.iter().any(|s| s.len() > MAX_ARG || s.contains('\0'))
        || argv.iter().map(String::len).sum::<usize>() > MAX_ARGS
    {
        bail!("argument limit exceeded or NUL argument");
    }
    Ok(())
}
/// Caller owns the absolute deadline and cancellation of its stream.
pub fn read_frame(reader: &mut impl Read, limit: usize) -> Result<Vec<u8>> {
    let mut header = [0; 4];
    reader.read_exact(&mut header)?;
    let len = u32::from_be_bytes(header) as usize;
    if len > limit {
        bail!("frame limit exceeded");
    }
    let mut body = vec![0; len];
    reader.read_exact(&mut body)?;
    let mut extra = [0];
    if reader.read(&mut extra)? != 0 {
        bail!("trailing frame bytes");
    }
    Ok(body)
}
pub fn write_frame(writer: &mut impl Write, body: &[u8], limit: usize) -> Result<()> {
    if body.len() > limit || body.len() > u32::MAX as usize {
        bail!("frame limit exceeded");
    }
    writer.write_all(&(body.len() as u32).to_be_bytes())?;
    writer.write_all(body)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn duplicate_unknown_and_trailing_data_fail() {
        for text in [
            r#"{"version":1,"version":1,"command":"tic","argv":[],"stdin":""}"#,
            r#"{"version":1,"command":"tic","argv":[],"stdin":"","cwd":"/"}"#,
        ] {
            assert!(serde_json::from_str::<Request>(text).is_err());
        }
        let mut frame = Vec::new();
        write_frame(&mut frame, b"{}", 8).unwrap();
        assert_eq!(read_frame(&mut &frame[..], 8).unwrap(), b"{}");
        frame.push(0);
        assert!(read_frame(&mut &frame[..], 8).is_err());
        assert!(read_frame(&mut &[0, 0, 0, 9][..], 8).is_err());
    }
}
