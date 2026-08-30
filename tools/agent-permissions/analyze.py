#!/usr/bin/env python3
"""Audit Claude Code permission rules against what actually got run.

The chat logs do NOT record the permission rule Claude proposed for each
approval. They DO record every tool call's real input. So we reconstruct:

  * which Bash commands actually ran, across every session in a project
  * the allow-list currently in .claude/settings.local.json

and report two kinds of mismatch:

  TOO BROAD   a wildcard allow-rule that, across all history, ever matched
              only 0-1 distinct commands -- it granted more than was used.

  TOO NARROW  a cluster of distinct commands sharing a natural prefix that
              is NOT covered by any wildcard rule -- each one needed its own
              approval, so a single wildcard would have saved friction.

Usage:
  analyze-agent-permissions [PROJECT]
  analyze-agent-permissions --narrow-min 3 [PROJECT]
"""
import argparse
import collections
import glob
import json
import os
import re
import shlex

# leading `VAR=value` assignments Claude Code strips when proposing a rule
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def load_bash_rules(settings_path):
    """Return list of (raw_rule, compiled_regex, has_wildcard) for Bash rules."""
    with open(settings_path, encoding="utf-8") as settings_file:
        settings = json.load(settings_file)
    rules = []
    for entry in settings["permissions"]["allow"]:
        m = re.fullmatch(r"Bash\((.*)\)", entry)
        if not m:
            continue
        inner = m.group(1)
        has_wild = "*" in inner
        pat = "".join(".*" if part == "*" else re.escape(part)
                       for part in re.split(r"(\*)", inner))
        rules.append((entry, re.compile(pat + r"\Z"), has_wild))
    return rules


def iter_bash_commands(logdir):
    """Yield every Bash command string executed in any logged session."""
    for path in glob.glob(os.path.join(logdir, "*.jsonl")):
        with open(path, encoding="utf-8") as log_file:
            for line in log_file:
                if '"tool_use"' not in line or "Bash" not in line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = o.get("message", {}).get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if (isinstance(block, dict)
                            and block.get("type") == "tool_use"
                            and block.get("name") == "Bash"):
                        cmd = block.get("input", {}).get("command")
                        if cmd:
                            yield cmd.strip()


def signature(cmd):
    """A natural prefix-rule key for a command: drop leading env assignments,
    then keep the program plus one subcommand-ish token."""
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    while toks and ENV_ASSIGN.match(toks[0]):
        toks.pop(0)
    if not toks:
        return None
    # keep program; add the next token if it looks like a subcommand/flag-group
    key = [toks[0]]
    if len(toks) > 1 and not toks[1].startswith("-") and "/" not in toks[1]:
        key.append(toks[1])
    return " ".join(key)


# Wasteful command habits worth discouraging, with the better move.
ANTIPATTERNS = [
    ("PAGER=cat on git/jj read",
     re.compile(r"\b(PAGER|MANPAGER)=cat\b"),
     "unnecessary in the sandbox; run the git/jj read directly"),
    ("leading `cd`",
     re.compile(r"\Acd\s"),
     "cwd is the repo root and persists; use an absolute path"),
    ("`cd \"$(git rev-parse ...)\"`",
     re.compile(r"cd\s+\"?\$\(git rev-parse"),
     "already at repo root; drop the hop entirely"),
    ("shell file-write (cat>/tee/heredoc)",
     re.compile(r"\bcat\s*>>?|\btee\s+[^|&;<>\s]|>[^|&;<]*<<"),
     "use the Write/Edit tool instead"),
    ("inline `python3 -c`",
     re.compile(r"\bpython3?\s+-c\b"),
     "put multi-step logic in a script file (saved memory)"),
    ("`echo \"...exit=$?...\"`",
     re.compile(r"echo\s+\"[^\"]*\$\?"),
     "the tool already reports exit status"),
    ("`ls -la` to inspect",
     re.compile(r"\bls\s+-l"),
     "prefer the Read/Glob tools for structured inspection"),
    ("redundant `| head`/`| tail`",
     re.compile(r"\|\s*(head|tail)\b"),
     "fine occasionally, but output is already truncated for you"),
]


def antipattern_report(logdir):
    commands = collections.Counter(iter_bash_commands(logdir))
    total = sum(commands.values())
    print(f"scanned {total} runs for wasteful habits\n")
    rows = []
    for name, rx, advice in ANTIPATTERNS:
        runs = sum(n for cmd, n in commands.items() if rx.search(cmd))
        distinct = sum(1 for cmd in commands if rx.search(cmd))
        rows.append((runs, distinct, name, advice))
    for runs, distinct, name, advice in sorted(rows, reverse=True):
        print(f"  {runs:5} runs / {distinct:4} distinct  {name}")
        print(f"        -> {advice}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("project", nargs="?", default=os.getcwd(),
                    help="project root (default: current directory)")
    ap.add_argument("--narrow-min", type=int, default=3,
                    help="min distinct uncovered commands to flag a too-narrow cluster")
    ap.add_argument("--antipatterns", action="store_true",
                    help="report wasteful command habits instead of rule coverage")
    args = ap.parse_args(argv)
    project = os.path.abspath(args.project)
    project_key = project.replace(os.sep, "-")
    logdir = os.path.expanduser(os.path.join("~/.claude/projects", project_key))
    settings = os.path.join(project, ".claude", "settings.local.json")

    if args.antipatterns:
        antipattern_report(logdir)
        return

    rules = load_bash_rules(settings)
    commands = collections.Counter(iter_bash_commands(logdir))
    distinct = list(commands)
    print(f"loaded {len(rules)} Bash allow-rules; "
          f"{sum(commands.values())} runs, {len(distinct)} distinct commands\n")

    # which distinct commands each wildcard rule matches
    rule_hits = {r[0]: set() for r in rules}
    uncovered = []
    for cmd in distinct:
        matched = False
        for raw, rx, _ in rules:
            if rx.match(cmd):
                rule_hits[raw].add(cmd)
                matched = True
        if not matched:
            uncovered.append(cmd)

    print("=== TOO BROAD: wildcard rules that matched <=1 distinct command ===")
    for raw, rx, has_wild in rules:
        if has_wild and len(rule_hits[raw]) <= 1:
            ex = next(iter(rule_hits[raw]), "(never matched anything)")
            print(f"  {raw:45}  hits={len(rule_hits[raw])}  e.g. {ex[:60]}")

    print("\n=== TOO NARROW: uncovered command clusters (>= "
          f"{args.narrow_min} distinct) ===")
    clusters = collections.defaultdict(list)
    for cmd in uncovered:
        sig = signature(cmd)
        if sig:
            clusters[sig].append(cmd)
    for sig, cmds in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        if len(cmds) >= args.narrow_min:
            runs = sum(commands[c] for c in cmds)
            print(f"  Bash({sig} *)  -> {len(cmds)} distinct cmds, {runs} runs")
            for c in sorted(cmds)[:3]:
                print(f"        {c[:70]}")


if __name__ == "__main__":
    main()
