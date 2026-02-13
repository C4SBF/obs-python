from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from obs.graph import Edge, Graph, GraphMeta, Node
from obs.discovery.types import Device, EntityKind, Point, Protocol, ProtocolRef


def make_protocol_ref(
    *,
    protocol: Protocol = Protocol.BACNET,
    address: str = "192.168.1.10",
    device_id: str = "1001",
    object_id: str | None = None,
    raw: dict[str, Any] | None = None,
) -> ProtocolRef:
    return ProtocolRef(
        protocol=protocol,
        address=address,
        device_id=device_id,
        object_id=object_id,
        raw={} if raw is None else raw,
    )


def make_discovery_point(
    *,
    uid: str = "bacnet://192.168.1.10/1001/analogInput:1",
    name: str = "AI-1",
    data_type: str | None = "float",
    access: str | None = "read",
) -> Point:
    return Point(
        uid=uid,
        kind=EntityKind.POINT,
        name=name,
        data_type=data_type,
        access=access,
        protocol_ref=make_protocol_ref(object_id="analogInput:1"),
    )


def make_discovery_device(
    *,
    uid: str = "bacnet://192.168.1.10/1001",
    name: str = "AHU-1",
    address: str = "192.168.1.10",
    device_id: str = "1001",
    points: list[Point] | None = None,
) -> Device:
    return Device(
        uid=uid,
        kind=EntityKind.DEVICE,
        name=name,
        protocol_ref=make_protocol_ref(address=address, device_id=device_id),
        points=[] if points is None else points,
    )


@dataclass
class FakeRawObjectIdentifier:
    object_type: str
    instance: int


@dataclass
class FakeRawDeviceIdentifier:
    address: str
    device_id: int


@dataclass
class FakeRawBACnetDevice:
    uid: str
    identifier: FakeRawDeviceIdentifier
    name: str | None = "AHU-1"
    vendor: str | None = "Acme"
    object_list: list[FakeRawObjectIdentifier] = field(default_factory=list)


@dataclass
class FakeRawBACnetObject:
    uid: str
    object_identifier: FakeRawObjectIdentifier
    device: FakeRawDeviceIdentifier
    name: str | None = "AI-1"
    description: str | None = "desc"
    units: str | None = "C"
    value: bool | int | float | str | None = 12.3
    metadata: dict[str, Any] = field(default_factory=dict)


def make_graph_node(
    *,
    node_id: str,
    node_type: str,
    tags: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> Node:
    return Node(
        id=node_id,
        type=node_type,
        tags=[] if tags is None else tags,
        attrs={} if attributes is None else attributes,
    )


def make_graph_edge(
    *,
    source: str,
    target: str,
    edge_type: str = "contains",
    attributes: dict[str, Any] | None = None,
) -> Edge:
    return Edge(
        source=source,
        target=target,
        type=edge_type,
        attrs={} if attributes is None else attributes,
    )


def make_graph(
    *,
    nodes: list[Node] | None = None,
    edges: list[Edge] | None = None,
    meta: GraphMeta | None = None,
) -> Graph:
    return Graph(
        nodes=[] if nodes is None else nodes,
        edges=[] if edges is None else edges,
        meta=meta if meta is not None else GraphMeta(),
    )


# Backwards compatibility alias
def make_graph_data(
    *,
    nodes: list[Node] | None = None,
    edges: list[Edge] | None = None,
    context: dict[str, Any] | None = None,
) -> Graph:
    """Deprecated: Use make_graph instead."""
    extra = context if context is not None else {}
    return Graph(
        nodes=[] if nodes is None else nodes,
        edges=[] if edges is None else edges,
        meta=GraphMeta(extra=extra),
    )
