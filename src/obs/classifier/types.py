"""Graph classifier data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from obs.graph import Edge, Graph, GraphMeta, Node

# Re-export unified types for backwards compatibility
__all__ = [
    "Node",
    "Edge",
    "GraphMeta",
    "Graph",
    "ClassifierTimings",
    "TopologyInput",
    "ClassifyOptions",
    "ClassifyInput",
    "ClassifyResult",
    "utc_now",
    "build_timings",
]


@dataclass(slots=True)
class ClassifierTimings:
    started_at_utc: str
    finished_at_utc: str
    duration_seconds: float


@dataclass(slots=True)
class TopologyInput:
    id: str | None = None
    url: str | None = None
    content: dict[str, Any] | list[Any] | str | None = None
    format: str | None = None


@dataclass(slots=True)
class ClassifyOptions:
    min_confidence: float = 0.5
    use_llm: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ClassifyInput:
    graph: Graph
    topology: TopologyInput
    options: ClassifyOptions = field(default_factory=ClassifyOptions)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ClassifyResult:
    input: ClassifyInput
    graph: Graph
    timings: ClassifierTimings
    success: bool
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now().astimezone()


def build_timings(started: datetime, finished: datetime) -> ClassifierTimings:
    return ClassifierTimings(
        started_at_utc=started.isoformat(),
        finished_at_utc=finished.isoformat(),
        duration_seconds=(finished - started).total_seconds(),
    )
