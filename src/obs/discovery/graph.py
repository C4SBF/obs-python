"""Discovery graph adapters (tree -> nodes/edges)."""

from __future__ import annotations

import dataclasses
from enum import StrEnum
from typing import Any

from obs.graph import Edge, Graph, GraphMeta, Node

from .types import (
    Device,
    DiscoveryFullScanResult,
    DiscoveryNetworkScanResult,
    DiscoveryObjectsResult,
)

__all__ = [
    "Node",
    "Edge",
    "GraphMeta",
    "Graph",
    "device_to_graph",
    "network_scan_result_to_graph",
    "objects_result_to_graph",
    "full_scan_result_to_graph",
]


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _to_dict(value)
    if isinstance(value, tuple):
        return [_serialize(v) for v in value]
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return value


def _to_dict(obj: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        value = getattr(obj, f.name)
        if value is None:
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        result[f.name] = _serialize(value)
    return result


def _entity_to_node(entity: Any) -> Node:
    data = _to_dict(entity)
    node_id = str(data.pop("uid"))
    node_type = str(data.pop("kind"))
    # Remove points from device attrs - they're represented as separate nodes + edges
    data.pop("points", None)
    # Flatten extra dict into attrs and remove it
    extra = data.pop("extra", {})
    if isinstance(extra, dict):
        data.update(extra)
    return Node(
        id=node_id,
        type=node_type,
        attrs=data,
    )


def _device_nodes_edges(device: Device) -> tuple[list[Node], list[Edge]]:
    nodes: list[Node] = [_entity_to_node(device)]
    edges: list[Edge] = []
    for point in device.points:
        point_node = _entity_to_node(point)
        nodes.append(point_node)
        edges.append(
            Edge(
                source=device.uid,
                target=point.uid,
                type="hasPoint",
            )
        )
    return nodes, edges


def _meta_from_result(
    *,
    input_data: Any,
    timings: Any,
    success: bool,
    errors: list[str],
    error_details: list[Any],
    metadata: dict[str, Any],
) -> GraphMeta:
    return GraphMeta(
        source="discovery",
        input=_to_dict(input_data),
        timings=_to_dict(timings),
        success=success,
        errors=list(errors),
        error_details=[_to_dict(e) for e in error_details],
        extra=dict(metadata),
    )


def device_to_graph(
    device: Device,
    *,
    meta: GraphMeta | None = None,
) -> Graph:
    nodes, edges = _device_nodes_edges(device)
    return Graph(
        nodes=nodes,
        edges=edges,
        meta=meta or GraphMeta(source="discovery"),
    )


def network_scan_result_to_graph(result: DiscoveryNetworkScanResult) -> Graph:
    nodes: list[Node] = []
    edges: list[Edge] = []
    for device in result.data:
        dn, de = _device_nodes_edges(device)
        nodes.extend(dn)
        edges.extend(de)
    return Graph(
        nodes=nodes,
        edges=edges,
        meta=_meta_from_result(
            input_data=result.input,
            timings=result.timings,
            success=result.success,
            errors=result.errors,
            error_details=result.error_details,
            metadata=result.metadata,
        ),
    )


def objects_result_to_graph(result: DiscoveryObjectsResult) -> Graph:
    return device_to_graph(
        result.data.device,
        meta=_meta_from_result(
            input_data=result.input,
            timings=result.timings,
            success=result.success,
            errors=result.errors,
            error_details=result.error_details,
            metadata=result.metadata,
        ),
    )


def full_scan_result_to_graph(result: DiscoveryFullScanResult) -> Graph:
    nodes: list[Node] = []
    edges: list[Edge] = []
    for device in result.data.devices:
        dn, de = _device_nodes_edges(device)
        nodes.extend(dn)
        edges.extend(de)
    return Graph(
        nodes=nodes,
        edges=edges,
        meta=_meta_from_result(
            input_data=result.input,
            timings=result.timings,
            success=result.success,
            errors=result.errors,
            error_details=result.error_details,
            metadata=result.metadata,
        ),
    )
