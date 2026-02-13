"""Tests for unified graph types."""

from __future__ import annotations

from obs.graph import Edge, Graph, GraphMeta, Node


def test_node_has_slots() -> None:
    node = Node(id="n1", type="device")
    assert node.id == "n1"
    assert node.type == "device"
    assert node.tags == []
    assert node.attrs == {}
    assert hasattr(node, "__slots__")


def test_node_with_tags_and_attrs() -> None:
    node = Node(
        id="bacnet://10.0.0.1/1001",
        type="point",
        tags=["protocol:bacnet", "temperature"],
        attrs={"name": "Zone-Temp", "unit": "F"},
    )
    assert "protocol:bacnet" in node.tags
    assert node.attrs["name"] == "Zone-Temp"


def test_edge_has_slots() -> None:
    edge = Edge(source="d1", target="p1", type="hasPoint")
    assert edge.source == "d1"
    assert edge.target == "p1"
    assert edge.type == "hasPoint"
    assert edge.attrs == {}
    assert hasattr(edge, "__slots__")


def test_edge_with_attrs() -> None:
    edge = Edge(
        source="d1",
        target="p1",
        type="feeds",
        attrs={"inferred": True},
    )
    assert edge.attrs["inferred"] is True


def test_graph_meta_defaults() -> None:
    meta = GraphMeta()
    assert meta.created_at == ""
    assert meta.source == ""
    assert meta.input == {}
    assert meta.timings == {}
    assert meta.success is True
    assert meta.errors == []
    assert meta.error_details == []
    assert meta.extra == {}


def test_graph_meta_with_values() -> None:
    meta = GraphMeta(
        created_at="2026-01-01T00:00:00Z",
        source="discovery",
        input={"network": "10.0.0.0/24"},
        timings={"duration_seconds": 1.5},
        success=True,
        extra={"version": "1.0"},
    )
    assert meta.source == "discovery"
    assert meta.input["network"] == "10.0.0.0/24"


def test_graph_defaults() -> None:
    graph = Graph()
    assert graph.nodes == []
    assert graph.edges == []
    assert isinstance(graph.meta, GraphMeta)


def test_graph_with_nodes_and_edges() -> None:
    device = Node(id="d1", type="device", attrs={"name": "AHU-1"})
    point = Node(id="p1", type="point", attrs={"name": "Zone-Temp"})
    edge = Edge(source="d1", target="p1", type="hasPoint")
    meta = GraphMeta(source="discovery", success=True)

    graph = Graph(nodes=[device, point], edges=[edge], meta=meta)

    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert graph.meta.source == "discovery"


def test_graph_node_lookup() -> None:
    nodes = [
        Node(id="d1", type="device"),
        Node(id="p1", type="point"),
        Node(id="p2", type="point"),
    ]
    graph = Graph(nodes=nodes)

    by_id = {n.id: n for n in graph.nodes}
    assert by_id["d1"].type == "device"
    assert by_id["p1"].type == "point"
