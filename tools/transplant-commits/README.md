# Import a commit series between repositories

[`transplant-commits`](../../bin/transplant-commits) imports selected commits, optionally selecting a directory and relocating its contents below another directory.
It requires Python 3 and Git, and both source and target must already be repository top levels.
It invokes Git directly; use the [Jujutsu workflow](../../skills/jj-workflow/SKILL.md) to preserve authored work when integrating the result.

## Preview the transfer

```sh
transplant-commits --dry-run --from /path/to/source:packages/example --to /path/to/target:tools/example BASE..TIP
```

`--from` and `--to` accept `REPO[:PATH]`; omitting a path selects the entire repository.
At least one endpoint option is required; an omitted endpoint defaults to the current repository.
`--dry-run` prints the pipeline without applying it, but still requires both repositories to exist.
To include a root commit, pass revision options after the CLI separator, for example `-- --root COMMIT`.

## History and side effects

The command pipes `git format-patch` into `git am -3`, with a relative source path and target directory when selected.
It preserves authors, author dates, and message text, rewrites commit IDs, and omits merge commits.
Original committer metadata, signatures, and parent relationships are not preserved; final newline bytes in commit messages may change.
Path selection does not automatically follow earlier directory renames.

Applying writes the target Git HEAD and index; it does not synchronize a colocated JJ workspace.
There is no tool-level dirty-worktree or destination-collision preflight.
Use a clean owned target or isolated import repository and inspect both endpoints before applying.
Inherited Git environment selectors can redirect Git away from the path-selected repositories; check the environment too.
The tool is not transactional: failure can leave applied commits or an interrupted `git am` requiring inspection and recovery.
Do not blindly retry a failed import.
After checking those conditions, remove `--dry-run` from the preview command to apply the series.

## Tests

From the dotfiles root, run `dev/pytest -q tests/vcs/transplant_commits_test.py` against disposable repositories.
