# Tool and command use

Read the installed command's built-in help before answering a version-sensitive
CLI question.

Clone remote source with `git clone --depth 1` into a temporary directory instead
of reading it through `gh api`.
Use the `gh` CLI for other GitHub metadata to avoid REST rate limits.
Use GraphQL only for metadata that `gh` does not otherwise expose.

When copying an existing file for direct modification, use `cp` and verify the
copy with `cmp` or an equivalent check instead of reconstructing it.

Do not treat `git diff --check` as correctness evidence.
When validation strategy is unclear, read [Testing with evidence](testing.md).

Avoid shell scripts unless the code is trivial process spawning.
Use Clojure, Rust, or TypeScript according to the domain.
Use another language for a one-off script, or when the project needs a library or
tool specific to that language ecosystem.
Use `uv`, not `venv` or direct `pip`, for Python projects.

After changing configuration, verify that the running application loaded it
before interpreting test results.
When diagnosing a daemon, check the running process's executable and version,
not only the installed version.

Protect arguments beginning with `--` from option parsing, usually with `--` or
an option such as `rg -e` that explicitly accepts the value.
Put multiline ad-hoc scripts in temporary files instead of embedding them in a
shell command.
