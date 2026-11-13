from pathlib import Path


def rst_plugin_dir() -> Path:
    return Path(__file__).with_name("plugin")


def markdown_mermaid_plugin_dir() -> Path:
    return Path(__file__).with_name("markdown_mermaid_plugin")


def plugin_dir() -> Path:
    return rst_plugin_dir()
