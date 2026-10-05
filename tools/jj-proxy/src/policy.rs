use color_eyre::eyre::{bail, eyre, Result};
use serde::Deserialize;
use std::collections::{BTreeMap, HashSet};
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
#[serde(deny_unknown_fields)]
struct PolicyFile {
    global: GlobalPolicy,
    inspect: BTreeMap<String, RuleSpec>,
    mutate: BTreeMap<String, RuleSpec>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GlobalPolicy {
    forbidden_options: Vec<String>,
    forbidden_prefixes: Vec<String>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum RuleSpec {
    Enabled(bool),
    Details(RuleDetails),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RuleDetails {
    subcmds: Option<Vec<String>>,
    #[serde(default)]
    updates_author: bool,
}

struct CommandRule {
    path: Vec<String>,
    updates_author: bool,
}

struct Policy {
    global: GlobalPolicy,
    inspect: Vec<CommandRule>,
    mutate: Vec<CommandRule>,
}

fn command_token(value: &str) -> Result<()> {
    if value.is_empty() || value.contains('\0') || value.chars().any(char::is_whitespace) {
        bail!("policy command must be one nonempty token: {value:?}");
    }
    Ok(())
}

fn expand_rules(specs: BTreeMap<String, RuleSpec>) -> Result<Vec<CommandRule>> {
    let mut rules = Vec::new();
    for (command, spec) in specs {
        command_token(&command)?;
        let spec = match spec {
            RuleSpec::Enabled(true) => RuleDetails { subcmds: None, updates_author: false },
            RuleSpec::Enabled(false) => bail!("policy rule must be true or a table; omit {command} to deny it"),
            RuleSpec::Details(details) => details,
        };
        match spec.subcmds {
            None => rules.push(CommandRule { path: vec![command], updates_author: spec.updates_author }),
            Some(subcmds) => {
                if subcmds.is_empty() { bail!("policy subcmds must not be empty: {command}"); }
                for subcmd in subcmds {
                    command_token(&subcmd)?;
                    rules.push(CommandRule { path: vec![command.clone(), subcmd], updates_author: spec.updates_author });
                }
            }
        }
    }
    Ok(rules)
}

impl Policy {
    fn parse(text: &str) -> Result<Self> {
        let file: PolicyFile = toml::from_str(text)?;
        Ok(Self {
            global: file.global,
            inspect: expand_rules(file.inspect)?,
            mutate: expand_rules(file.mutate)?,
        })
    }

    fn rule_for(&self, argv: &[String], inspect: bool) -> Result<&CommandRule> {
        // Mutation entries take precedence; inspection permissions are inherited.
        self.mutate.iter().filter(|_| !inspect).chain(self.inspect.iter())
            .find(|rule| argv.starts_with(&rule.path))
            .ok_or_else(|| eyre!("command is not allowed: {}", argv.first().map(String::as_str).unwrap_or("")))
    }
}

static POLICY: OnceLock<Policy> = OnceLock::new();

fn policy() -> &'static Policy {
    POLICY.get_or_init(|| {
        Policy::parse(include_str!("../policy.toml"))
            .expect("embedded jj-proxy policy.toml must be valid")
    })
}

fn option_name(arg: &str) -> &str { arg.split_once('=').map_or(arg, |pair| pair.0) }

fn reject_security_options(global: &GlobalPolicy, args: &[String]) -> Result<()> {
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
    evaluate(policy(), argv, inspect, remotes)
}

fn evaluate(policy: &Policy, argv: &[String], inspect: bool, remotes: &HashSet<String>) -> Result<Decision> {
    validate_shape(argv)?;
    let rule = policy.rule_for(argv, inspect)?;
    reject_security_options(&policy.global, &argv[rule.path.len()..])?;
    // Fetch constraints are fixed behavior, not configurable authorization.
    let git_fetch = matches!(argv.get(0..2), Some([command, subcmd]) if command == "git" && subcmd == "fetch");
    let mut selected_remote = false;
    if git_fetch {
        let mut index = 2;
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
    if git_fetch && !selected_remote {
        normalized_argv.extend(remotes.iter().flat_map(|remote| ["--remote".to_owned(), remote.clone()]));
    }
    Ok(Decision {
        kind: if git_fetch { CommandKind::GitFetch } else { CommandKind::Standard },
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
    const COMPACT_POLICY: &str = include_str!("../tests/fixtures/compact-policy.toml");

    #[test]
    fn true_rules_are_equivalent_to_empty_tables() {
        let shorthand = Policy::parse(COMPACT_POLICY).unwrap();
        let tables = Policy::parse(&COMPACT_POLICY.replace("state = true", "state = {}")
            .replace("files = true", "files = {}")).unwrap();
        for (command, inspect) in [("state", true), ("state", false), ("files", false)] {
            let argv = [command, "operand"].map(str::to_owned);
            assert_eq!(
                evaluate(&shorthand, &argv, inspect, &HashSet::new()).unwrap(),
                evaluate(&tables, &argv, inspect, &HashSet::new()).unwrap(),
            );
        }
    }

    #[test]
    fn compact_rules_expand_and_mutation_inherits_inspection() {
        let policy = Policy::parse(COMPACT_POLICY).unwrap();
        let decide = |args: &[&str], inspect| evaluate(
            &policy, &args.iter().map(|arg| (*arg).to_owned()).collect::<Vec<_>>(), inspect, &HashSet::new(),
        );
        for inspect in [true, false] {
            for args in [vec!["state", "operand"], vec!["history", "list", "--future-option"], vec!["history", "show"]] {
                let decision = decide(&args, inspect).unwrap();
                assert_eq!(decision.read_only, inspect);
                assert!(!decision.updates_author);
                assert_eq!(decision.argv, args);
            }
            for args in [vec!["history"], vec!["history", "unknown"], vec!["state", "--blocked=x"], vec!["history", "list", "--private-key"]] {
                assert!(decide(&args, inspect).is_err(), "accepted {args:?} in inspect={inspect}");
            }
        }
        for subcmd in ["create", "amend"] {
            assert!(decide(&["change", subcmd], false).unwrap().updates_author);
            assert!(decide(&["change", subcmd], true).is_err());
        }
        assert!(decide(&["history", "restore"], false).is_ok());
        assert!(decide(&["history", "restore"], true).is_err());
        assert!(decide(&["files", "future-subcommand", "operand"], false).is_ok());
        assert!(decide(&["files", "future-subcommand"], true).is_err());
    }

    #[test]
    fn editing_policy_changes_permissions_and_author_hooks() {
        let text = COMPACT_POLICY.replace("\"list\", \"show\"", "\"search\"")
            .replace("updates_author = true", "updates_author = false")
            .replace("[mutate]", "[mutate]\nstate = { updates_author = true }");
        let policy = Policy::parse(&text).unwrap();
        for inspect in [true, false] {
            let state = evaluate(&policy, &["state".into()], inspect, &HashSet::new()).unwrap();
            assert_eq!(state.read_only, inspect);
            assert_eq!(state.updates_author, !inspect);
            assert!(evaluate(&policy, &["history".into(), "search".into()], inspect, &HashSet::new()).is_ok());
            assert!(evaluate(&policy, &["history".into(), "show".into()], inspect, &HashSet::new()).is_err());
        }
        assert!(!evaluate(&policy, &["change".into(), "create".into()], false, &HashSet::new()).unwrap().updates_author);
    }

    #[test]
    fn malformed_compact_rules_fail_instead_of_broadening_permissions() {
        for invalid in [
            COMPACT_POLICY.replace("subcmds =", "subcommands ="),
            COMPACT_POLICY.replace("[\"list\", \"show\"]", "[]"),
            COMPACT_POLICY.replace("[\"list\", \"show\"]", "[\"\"]"),
            COMPACT_POLICY.replace("[\"list\", \"show\"]", "[\"list show\"]"),
            COMPACT_POLICY.replace("state = true", "\"\" = true"),
            COMPACT_POLICY.replace("state = true", "\"git fetch\" = true"),
            COMPACT_POLICY.replace("state = true", "state = { prefix = true }"),
            COMPACT_POLICY.replace("state = true", "state = { kind = \"git-fetch\" }"),
            COMPACT_POLICY.replace("state = true", "state = { approved_remote = true }"),
            COMPACT_POLICY.replace("state = true", "state = false"),
            COMPACT_POLICY.replace("state = true", "state = \"true\""),
        ] {
            assert!(Policy::parse(&invalid).is_err(), "accepted invalid policy: {invalid}");
        }
    }

    #[test]
    fn fetch_constraints_do_not_require_policy_flags() {
        let remotes = HashSet::from(["origin".into()]);
        assert!(validate_inspect(&["git".into(), "fetch".into()]).is_err());
        assert!(validate(&["git".into(), "fetch".into()], &HashSet::new()).is_err());
        for args in [vec!["git", "fetch", "--remote"], vec!["git", "fetch", "--remote=evil"], vec!["git", "fetch", "--remote", "origin", "--remote", "evil"]] {
            assert!(validate(&args.into_iter().map(str::to_owned).collect::<Vec<_>>(), &remotes).is_err());
        }
        let argv = ["git", "fetch", "--remote=origin", "--branch", "main"].map(str::to_owned);
        let decision = validate(&argv, &remotes).unwrap();
        assert_eq!(decision.kind, CommandKind::GitFetch);
        assert_eq!(decision.argv, argv);
    }

    #[test]
    fn broad_git_permission_keeps_fixed_fetch_constraints() {
        let policy = Policy::parse(&COMPACT_POLICY.replace("[mutate]", "[mutate]\ngit = {}")).unwrap();
        let remotes = HashSet::from(["origin".into()]);
        let argv = ["git", "fetch"].map(str::to_owned);
        assert!(evaluate(&policy, &argv, true, &remotes).is_err());
        assert!(evaluate(&policy, &argv, false, &HashSet::new()).is_err());
        assert!(evaluate(&policy, &["git".into(), "fetch".into(), "--remote=evil".into()], false, &remotes).is_err());
        let decision = evaluate(&policy, &argv, false, &remotes).unwrap();
        assert_eq!(decision.kind, CommandKind::GitFetch);
        assert_eq!(decision.argv, ["git", "fetch", "--remote", "origin"]);
        let explicit = ["git", "fetch", "--remote=origin"].map(str::to_owned);
        assert_eq!(evaluate(&policy, &explicit, false, &remotes).unwrap().argv, explicit);
        let unauthorized = Policy::parse(COMPACT_POLICY).unwrap();
        assert!(evaluate(&unauthorized, &argv, false, &remotes).is_err());
    }

    #[test]
    fn leaves_ordinary_validation_to_jj() {
        assert!(check(&["log", "--future-jj-option", "value"]));
        assert!(check(&["op", "log"]));
        assert!(check(&["op", "show", "@"]));
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
        assert!(check(&["op", "show", "@"]));
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
