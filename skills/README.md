# Agent skills

These skills follow the Agent Skills directory format and are intentionally small and composable. Use them manually at first; automate only the sequences you actually repeat.

## Install

Install the repository through a supported harness, or copy an individual directory from `skills/` into that harness's skill directory.

### Pi

```sh
pi install git:github.com/jyn514/dotfiles
```

### Claude Code

```sh
claude plugin marketplace add jyn514/dotfiles
claude plugin install jyn514-agent-skills@jyn514-agent-skills
```

### Codex and other Agent Skills clients

Copy or symlink the desired skill directories into the client's user or project skill directory. For clients that use the shared convention, install them under `~/.agents/skills/` or `.agents/skills/`.

This repository's `./setup dotfiles` command links the complete `skills/` directory to `~/.agents/skills/`.

## Agent orchestration

For agent-driven use, start with `design-deliberation`. It is a thin meta-skill that selects the smallest useful workflow and composes the narrower skills while preserving candidate isolation and explicit abstention.

## Suggested workflow

For an uncertain design question:

1. `pain-axis` — inspect repository/history evidence about where the current design has hurt.
2. `design-space-scout` — produce three viable, materially distinct briefs.
3. `independent-plan` — elaborate each brief independently, ideally in isolated subagents.
4. `cross-critic` — compare the fixed candidates and identify assumptions, omissions, and incompatibilities.
5. `fusion-candidate` — only if the critic finds cleanly composable parts, construct one explicit synthesis candidate.
6. `council-review` — evaluate the fixed candidate set; choose, declare equivalence, or abstain.

After choosing a design and before implementation:

7. `boundary-declaration` — state ownership/effect boundaries and invariants explicitly.
8. `second-user` — challenge any new abstraction that lacks a second concrete consumer.
9. `ratchet` — turn verified invariants and discovered failure modes into mechanical checks where possible.

## Minimal use

You do not need the whole chain every time.

- Small refactor: `boundary-declaration` → `second-user` → implementation.
- Architecture decision: `design-space-scout` → 3× `independent-plan` → `cross-critic` → `council-review`.
- Legacy subsystem: start with `pain-axis` before scouting.
- Long autonomous run: add `ratchet` early and keep extending it as the agent learns new invariants.

## Important rule

Treat model judgments as evidence, not verification. Prefer repository facts, tests, type checks, benchmarks, and historical evidence whenever they exist. `council-review` may return `ABSTAIN`; that is a valid result.
