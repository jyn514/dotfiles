from pathlib import Path


def plugin_dir() -> Path:
    return Path(__file__).with_name("plugin")
