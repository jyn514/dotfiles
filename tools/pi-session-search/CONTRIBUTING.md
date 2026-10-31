# Contributing

Thanks for choosing to contribute!

The following are a set of guidelines to follow when contributing to this project.

## Code Of Conduct

This project adheres to the Adobe [code of conduct](./CODE_OF_CONDUCT.md). By participating,
you are expected to uphold this code. Please report unacceptable behavior to
[Grp-opensourceoffice@adobe.com](mailto:Grp-opensourceoffice@adobe.com).

## Have A Question?

Start by filing an issue. The existing committers on this project work to reach
consensus around project direction and issue solutions within issue threads
(when appropriate).

## Development checks

For this maintained dotfiles copy, run from the dotfiles root:

```bash
dev/pytest -q tests/native/test_native_pi_session_search.py
```

The adapter runs the upstream suite in a disposable copy with the installed Pi peers.
For an additional upstream typecheck, copy this package into disposable storage first and run the following from that copy through dotfiles' `dev/test-environment`:

```bash
npm install --ignore-scripts --no-audit --no-fund
npm run typecheck
npm test
```

The pinned development dependencies provide the local TypeScript compiler and Node.js type declarations.
No global `tsc` installation is required.
Do not install dependencies or generate artifacts in the authoritative `tools/pi-session-search` directory.
The remaining contribution and licensing sections preserve upstream policy; dotfiles' repository guidance owns local changes.

For automated probes that parse Node test output, select TAP explicitly. Do not
assume the default reporter emits `ok`/`not ok`; a human-readable default caused
a false probe failure during regression testing.

```bash
node --test --test-reporter=tap --experimental-strip-types 'test/**/*.test.ts'
```

Check the process exit status and assertion diagnostics, not just reporter text,
to distinguish an expected regression failure from a setup or import failure.

For native Pi 1.0.2 fixtures, `SessionManager.create()` assigns a session-file path before creating the file.
`getSessionFile()` returning a path does not establish that the file exists.
Pi first writes the file after a user or assistant message; custom messages alone remain in memory.
For transcript-read fixtures, append a user or assistant message before invoking the reader to avoid a setup-time `ENOENT`.
That first write also persists earlier custom entries and messages.

If the fixture must remain empty or custom-only, write its JSONL explicitly in the disposable sessions root.
Include a valid session header rather than creating a zero-byte file.
If a `SessionManager` must continue appending, call `setSessionFile(sessionFile)` after writing the fixture to reload its persisted entries.

To check real Codex recordings without adding their contents to the test suite, supply a read-only corpus explicitly:

```bash
PI_SESSION_SEARCH_TEST_CODEX_ROOT=/absolute/path/to/read-only/codex-sessions dev/pytest -q tests/native/test_native_pi_session_search.py
```

The optional test checks search-to-read round trips through Pi's loader, paging, version selection, and unchanged file checksums.
It skips when the variable is unset and does not establish support for every Codex item type.
Synthetic fixtures remain the decoding and inherited-history tests.

## Contributor License Agreement

All third-party contributions to this project must be accompanied by a signed contributor
license agreement. This gives Adobe permission to redistribute your contributions
as part of the project. [Sign our CLA](https://opensource.adobe.com/cla.html). You
only need to submit an Adobe CLA one time, so if you have submitted one previously,
you are good to go!

## Code Reviews

All submissions should come in the form of pull requests and need to be reviewed
by project committers. Read [GitHub's pull request documentation](https://help.github.com/articles/about-pull-requests/)
for more information on sending pull requests.

Lastly, please follow the [pull request template](PULL_REQUEST_TEMPLATE.md) when
submitting a pull request!

## From Contributor To Committer

We love contributions from our community! If you'd like to go a step beyond contributor
and become a committer with full write access and a say in the project, you must
be invited to the project. The existing committers employ an internal nomination
process that must reach lazy consensus (silence is approval) before invitations
are issued. If you feel you are qualified and want to get more deeply involved,
feel free to reach out to existing committers to have a conversation about that.

## Security Issues

Security issues shouldn't be reported on this issue tracker. Instead, [file an issue to our security experts](https://helpx.adobe.com/security/alertus.html).
