use tic_proxy::policy::{classify, Decision};
use tic_proxy::protocol::{AuthenticatedRequest, Request};
fn args(a: &[&str]) -> Vec<String> {
    a.iter().map(|s| (*s).into()).collect()
}
// Exercise the same typed envelope a client bypass uses, not client normalization.
fn direct(a: &[&str], stdin: &str) -> Result<Decision, String> {
    let raw = serde_json::to_vec(&AuthenticatedRequest {
        token: "owned-test-token".into(),
        request: Request {
            version: 1,
            command: "tic".into(),
            argv: args(a),
            stdin: stdin.into(),
        },
    })
    .unwrap();
    let decoded: AuthenticatedRequest = serde_json::from_slice(&raw).unwrap();
    classify(&decoded.request.argv, &decoded.request.stdin)
}
#[test]
fn explicit_and_absent_inputs_follow_native_fallback_conditions() {
    let table: &[(&[&str], bool)] = &[
        (&[], true),
        (&["ls"], true),
        (&["list", "--assigned", "agent@example.invalid"], true),
        (&["new"], false),
        (&["new", "-t", ""], false),
        (&["new", "-t", " \t"], false),
        (&["new", "-t", "title"], true),
        (&["new", "-F", "-"], true),
        (&["new", "-t", "title", "--comment", ""], true),
        (&["new", "-t", "title", "--comment-edit"], false),
        (&["new", "-cF-"], true),
        (&["edit"], false),
        (&["edit", "-F-"], true),
        (&["comment"], false),
        (&["comment", ""], true),
        (&["comment", "body"], true),
        (&["comment", "body", "-e"], false),
        (&["comment", "-etabc", "body"], false),
        (&["comment", "--", "--edit"], true),
        (&["spec"], false),
        (&["spec", ""], true),
        (&["spec", "--clear"], true),
        (&["spec", "-F-"], true),
        (&["meta", "field"], true),
        (&["state"], false),
        (&["status"], false),
        (&["state", "--json"], false),
        (&["status", "--ticket", "id"], false),
        (&["state", ""], true),
        (&["status", "--", "blocked"], true),
        (&["state", "resolved"], true),
        (&["writeup", "new", "-t", "title"], false),
        (&["writeup", "new", "--body", "body"], false),
        (&["writeup", "new", "-t", " ", "--body", ""], false),
        (&["writeup", "new", "-t", "title", "--body", ""], true),
        (&["writeup", "new", "-t", "title", "-F-"], true),
        (&["writeup", "edit", "id"], false),
        (&["writeup", "edit", "id", "--body", ""], true),
        (&["writeup", "edit", "id", "-F-"], true),
    ];
    for &(a, admitted) in table {
        assert_eq!(direct(a, "").is_ok(), admitted, "{a:?}");
    }
}
#[test]
fn admitted_paths_and_aliases_only() {
    for a in [
        vec!["show", "id"],
        vec!["history", "-t", "id"],
        vec!["recent"],
        vec!["stats"],
        vec!["next"],
        vec!["claim"],
        vec!["close"],
        vec!["tag", "bug"],
        vec!["assign", "agent"],
        vec!["priority", "1"],
        vec!["points", "2"],
        vec!["milestone", "v1"],
        vec!["code", "repo:branch"],
        vec!["depends", "other"],
        vec!["dep", "other"],
        vec!["subissue", "parent"],
        vec!["writeup", "list"],
        vec!["writeup", "show", "id"],
        vec!["writeup", "promote", "id"],
        vec!["writeup", "close", "id"],
        vec!["writeup", "archive", "id"],
        vec!["writeup", "link", "id", "ticket"],
        vec!["writeup", "unlink", "id", "ticket"],
    ] {
        assert!(matches!(direct(&a, ""), Ok(Decision::Execute)), "{a:?}");
    }
    for cmd in [
        "setup", "init", "migrate", "update", "import", "pull", "push", "sync", "tui", "agent",
        "users", "views", "checkout", "co", "review", "mine",
    ] {
        assert!(direct(&[cmd], "").is_err(), "{cmd}");
    }
    assert!(direct(&["mine", "--assigned", "agent"], "").is_err());
    assert!(direct(&["list", "--repository", "/"], "").is_err());
}
#[test]
fn host_files_unexpected_stdin_nuls_and_limits_reject() {
    for a in [
        vec!["new", "--file=/host/secret"],
        vec!["edit", "-F/host/secret"],
        vec!["spec", "-F", "./-"],
        vec!["meta", "key", "-F", "relative"],
        vec!["writeup", "new", "-t", "title", "-F", "secret"],
        vec!["writeup", "edit", "id", "--file", ""],
    ] {
        assert!(direct(&a, "payload").is_err(), "{a:?}");
    }
    for a in [
        vec!["list"],
        vec!["comment", "body"],
        vec!["writeup", "edit", "id", "--body", "body"],
        vec!["--help"],
        vec!["--version"],
    ] {
        assert!(direct(&a, "unexpected").is_err(), "{a:?}");
    }
    assert!(direct(&["edit", "-F-"], "").is_ok());
    assert!(direct(&["edit", "-F-"], "\0").is_ok()); // JSON can preserve stdin NUL.
    assert!(direct(&["comment", "nul\0body"], "").is_err());
    assert!(classify(&vec!["x".into(); 129], "").is_err());
    assert!(classify(&vec!["x".repeat(65537)], "").is_err());
    assert!(classify(&vec!["x".repeat(65536); 5], "").is_err());
}
#[test]
fn help_and_version_never_publish_native_administration_or_editor_options() {
    for a in [
        vec!["--help"],
        vec!["new", "--help"],
        vec!["help", "setup"],
        vec!["review", "--help"],
    ] {
        let Decision::Respond {
            exit,
            stdout,
            stderr,
        } = direct(&a, "").unwrap()
        else {
            panic!("not help")
        };
        assert_eq!(exit, 0);
        assert!(stderr.is_empty());
        for forbidden in [
            "setup:",
            "review:",
            "mine:",
            "checkout:",
            "users:",
            "views:",
            "--comment-edit",
            "--edit",
            "$EDITOR",
        ] {
            assert!(!stdout.contains(forbidden), "{forbidden} in {stdout}");
        }
        assert!(stdout.contains("--file"));
        assert!(stdout.contains("alias ls"));
        assert!(stdout.contains("alias dep"));
    }
    assert!(matches!(
        direct(&["--version"], ""),
        Ok(Decision::Respond { exit: 0, .. })
    ));
    assert!(direct(&["nonesuch", "--help"], "").is_err());
}
