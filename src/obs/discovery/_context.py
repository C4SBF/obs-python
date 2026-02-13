"""Internal context and timing helpers for discovery operations."""

from __future__ import annotations

import functools
import platform
from datetime import datetime, timezone
from pathlib import Path
import tomllib
from typing import Any

from .types import DiscoveryScanTimings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timings(started: datetime, finished: datetime) -> DiscoveryScanTimings:
    return DiscoveryScanTimings(
        started_at_utc=started.isoformat(),
        finished_at_utc=finished.isoformat(),
        duration_seconds=(finished - started).total_seconds(),
    )


@functools.lru_cache(maxsize=1)
def library_version_from_source() -> str | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "pyproject.toml"
        if not candidate.exists():
            continue
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return None
        project = data.get("project", {})
        version = project.get("version")
        return str(version) if version is not None else None
    return None


def scan_context(*, client_ip: str | None) -> dict[str, Any]:
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "client_ip": client_ip,
        "library_version": library_version_from_source(),
    }
