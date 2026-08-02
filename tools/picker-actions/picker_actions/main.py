"""Command-line entry point for external picker actions."""

from __future__ import annotations

import sys

from picker_actions import edit, open_action, search


def main(arguments: list[str]) -> int:
    if not arguments:
        print("usage: picker-action action [selection options]", file=sys.stderr)
        return 2
    action, action_arguments = arguments[0], arguments[1:]
    if action == "edit":
        return edit.main(action_arguments)
    if action == "open":
        return open_action.main(action_arguments)
    if action == "search":
        return search.main(action_arguments)
    print(f"unknown picker action: {action}", file=sys.stderr)
    return 2
