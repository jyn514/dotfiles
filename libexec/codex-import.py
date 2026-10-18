"""Repair the local index through the installed Codex app-server protocol."""

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading


# Explicit sources include noninteractive sessions that thread/list omits by default.
SOURCES = ["cli", "vscode", "exec", "appServer", "subAgent", "subAgentReview",
           "subAgentCompact", "subAgentThreadSpawn", "subAgentOther", "unknown"]


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
    print(f"Repairing session index in {os.environ['CODEX_HOME']}...", file=sys.stderr)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
