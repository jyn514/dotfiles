"""Repair the local index through the installed Codex app-server protocol."""

from contextlib import closing
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import tomllib


# Explicit sources include noninteractive sessions that thread/list omits by default.
SOURCES = ["cli", "vscode", "exec", "appServer", "subAgent", "subAgentReview",
           "subAgentCompact", "subAgentThreadSpawn", "subAgentOther", "unknown"]


def fingerprint(path):
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def environment_signature(home):
    root = Path(__file__).resolve().parents[1]
    # Fingerprint candidates rather than launching `codex --version` on every hit.
    # Include resolved targets so replacing an installed binary invalidates the receipt.
    programs = {Path(__file__).resolve(), root / "bin/codex", root / "bin/codex-import"}
    candidates = []
    for directory in os.get_exec_path():
        candidate = Path(directory) / "codex"
        if candidate.is_file():
            resolved = candidate.resolve()
            programs.add(resolved)
            if resolved != root / "bin/codex" and str(resolved) not in candidates:
                candidates.append(str(resolved))
    configuration = {}
    for name in ("config.toml", "dotfiles.config.toml"):
        path = home / name
        configuration[name] = fingerprint(path) if path.exists() else None
    return {"version": 1, "programs": {str(p): fingerprint(p) for p in programs},
            "codex_candidates": candidates, "configuration": configuration,
            "sqlite_home": os.environ.get("CODEX_SQLITE_HOME")}


def rollout_inventory(home):
    files = {}
    def fail(error):
        raise error
    for name, archived in (("sessions", 0), ("archived_sessions", 1)):
        root = home / name
        if not root.exists():
            continue
        for directory, children, names in os.walk(root, onerror=fail):
            if any((Path(directory) / child).is_symlink() for child in children):
                raise OSError("rollout directory contains a symlink")
            for filename in names:
                if filename.endswith(".jsonl"):
                    path = Path(directory) / filename
                    files[str(path)] = [archived, fingerprint(path)]
    return files


def index_snapshot(home, files, signature):
    def custom_database(value):
        return isinstance(value, dict) and ("sqlite_home" in value or any(custom_database(v) for v in value.values()))
    # Resolving layered custom database settings belongs to Codex. Be conservative
    # rather than treating an old default database as the configured index.
    for name in ("config.toml", "dotfiles.config.toml"):
        config = home / name
        if config.exists() and custom_database(tomllib.loads(config.read_text())):
            raise OSError("custom sqlite_home requires a full Codex scan")
    directory = Path(os.environ.get("CODEX_SQLITE_HOME") or home).absolute()
    database = directory / "state_5.sqlite"
    # Unknown/new layouts must go through Codex, never an old leftover database.
    if set(directory.glob("state_*.sqlite")) != {database}:
        raise OSError("unsupported Codex state database layout")
    identity = fingerprint(database)[:2]
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.05)) as connection:
        indexed = dict(connection.execute("SELECT rollout_path, archived FROM threads"))
    return {"context": dict(signature, database=identity), "indexed": indexed,
            "paths": list(files),
            "unindexed": {p: stamp for p, stamp in files.items() if indexed.get(p) != stamp[0]}}


def receipt_matches(receipt, current):
    return (receipt["context"] == current["context"]
            and set(receipt["paths"]).issubset(current["paths"])
            and all(current["indexed"].get(p) == archived for p, archived in receipt["indexed"].items())
            and all(receipt["unindexed"].get(p) == stamp for p, stamp in current["unindexed"].items()))


def publish_receipt(path, snapshot):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", delete=False) as output:
            temporary = Path(output.name)
            json.dump(snapshot, output)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def repair(process):
    replies = queue.Queue()

    def read():
        try:
            for line in process.stdout:
                replies.put(json.loads(line))
        except (ValueError, OSError) as error:
            replies.put(error)
        finally:
            replies.put(EOFError("Codex app-server closed its output"))

    threading.Thread(target=read, daemon=True).start()
    request_id = 0

    def request(method, params):
        nonlocal request_id
        request_id += 1
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        while True:
            try:
                reply = replies.get(timeout=120)
            except queue.Empty:
                raise TimeoutError(f"Codex did not answer {method} within 120 seconds") from None
            if isinstance(reply, Exception):
                raise reply
            # Server request IDs are independent of client request IDs.
            if "method" in reply or reply.get("id") != request_id:
                continue
            if "error" in reply:
                raise RuntimeError(f"{method}: {json.dumps(reply['error'])}")
            return reply["result"]

    request("initialize", {"clientInfo": {"name": "codex_import", "version": "1.0.0"}})
    process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
    process.stdin.flush()
    total = 0
    for archived in (False, True):
        label = "archived" if archived else "current"
        print(f"Scanning {label} sessions...", file=sys.stderr, flush=True)
        cursor = None
        seen = set()
        while True:
            page = request("thread/list", {
                "archived": archived, "cursor": cursor, "limit": 100,
                "modelProviders": [], "sourceKinds": SOURCES,
                "sortKey": "created_at", "sortDirection": "desc",
                # False enables Codex's scan-and-repair path instead of DB-only listing.
                "useStateDbOnly": False,
            })
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise ValueError("thread/list returned an invalid page")
            total += len(page["data"])
            cursor = page.get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ValueError("thread/list returned an invalid or repeated cursor")
            seen.add(cursor)
    return total


def main():
    home = Path(os.environ["CODEX_HOME"]).resolve()
    receipt_path = home / "codex-import-receipt.json"
    before = signature = None
    try:
        signature = environment_signature(home)
        before = rollout_inventory(home)
        current = index_snapshot(home, before, signature)
        if "--force" not in sys.argv[1:] and receipt_matches(json.loads(receipt_path.read_text()), current):
            print("Session index is current.")
            return 0
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
        pass  # An uncertain fast-path check always falls back to Codex.
    try:
        receipt_path.unlink(missing_ok=True)
    except OSError as error:
        print(f"codex-import: warning: cannot invalidate receipt: {error}", file=sys.stderr)
    print(f"Repairing session index in {home}...", file=sys.stderr)
    with tempfile.TemporaryFile(mode="w+") as diagnostics:
        try:
            process = subprocess.Popen(
                ["codex", "app-server", "--stdio"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=diagnostics, text=True,
            )
            try:
                count = repair(process)
            finally:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                process.stdout.close()
            if process.returncode:
                raise RuntimeError(f"Codex app-server exited with status {process.returncode}")
        except (OSError, ValueError, EOFError, RuntimeError, TimeoutError, KeyError) as error:
            diagnostics.seek(0)
            detail = diagnostics.read().strip()
            print(f"codex-import: repair failed: {error}. Partial index repairs may remain; "
                  "retry codex-import.", file=sys.stderr)
            if detail:
                print(detail, file=sys.stderr)
            return 1
    print(f"Session import complete. Scanned {count} sessions.")
    try:
        if before is not None and environment_signature(home) == signature:
            after = rollout_inventory(home)
            snapshot = index_snapshot(home, after, signature)
            # Files created or modified during the scan must be reconsidered next time.
            snapshot["unindexed"] = {p: stamp for p, stamp in snapshot["unindexed"].items()
                                     if before.get(p) == stamp}
            publish_receipt(receipt_path, snapshot)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"codex-import: warning: receipt unavailable: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
