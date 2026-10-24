use clap::Parser;
use std::path::PathBuf;

#[derive(Parser)]
#[command(about = "Launcher-owned TicGit command broker (not a native server)")]
struct Args {
    #[arg(long)]
    config: PathBuf,
    #[arg(long)]
    lifetime_fd: i32,
}
#[derive(Parser)]
#[command(
    name = "tic-broker inspect-context",
    about = "Inspect explicit repository metadata without loading host configuration or ticket storage"
)]
struct InspectArgs {
    #[arg(long)]
    workspace: PathBuf,
    #[arg(long)]
    common_dir: PathBuf,
}
fn main() {
    if std::env::args_os()
        .nth(1)
        .is_some_and(|arg| arg == "inspect-context")
    {
        let arguments = std::iter::once(std::ffi::OsString::from("tic-broker inspect-context"))
            .chain(std::env::args_os().skip(2));
        let args = match InspectArgs::try_parse_from(arguments) {
            Ok(args) => args,
            Err(_) => {
                eprintln!(
                    "tic-broker: inspect-context requires --workspace ROOT --common-dir COMMON"
                );
                std::process::exit(2);
            }
        };
        let result = tic_proxy::inspect::inspect_context(&args.workspace, &args.common_dir);
        match result {
            Ok(bytes) => {
                use std::io::Write;
                if std::io::stdout().lock().write_all(&bytes).is_err() {
                    eprintln!("tic-broker: context output delivery failed");
                    std::process::exit(1);
                }
            }
            Err(error) => {
                // Fixed diagnostic classes only; never forward repository
                // paths, file contents, or environment values.
                eprintln!("tic-broker: context inspection failed: {error}");
                std::process::exit(1);
            }
        }
        return;
    }
    let args = Args::parse();
    let result = tic_proxy::broker::load_config(&args.config).and_then(|config| {
        // The launcher transfers the inherited read descriptor exclusively.
        unsafe { tic_proxy::broker::run(config, args.lifetime_fd) }
    });
    if let Err(error) = result {
        // Never serialize config, token, request bytes, or native environment.
        eprintln!("tic-broker: startup/lifetime failure: {error:#}");
        std::process::exit(1);
    }
}
