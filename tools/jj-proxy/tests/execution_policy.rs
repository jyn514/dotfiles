use std::process::{Command, Output};

fn run_fixture(mode: &str) -> Output {
    Command::new(env!("CARGO_BIN_EXE_execution-policy-fixture"))
        .arg(mode)
        .output()
        .expect("could not run execution-policy fixture")
}

fn assert_success(output: Output) {
    assert!(
        output.status.success(),
        "fixture failed with {}:\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

#[test]
fn trusted_jj_policy_can_replace_working_tree_files() {
    assert_success(run_fixture("worktree"));
}

#[test]
fn trusted_jj_policy_cannot_write_outside_repository() {
    assert_success(run_fixture("outside"));
}
