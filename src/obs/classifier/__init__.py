"""Graph-based classification package."""

from .classify import classify_graph, classify_graph_sync
from .types import (
    # Unified graph types (from obs.graph)
    Edge,
    Graph,
    GraphMeta,
    Node,
    # Classifier-specific types
    ClassifierTimings,
    ClassifyInput,
    ClassifyOptions,
    ClassifyResult,
    TopologyInput,
)

__all__ = [
    # Unified graph types (preferred)
    "Node",
    "Edge",
    "GraphMeta",
    "Graph",
    # Classifier-specific types
    "TopologyInput",
    "ClassifyOptions",
    "ClassifyInput",
    "ClassifierTimings",
    "ClassifyResult",
    # Classification functions
    "classify_graph",
    "classify_graph_sync",
]
