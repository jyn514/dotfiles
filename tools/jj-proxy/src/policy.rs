use color_eyre::eyre::{bail, eyre, Result};
use serde::Deserialize;
use std::collections::HashSet;
use std::sync::OnceLock;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CommandKind {
    Standard,
    GitFetch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Decision {
    pub kind: CommandKind,
    pub read_only: bool,
    pub updates_author: bool,
    pub argv: Vec<String>,
}

#[derive(Deserialize)]
struct PolicyFile {
    global: GlobalPolicy,
    command: Vec<CommandRule>,
}

#[derive(Deserialize)]
struct GlobalPolicy {
    forbidden_options: Vec<String>,
    forbidden_prefixes: Vec<String>,
}

#[derive(Deserialize)]
struct CommandRule {
    path: Vec<String>,
    #[serde(default)]
    prefix: bool,
    modes: Vec<String>,
    #[serde(default = "standard_kind")]
    kind: String,
    #[serde(default)]
    approved_remote: bool,
    #[serde(default)]
    updates_author: bool,
}

fn standard_kind() -> String { "standard".to_owned() }

static POLICY: OnceLock<PolicyFile> = OnceLock::new();

fn policy() -> &'static PolicyFile {
    POLICY.get_or_init(|| {
        toml::from_str(include_str!("../policy.toml"))
            .expect("embedded jj-proxy policy.toml must be valid")
    })
}

fn option_name(arg: &str) -> &str { arg.split_once('=').map_or(arg, |pair| pair.0) }

fn reject_security_options(args: &[String]) -> Result<()> {
    let global = &policy().global;
    for arg in args {
        let option = option_name(arg);
        if global.forbidden_options.iter().any(|forbidden| forbidden == option)
            || arg.starts_with("-R")
            || global.forbidden_prefixes.iter().any(|prefix| option.starts_with(prefix))
        {
            bail!("security-sensitive option is not allowed: {option}");
        }
    }
    Ok(())
}

fn matches(rule: &CommandRule, argv: &[String]) -> bool {
    argv.len() >= rule.path.len()
        && rule.path.iter().zip(argv).all(|(expected, actual)| expected == actual)
        && (rule.prefix || argv.first() == rule.path.first())
}

fn rule_for(argv: &[String], inspect: bool) -> Result<&CommandRule> {
    let mode = if inspect { "inspect" } else { "mutate" };
    policy()
        .command
        .iter()
        .find(|rule| matches(rule, argv) && rule.modes.iter().any(|candidate| candidate == mode))
        .ok_or_else(|| eyre!("command is not allowed: {}", argv.first().map(String::as_str).unwrap_or("")))
}

/// Separate the global repository selector before command-policy validation.
/// The trusted server resolves the value; no client-provided access mode follows it.
pub fn extract_repository(argv: &[String]) -> Result<(Option<String>, Vec<String>)> {
    let mut repository = None;
    let mut command = Vec::with_capacity(argv.len());
    let mut index = 0;
    let mut positional = false;
    while index < argv.len() {
        let arg = &argv[index];
        if arg == "--" { positional = true; }
        let value = if !positional && (arg == "-R" || arg == "--repository") {
            index += 1;
            Some(argv.get(index).ok_or_else(|| eyre!("{arg} requires a path"))?.as_str())
        } else if !positional {
            arg.strip_prefix("--repository=").or_else(|| arg.strip_prefix("-R"))
        } else { None };
        if let Some(value) = value {
            if repository.is_some() { bail!("repository selector may appear only once"); }
            if value.is_empty() || value.contains('\0') { bail!("repository selector is empty or invalid"); }
            repository = Some(value.to_owned());
        } else { command.push(arg.clone()); }
        index += 1;
    }
    Ok((repository, command))
}

pub fn validate_inspect(argv: &[String]) -> Result<Decision> { validate_for_mode(argv, true, &HashSet::new()) }

pub fn validate(argv: &[String], remotes: &HashSet<String>) -> Result<Decision> { validate_for_mode(argv, false, remotes) }

fn validate_for_mode(argv: &[String], inspect: bool, remotes: &HashSet<String>) -> Result<Decision> {
    validate_shape(argv)?;
    let rule = rule_for(argv, inspect)?;
    reject_security_options(&argv[rule.path.len()..])?;
    let mut selected_remote = false;
    if rule.approved_remote {
        let mut index = rule.path.len();
        while index < argv.len() {
            let arg = &argv[index];
            let remote = if arg == "--remote" {
                index += 1;
                Some(argv.get(index).ok_or_else(|| eyre!("--remote requires a value"))?.as_str())
            } else { arg.strip_prefix("--remote=") };
            if let Some(remote) = remote {
                selected_remote = true;
                if !remotes.contains(remote) { bail!("remote is not approved: {remote}"); }
            }
            index += 1;
        }
        if !selected_remote && remotes.is_empty() { bail!("no remotes are approved"); }
    }
    let mut normalized_argv = argv.to_vec();
    if rule.approved_remote && !selected_remote {
        normalized_argv.extend(remotes.iter().flat_map(|remote| ["--remote".to_owned(), remote.clone()]));
    }
    Ok(Decision {
        kind: match rule.kind.as_str() {
            "standard" => CommandKind::Standard,
            "git-fetch" => CommandKind::GitFetch,
            other => return Err(eyre!("unknown command kind in policy: {other}")),
        },
        read_only: inspect,
        updates_author: rule.updates_author,
        argv: normalized_argv,
    })
}

fn validate_shape(argv: &[String]) -> Result<()> {
    if argv.is_empty() || argv.len() > 256 { bail!("expected between 1 and 256 arguments"); }
    if argv.iter().any(|arg| arg.contains('\0') || arg.len() > 65_536) { bail!("argument contains NUL or is too long"); }
    Ok(())
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
        assert!(check(&["op", "log"]));
        assert!(!check(&["op", "log", "--at-operation", "@-"]));
        assert!(check(&["help"]));
        assert!(check(&["git", "root"]));
        assert!(check(&["commit", "-m", "literal; $(touch nope)", "src/main.rs"]));
        assert!(check(&["git", "fetch", "--remote", "origin", "--branch", "main"]));
        assert!(check(&["workspace", "list"]));
        assert!(check(&["file", "show", "src/main.rs"]));
    }
    #[test]
    fn decisions_describe_execution_effects() {
        let commit = validate(&["commit".into()], &HashSet::new()).unwrap();
        assert_eq!(commit.kind, CommandKind::Standard);
        assert!(commit.updates_author);
        assert!(!commit.read_only);
        let fetch = validate(&["git".into(), "fetch".into()], &HashSet::from(["origin".into()])).unwrap();
        assert_eq!(fetch.kind, CommandKind::GitFetch);
        assert_eq!(fetch.argv, ["git", "fetch", "--remote", "origin"]);
    }
    #[test]
    fn rejects_escape_surfaces() {
        for args in [
            &["util", "exec", "sh"][..], &["debug", "operation"][..], &["op", "restore", "@-"][..], &["git", "push"][..],
            &["git", "init"][..], &["config", "set", "x", "y"][..], &["diff", "--tool", "/tmp/x"][..],
            &["status", "--repository", "/tmp/x"][..], &["log", "--config", "aliases.x=util exec"][..],
            &["workspace", "list", "--repository", "/tmp/x"][..], &["file", "show", "--repository", "/tmp/x", "src/main.rs"][..],
            &["git", "fetch", "--remote", "evil"][..], &["push"][..],
        ] { assert!(!check(args), "accepted {args:?}"); }
    }
    #[test]
    fn inspection_accepts_only_observational_commands() {
        let check = |args: &[&str]| validate_inspect(&args.iter().map(|value| (*value).to_owned()).collect::<Vec<_>>()).is_ok();
        assert!(check(&["file", "show", "src/main.rs"]));
        assert!(check(&["workspace", "list"]));
        assert!(check(&["op", "log"]));
        assert!(check(&["op", "log", "--no-graph"]));
        assert!(!check(&["op", "log", "--at-operation", "@-"]));
        for args in [
            &["op", "restore", "@-"][..], &["file", "track", "src/main.rs"][..], &["file", "untrack", "src/main.rs"][..],
            &["file", "chmod", "+x", "src/main.rs"][..], &["workspace", "add", "other"][..], &["status", "--repository", "/src/other"][..],
        ] { assert!(!check(args), "accepted {args:?}"); }
    }
    #[test]
    fn repository_selector_is_extracted_once_without_hiding_other_options() {
        for input in [vec!["-R", "/src/other", "status"], vec!["-R/src/other", "status"], vec!["--repository", "/src/other", "status"], vec!["status", "--repository=/src/other"]] {
            let args = input.into_iter().map(str::to_owned).collect::<Vec<_>>();
            let (repo, command) = extract_repository(&args).unwrap();
            assert_eq!(repo.as_deref(), Some("/src/other"));
            assert_eq!(command, ["status"]);
        }
        for input in [vec!["-R", "/src/one", "-R", "/src/two", "status"], vec!["--repository=", "status"], vec!["-R"]] {
            assert!(extract_repository(&input.into_iter().map(str::to_owned).collect::<Vec<_>>()).is_err());
        }
        let (_, command) = extract_repository(&["status", "--", "-R", "/src/other"].map(str::to_owned)).unwrap();
        assert!(validate_inspect(&command).is_err());
    }
}
