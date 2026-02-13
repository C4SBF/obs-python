"""Generic serialization utilities for dataclass ↔ dict conversion."""

from __future__ import annotations

import dataclasses
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


def _serialize(value: Any) -> Any:
    """Recursively convert a value for JSON output."""
    if isinstance(value, StrEnum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_dict(value)
    if isinstance(value, tuple):
        return [_serialize(v) for v in value]
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return value


def to_dict(obj: Any) -> dict[str, Any]:
    """Serialize any dataclass, skipping None and empty collections."""
    result: dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        value = getattr(obj, f.name)
        if value is None:
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        result[f.name] = _serialize(value)
    return result


def to_json(obj: Any, *, indent: int = 2) -> str:
    """Serialize a dataclass-like object into JSON text."""
    return json.dumps(to_dict(obj), indent=indent)


def to_yaml(obj: Any) -> str:
    """Serialize a dataclass-like object into YAML text."""
    return yaml.safe_dump(to_dict(obj), sort_keys=False)


def dump_json(obj: Any, path: str | Path, *, indent: int = 2) -> None:
    """Write a dataclass-like object as JSON to disk."""
    Path(path).write_text(to_json(obj, indent=indent), encoding="utf-8")


def dump_yaml(obj: Any, path: str | Path) -> None:
    """Write a dataclass-like object as YAML to disk."""
    Path(path).write_text(to_yaml(obj), encoding="utf-8")
