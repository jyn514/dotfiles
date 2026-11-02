//! Admission uses the installed native parser, never native dispatch.
use clap::{
    error::{ContextKind, ContextValue, ErrorKind},
    Arg, ArgMatches, CommandFactory, FromArgMatches,
};
use std::path::{Path, PathBuf};
use ticgit::cli::{Cli, Command, WriteupAction};

#[derive(Debug, PartialEq, Eq)]
pub enum Decision {
    Execute,
    Respond {
        exit: i32,
        stdout: String,
        stderr: String,
    },
}

pub(crate) fn parse(argv: &[String]) -> Result<Cli, clap::Error> {
    Cli::from_arg_matches(&parse_matches(argv)?)
}
pub(crate) fn parse_matches(argv: &[String]) -> Result<ArgMatches, clap::Error> {
    Cli::command()
        .try_get_matches_from(std::iter::once("ti".to_owned()).chain(argv.iter().cloned()))
}

/// Only these parsed fields represent guest file inputs. In particular a writeup
/// body is text, not a file and not interchangeable with writeup edit-file syntax.
pub(crate) fn file_mut(cli: &mut Cli) -> Option<&mut Option<PathBuf>> {
    match cli.command.as_mut()? {
        Command::New(a) => Some(&mut a.file),
        Command::Edit(a) => Some(&mut a.file),
        Command::Spec(a) => Some(&mut a.file),
        Command::Meta(a) => Some(&mut a.file),
        Command::Writeup(a) => match &mut a.action {
            WriteupAction::New(a) => Some(&mut a.file),
            WriteupAction::Edit(a) => Some(&mut a.file),
            _ => None,
        },
        _ => None,
    }
}

pub fn classify(argv: &[String], stdin: &str) -> Result<Decision, String> {
    crate::protocol::validate_argv(argv).map_err(|e| e.to_string())?;
    if stdin.len() > crate::protocol::MAX_REQUEST {
        return Err("stdin limit exceeded".into());
    }
    let parsed = match parse_matches(argv) {
        Ok(parsed) => parsed,
        Err(e) => {
            return match e.kind() {
                ErrorKind::DisplayHelp => {
                    if !stdin.is_empty() {
                        return Err("unexpected stdin".into());
                    }
                    Ok(Decision::Respond {
                        exit: 0,
                        stdout: agent_help(),
                        stderr: String::new(),
                    })
                }
                ErrorKind::DisplayVersion => {
                    if !stdin.is_empty() {
                        return Err("unexpected stdin".into());
                    }
                    Ok(Decision::Respond {
                        exit: 0,
                        stdout: format!(
                            "ti {} (agent proxy)\n",
                            Cli::command().get_version().unwrap_or("unknown")
                        ),
                        stderr: String::new(),
                    })
                }
                _ => Err(argument_error(&e)),
            }
        }
    };
    if parsed
        .subcommand_name()
        .is_some_and(|name| !admitted_name(name))
    {
        return Err("command is not available to agents".into());
    }
    let mut cli = Cli::from_arg_matches(&parsed).map_err(|_| "cannot inspect native arguments")?;
    let file = file_mut(&mut cli).and_then(|f| f.as_ref());
    if let Some(path) = file {
        if path != Path::new("-") {
            return Err("file input must be normalized to stdin (-)".into());
        }
    } else if !stdin.is_empty() {
        return Err("unexpected stdin without file input".into());
    }
    let nonblank = |s: &Option<String>| s.as_ref().is_some_and(|s| !s.trim().is_empty());
    let admitted = match &cli.command {
        None => true,
        Some(Command::New(a)) => !a.comment_edit && (a.file.is_some() || nonblank(&a.title)),
        Some(Command::Edit(a)) => a.file.is_some(),
        Some(Command::Comment(a)) => !a.edit && !a.body.is_empty(),
        Some(Command::State(a) | Command::Status(a)) => a.lifecycle.is_some(),
        Some(Command::Spec(a)) => a.spec.is_some() || a.file.is_some() || a.clear,
        Some(Command::Writeup(a)) => match &a.action {
            WriteupAction::New(a) => nonblank(&a.title) && (a.body.is_some() || a.file.is_some()),
            WriteupAction::Edit(a) => a.body.is_some() || a.file.is_some(),
            WriteupAction::List(_)
            | WriteupAction::Show(_)
            | WriteupAction::Promote(_)
            | WriteupAction::Close(_)
            | WriteupAction::Archive(_)
            | WriteupAction::Link(_)
            | WriteupAction::Unlink(_) => true,
        },
        // The canonical native command name was admitted above using the same
        // allowlist that generates agent help. Other admitted paths have no
        // interactive condition beyond the native parser's validation.
        _ => true,
    };
    if admitted {
        Ok(Decision::Execute)
    } else {
        Err("command requires an admitted explicit input or is not available to agents".into())
    }
}

fn admitted_name(name: &str) -> bool {
    matches!(
        name,
        "new"
            | "list"
            | "show"
            | "history"
            | "recent"
            | "stats"
            | "next"
            | "claim"
            | "edit"
            | "comment"
            | "state"
            | "status"
            | "close"
            | "tag"
            | "assign"
            | "priority"
            | "points"
            | "milestone"
            | "code"
            | "depends"
            | "subissue"
            | "meta"
            | "spec"
            | "writeup"
    )
}

fn advertised_arg(arg: &Arg) -> bool {
    !arg.is_hide_set() && !matches!(arg.get_id().as_str(), "comment_edit" | "edit")
}

/// Preserve conflict participants, not native usage or suggestions, which can
/// advertise excluded commands and editor fallbacks. Other parser failures keep
/// the restricted-interface diagnostic.
fn argument_error(error: &clap::Error) -> String {
    const FALLBACK: &str = "invalid native TicGit arguments; use --help for the admitted interface";
    if error.kind() != ErrorKind::ArgumentConflict {
        return FALLBACK.into();
    }
    let Some(ContextValue::String(invalid)) = error.get(ContextKind::InvalidArg) else {
        return FALLBACK.into();
    };
    let prior = match error.get(ContextKind::PriorArg) {
        Some(ContextValue::String(value)) => vec![value.as_str()],
        Some(ContextValue::Strings(values)) => values.iter().map(String::as_str).collect(),
        _ => return FALLBACK.into(),
    };
    // Only publish parser-owned argument labels from the advertised interface,
    // never caller values or labels for excluded editor controls.
    let mut native = Cli::command();
    native.build();
    let mut labels = Vec::new();
    for command in native
        .get_subcommands()
        .filter(|c| admitted_name(c.get_name()))
    {
        labels.extend(
            command
                .get_arguments()
                .filter(|a| advertised_arg(a))
                .map(ToString::to_string),
        );
        for action in command.get_subcommands() {
            labels.extend(
                action
                    .get_arguments()
                    .filter(|a| advertised_arg(a))
                    .map(ToString::to_string),
            );
        }
    }
    if !labels.contains(invalid)
        || prior.is_empty()
        || prior
            .iter()
            .any(|value| !labels.iter().any(|label| label == value))
    {
        return FALLBACK.into();
    }
    if prior == [invalid.as_str()] {
        format!("argument '{invalid}' cannot be used multiple times; use --help for the admitted interface")
    } else {
        format!("argument '{invalid}' cannot be used with {}; remove conflicting arguments or use --help for the admitted interface",
            prior.iter().map(|value| format!("'{value}'")).collect::<Vec<_>>().join(", "))
    }
}

/// Derive option names, aliases, and conflicts from the exported parser.
/// Native templates and unreviewed descriptions advertise interactive fallbacks.
pub fn agent_help() -> String {
    let mut native = Cli::command();
    native.build();
    let mut out = String::from("TicGit agent interface\nUsage: ti <command> [options]\nNo arguments means list. Files are collected in the guest; - reads stdin.\nExplicit input is required for new, edit, comment, state/status, spec and writeup new/edit.\nWriteup --body is literal text; writeup edit --file reads title then body.\n\n");
    for cmd in native
        .get_subcommands()
        .filter(|c| admitted_name(c.get_name()))
    {
        help_line(cmd, cmd.get_name(), &mut out);
        for action in cmd.get_subcommands() {
            help_line(
                action,
                &format!("{} {}", cmd.get_name(), action.get_name()),
                &mut out,
            );
        }
    }
    out.push_str("\nHelp: -h, --help; version: -v, --version.\n");
    out
}
fn help_line(cmd: &clap::Command, name: &str, out: &mut String) {
    out.push_str(name);
    for alias in cmd.get_visible_aliases() {
        out.push_str(&format!(" (alias {alias})"));
    }
    out.push(':');
    for arg in cmd.get_arguments() {
        if !advertised_arg(arg) {
            continue;
        }
        if let Some(long) = arg.get_long() {
            out.push_str(&format!(" --{long}"));
        }
        if let Some(short) = arg.get_short() {
            out.push_str(&format!(" -{short}"));
        }
        if arg.get_long().is_none() && arg.get_short().is_none() {
            out.push_str(&format!(" <{}>", arg.get_id()));
        }
    }
    out.push('\n');
    for arg in cmd.get_arguments().filter(|a| advertised_arg(a)) {
        let conflicts: Vec<_> = cmd
            .get_arg_conflicts_with(arg)
            .into_iter()
            .filter(|a| advertised_arg(a))
            .map(ToString::to_string)
            .collect();
        // This native description explains the reported --open/--limit mistake
        // without importing prose that promises unavailable editor fallbacks.
        let description = if name == "list" && arg.get_id() == "open" {
            arg.get_help()
        } else {
            None
        };
        if description.is_none() && conflicts.is_empty() {
            continue;
        }
        out.push_str(&format!("  {arg}:"));
        if let Some(description) = description {
            out.push_str(&format!(" {description}"));
        }
        if !conflicts.is_empty() {
            out.push_str(&format!(" conflicts with {}.", conflicts.join(", ")));
        }
        out.push('\n');
    }
}
