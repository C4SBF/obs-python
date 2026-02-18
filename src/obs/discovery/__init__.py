"""Device discovery — protocol-agnostic scan API."""

from .graph import (
    Edge,
    Graph,
    GraphMeta,
    Node,
    device_to_graph,
    full_scan_result_to_graph,
    network_scan_result_to_graph,
    objects_result_to_graph,
)
from .scan import (
    discover_objects,
    discover_objects_sync,
    full_scan,
    full_scan_sync,
    read_points,
    read_points_sync,
    scan_network,
    scan_network_sync,
)
from .types import (
    DiscoveryFullScanResult,
    DiscoveryNetworkScanResult,
    DiscoveryObjectsResult,
    ReadPointsResult,
)

__all__ = [
    # Scan functions
    "scan_network",
    "scan_network_sync",
    "discover_objects",
    "discover_objects_sync",
    "full_scan",
    "full_scan_sync",
    # Read functions
    "read_points",
    "read_points_sync",
    # Graph types
    "Node",
    "Edge",
    "GraphMeta",
    "Graph",
    # Conversion functions
    "device_to_graph",
    "network_scan_result_to_graph",
    "objects_result_to_graph",
    "full_scan_result_to_graph",
    # Result types
    "DiscoveryNetworkScanResult",
    "DiscoveryObjectsResult",
    "DiscoveryFullScanResult",
    "ReadPointsResult",
]
