use color_eyre::eyre::{bail, eyre, Result};
use std::collections::HashSet;

const COMMANDS: &[&str] = &[
    "status", "diff", "log", "show", "interdiff", "commit", "describe",
    "new", "split", "squash", "rebase", "restore", "abandon", "duplicate",
    "edit", "next", "prev", "undo", "workspace",
];

const FORBIDDEN_OPTIONS: &[&str] = &[
    "--repository", "-R", "--workspace", "--config", "--config-file",
    "--config-toml", "--operation", "--at-operation", "--tool", "--editor",
    "--pager", "--sign", "--signing-key", "--ssh-command",
];

fn option_name(arg: &str) -> &str {
    arg.split_once('=').map_or(arg, |pair| pair.0)
}

fn reject_security_options(args: &[String]) -> Result<()> {
    for arg in args {
        let option = option_name(arg);
        if FORBIDDEN_OPTIONS.contains(&option)
            || arg.starts_with("-R")
            || option.starts_with("--config-")
            || option.starts_with("--repository-")
        {
            bail!("security-sensitive option is not allowed: {option}");
        }
    }
    Ok(())
}

pub fn validate(argv: &[String], remotes: &HashSet<String>) -> Result<()> {
    if argv.is_empty() || argv.len() > 256 {
        bail!("expected between 1 and 256 arguments");
    }
    if argv.iter().any(|arg| arg.contains('\0') || arg.len() > 65_536) {
        bail!("argument contains NUL or is too long");
    }

    let command = argv[0].as_str();
    if COMMANDS.contains(&command) {
        return reject_security_options(&argv[1..]);
    }
    if command == "bookmark" {
        let subcommand = argv.get(1).map(String::as_str).unwrap_or("");
        if !["create", "delete", "forget", "list", "move", "rename", "set", "track", "untrack"].contains(&subcommand) {
            bail!("bookmark subcommand is not allowed");
        }
        return reject_security_options(&argv[2..]);
    }
    if command == "git" && argv.get(1).map(String::as_str) == Some("fetch") {
        reject_security_options(&argv[2..])?;
        let mut i = 2;
        let mut selected_remote = false;
        while i < argv.len() {
            let arg = &argv[i];
            let remote = if arg == "--remote" {
                i += 1;
                Some(argv.get(i).ok_or_else(|| eyre!("--remote requires a value"))?.as_str())
            } else {
                arg.strip_prefix("--remote=")
            };
            if let Some(remote) = remote {
                selected_remote = true;
                if !remotes.contains(remote) {
                    bail!("remote is not approved: {remote}");
                }
            }
            i += 1;
        }
        if !selected_remote && remotes.is_empty() {
            bail!("no remotes are approved");
        }
        return Ok(());
    }
    bail!("command is not allowed: {command}")
}

#[cfg(test)]
mod tests {
    use super::*;
    fn check(args: &[&str]) -> bool {
        validate(&args.iter().map(|s| s.to_string()).collect::<Vec<_>>(), &HashSet::from(["origin".into()])).is_ok()
    }
    #[test]
    fn leaves_ordinary_validation_to_jj() {
        assert!(check(&["log", "--future-jj-option", "value"]));
        assert!(check(&["commit", "-m", "literal; $(touch nope)", "src/main.rs"]));
        assert!(check(&["git", "fetch", "--remote", "origin", "--branch", "main"]));
        assert!(check(&["workspace", "list"]));
    }
    #[test]
    fn rejects_escape_surfaces() {
        for args in [
            &["util", "exec", "sh"][..], &["debug", "operation"][..], &["git", "push"][..],
            &["git", "init"][..], &["config", "set", "x", "y"][..], &["diff", "--tool", "/tmp/x"][..],
            &["status", "--repository", "/tmp/x"][..], &["log", "--config", "aliases.x=util exec"][..],
            &["workspace", "list", "--repository", "/tmp/x"][..],
            &["git", "fetch", "--remote", "evil"][..], &["push"][..],
        ] { assert!(!check(args), "accepted {args:?}"); }
    }
}
