"""Run the Jujutsu proxy Cargo suite with the existing platform target scope."""

import os
import platform


def test_jj_proxy(run_native_suite):
    command = ["cargo", "test", "--manifest-path", "tools/jj-proxy/Cargo.toml"]
    if platform.system() != "Linux":
        command.extend(["--lib", "--bins"])
    env = {}
    if real_jj := os.environ.get("DOTFILES_TEST_JJ_REAL"):
        env["JJ_PROXY_TEST_JJ"] = real_jj
    run_native_suite(command, env=env)
