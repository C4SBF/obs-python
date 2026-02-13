"""Unified graph types for OBS.

This module defines the canonical graph format used throughout OBS:
- Discovery outputs Graph
- Classification enriches Graph
- API returns Graph
- CLI saves Graph
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Node:
    """A node in the graph (device, point, equipment, etc.)."""

    id: str
    type: str  # "device" | "point" | "equipment" | ...
    tags: list[str] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Edge:
    """A relationship between two nodes."""

    source: str
    target: str
    type: str  # "hasPoint" | "feeds" | "locatedIn" | ...
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphMeta:
    """Metadata about the graph and how it was produced."""

    created_at: str = ""
    source: str = ""  # "discovery" | "classification" | "manual"
    input: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    errors: list[str] = field(default_factory=list)
    error_details: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Graph:
    """A collection of nodes and edges with metadata."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    meta: GraphMeta = field(default_factory=GraphMeta)
