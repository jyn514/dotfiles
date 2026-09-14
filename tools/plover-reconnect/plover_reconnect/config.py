"""The persisted selected-device boundary."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_NAME = "plover-reconnect.json"


def config_path() -> Path:
    from plover.config import CONFIG_DIR
    return Path(CONFIG_DIR) / CONFIG_NAME


@dataclass(frozen=True)
class DeviceFingerprint:
    vid: int
    pid: int
    manufacturer: str | None = None
    product: str | None = None

    def matches(self, device: Any) -> bool:
        return self.vid == device.vid and self.pid == device.pid

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "device": {
                "vid": self.vid,
                "pid": self.pid,
                "manufacturer": self.manufacturer,
                "product": self.product,
            },
        }


def _string_or_none(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    return value


def parse(value: object) -> DeviceFingerprint:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("unsupported configuration schema")
    if set(value) != {"schema", "device"}:
        raise ValueError("configuration contains unknown fields")
    device = value.get("device")
    if not isinstance(device, dict):
        raise ValueError("device must be an object")
    if set(device) != {"vid", "pid", "manufacturer", "product"}:
        raise ValueError("device contains unknown fields")
    vid, pid = device.get("vid"), device.get("pid")
    if (not isinstance(vid, int) or isinstance(vid, bool) or vid < 0 or
            not isinstance(pid, int) or isinstance(pid, bool) or pid < 0):
        raise ValueError("vid and pid must be non-negative integers")
    return DeviceFingerprint(
        vid, pid, _string_or_none(device.get("manufacturer"), "manufacturer"),
        _string_or_none(device.get("product"), "product"),
    )


def read(path: Path) -> DeviceFingerprint:
    with path.open(encoding="utf-8") as stream:
        return parse(json.load(stream))


def write(path: Path, fingerprint: DeviceFingerprint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(fingerprint.as_dict(), stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
