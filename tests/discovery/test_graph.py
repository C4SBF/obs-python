from __future__ import annotations

from obs.discovery.graph import (
    device_to_graph,
    network_scan_result_to_graph,
    objects_result_to_graph,
)
from obs.discovery.types import (
    DiscoveryNetworkScanInput,
    DiscoveryNetworkScanResult,
    DiscoveryObjectsData,
    DiscoveryObjectsInput,
    DiscoveryObjectsResult,
    DiscoveryScanTimings,
    Protocol,
)
from obs.graph import Graph
from tests.factories import make_discovery_device, make_discovery_point


def test_device_to_graph_adds_hasPoint_edge() -> None:
    # given
    point = make_discovery_point(uid="bacnet://192.168.1.10/1001/analogInput:2")
    device = make_discovery_device(points=[point])

    # when
    graph = device_to_graph(device)

    # then
    assert isinstance(graph, Graph)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert graph.edges[0].source == device.uid
    assert graph.edges[0].target == point.uid
    assert graph.edges[0].type == "hasPoint"


def test_objects_result_to_graph_preserves_meta() -> None:
    # given
    device = make_discovery_device(points=[make_discovery_point()])
    result = DiscoveryObjectsResult(
        input=DiscoveryObjectsInput(device=device.uid, network="192.168.1.0/24"),
        data=DiscoveryObjectsData(device=device),
        timings=DiscoveryScanTimings(
            started_at_utc="2026-01-01T00:00:00+00:00",
            finished_at_utc="2026-01-01T00:00:01+00:00",
            duration_seconds=1.0,
        ),
        success=True,
        metadata={"client_ip": "192.168.1.2/24"},
    )

    # when
    graph = objects_result_to_graph(result)

    # then
    assert isinstance(graph, Graph)
    assert graph.meta.success is True
    assert graph.meta.source == "discovery"
    assert graph.meta.input["device"] == device.uid
    assert graph.meta.input["network"] == "192.168.1.0/24"
    assert graph.meta.extra["client_ip"] == "192.168.1.2/24"


def test_network_scan_result_to_graph_builds_nodes_for_all_devices() -> None:
    # given
    device_a = make_discovery_device(
        uid="bacnet://192.168.1.10/1001",
        points=[make_discovery_point(uid="bacnet://192.168.1.10/1001/analogInput:1")],
    )
    device_b = make_discovery_device(
        uid="bacnet://192.168.1.11/1002",
        address="192.168.1.11",
        device_id="1002",
        points=[make_discovery_point(uid="bacnet://192.168.1.11/1002/analogInput:1")],
    )
    result = DiscoveryNetworkScanResult(
        input=DiscoveryNetworkScanInput(protocols=[Protocol.BACNET]),
        data=[device_a, device_b],
        timings=DiscoveryScanTimings(
            started_at_utc="2026-01-01T00:00:00+00:00",
            finished_at_utc="2026-01-01T00:00:01+00:00",
            duration_seconds=1.0,
        ),
        success=True,
    )

    # when
    graph = network_scan_result_to_graph(result)

    # then
    assert isinstance(graph, Graph)
    assert len(graph.nodes) == 4
    assert len(graph.edges) == 2
    assert all(edge.type == "hasPoint" for edge in graph.edges)
