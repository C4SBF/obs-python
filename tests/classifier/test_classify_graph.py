from __future__ import annotations

import asyncio

from obs.classifier import (
    ClassifyOptions,
    Graph,
    TopologyInput,
    classify_graph,
    classify_graph_sync,
)
from tests.factories import make_graph, make_graph_edge, make_graph_node


def _make_test_ontology(prefix: str = "test") -> dict:
    """Create a minimal test ontology with common classes."""
    base_uri = f"https://example.org/{prefix}#"
    return {
        "@graph": [
            {
                "@id": f"{base_uri}Temperature_Sensor",
                "@type": "owl:Class",
                "rdfs:label": "Temperature Sensor",
            },
            {
                "@id": f"{base_uri}Flow_Sensor",
                "@type": "owl:Class",
                "rdfs:label": "Flow Sensor",
            },
            {"@id": f"{base_uri}Sensor", "@type": "owl:Class", "rdfs:label": "Sensor"},
            {
                "@id": f"{base_uri}Setpoint",
                "@type": "owl:Class",
                "rdfs:label": "Setpoint",
            },
            {
                "@id": f"{base_uri}Equipment",
                "@type": "owl:Class",
                "rdfs:label": "Equipment",
            },
            {"@id": f"{base_uri}Point", "@type": "owl:Class", "rdfs:label": "Point"},
            {
                "@id": f"{base_uri}Binary_Point",
                "@type": "owl:Class",
                "rdfs:label": "Binary Point",
            },
            {
                "@id": f"{base_uri}Status_Point",
                "@type": "owl:Class",
                "rdfs:label": "Status Point",
            },
            {
                "@id": f"{base_uri}Analog_Point",
                "@type": "owl:Class",
                "rdfs:label": "Analog Point",
            },
        ]
    }


def test_classify_graph_enriches_nodes_and_edges() -> None:
    # given
    device = make_graph_node(
        node_id="d1", node_type="device", attributes={"name": "AHU-1"}
    )
    point = make_graph_node(
        node_id="p1",
        node_type="point",
        attributes={
            "quantity": "temperature",
            "unit": "F",
            "point_type": "analogInput",
        },
    )
    graph = make_graph(
        nodes=[device, point],
        edges=[make_graph_edge(source="d1", target="p1", edge_type="contains")],
    )

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(id="test_ontology", content=_make_test_ontology("test")),
    )

    # then
    assert result.success is True
    assert isinstance(result.graph, Graph)
    assert len(result.graph.nodes) == 2
    assert any(edge.type == "hasPoint" for edge in result.graph.edges)
    point_node = next(node for node in result.graph.nodes if node.id == "p1")
    assert point_node.attrs["class"] == "test:Temperature_Sensor"
    assert point_node.attrs["class_confidence"] >= 0.9


def test_classify_graph_uses_inline_topology_without_network() -> None:
    # given
    graph = make_graph(
        nodes=[
            make_graph_node(
                node_id="p1",
                node_type="point",
                attributes={"point_type": "binaryInput"},
            )
        ],
        edges=[],
    )

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(content=_make_test_ontology("test")),
    )

    # then
    assert result.success is True
    assert result.metadata["topology_ref"] == "inline"


def test_classify_graph_respects_min_confidence() -> None:
    # given
    graph = make_graph(
        nodes=[
            make_graph_node(
                node_id="p1", node_type="point", attributes={"name": "unknown"}
            )
        ],
        edges=[],
    )

    # when
    result = asyncio.run(
        classify_graph(
            graph,
            TopologyInput(id="test_ontology", content=_make_test_ontology("test")),
            options=ClassifyOptions(min_confidence=0.9),
        )
    )

    # then
    assert result.success is True
    node = result.graph.nodes[0]
    # With high min_confidence and generic name, no class should be assigned
    assert "class" not in node.attrs or node.attrs["class_confidence"] < 0.9


def test_classify_graph_fails_without_topology_reference() -> None:
    # given
    graph = make_graph(
        nodes=[make_graph_node(node_id="p1", node_type="point")],
        edges=[],
    )

    # when
    result = classify_graph_sync(graph, TopologyInput())

    # then
    assert result.success is False
    assert result.errors


def test_classify_graph_loads_topology_from_url(monkeypatch) -> None:
    # given
    import json

    graph = make_graph(
        nodes=[
            make_graph_node(
                node_id="p1", node_type="point", attributes={"quantity": "flow"}
            )
        ],
        edges=[],
    )

    ontology_content = json.dumps(_make_test_ontology("remote")).encode("utf-8")

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return ontology_content

    monkeypatch.setattr(
        "obs.classifier.classify.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(),
    )

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(url="https://example.org/ontology.jsonld"),
    )

    # then
    assert result.success is True
    assert result.metadata["topology_ref"] == "https://example.org/ontology.jsonld"
    # Verify classification worked with remote ontology
    node = result.graph.nodes[0]
    assert node.attrs.get("class") == "remote:Flow_Sensor"


def _make_pump_station_ontology() -> dict:
    """Create ontology with pump station and related classes."""
    base_uri = "https://brickschema.org/schema/Brick#"
    return {
        "@graph": [
            {"@id": f"{base_uri}Pump", "@type": "owl:Class", "rdfs:label": "Pump"},
            {"@id": f"{base_uri}Tank", "@type": "owl:Class", "rdfs:label": "Tank"},
            {
                "@id": f"{base_uri}Pump_Station",
                "@type": "owl:Class",
                "rdfs:label": "Pump Station",
            },
            {
                "@id": f"{base_uri}Pump_Group",
                "@type": "owl:Class",
                "rdfs:label": "Pump Group",
            },
            {
                "@id": f"{base_uri}Water_System",
                "@type": "owl:Class",
                "rdfs:label": "Water System",
            },
            {
                "@id": f"{base_uri}Equipment",
                "@type": "owl:Class",
                "rdfs:label": "Equipment",
            },
            {"@id": f"{base_uri}Status", "@type": "owl:Class", "rdfs:label": "Status"},
            {"@id": f"{base_uri}Sensor", "@type": "owl:Class", "rdfs:label": "Sensor"},
            {
                "@id": f"{base_uri}Flow_Sensor",
                "@type": "owl:Class",
                "rdfs:label": "Flow Sensor",
            },
            {
                "@id": f"{base_uri}Level_Sensor",
                "@type": "owl:Class",
                "rdfs:label": "Level Sensor",
            },
        ]
    }


def test_classify_composite_pump_station() -> None:
    """Test that a device with multiple pumps and tanks is classified as Pump_Station."""
    # given - A BACnet device with pump and tank points
    device = make_graph_node(
        node_id="device:BACnetDevice_240140",
        node_type="device",
        attributes={"name": "Pump Station Controller"},
    )
    points = [
        # Pump 1 points
        make_graph_node(node_id="p1", node_type="point", attributes={"name": "P1_Run"}),
        make_graph_node(
            node_id="p2", node_type="point", attributes={"name": "P1_Fail"}
        ),
        make_graph_node(
            node_id="p3", node_type="point", attributes={"name": "P1_Speed"}
        ),
        # Pump 2 points
        make_graph_node(node_id="p4", node_type="point", attributes={"name": "P2_Run"}),
        make_graph_node(
            node_id="p5", node_type="point", attributes={"name": "P2_Fail"}
        ),
        make_graph_node(
            node_id="p6", node_type="point", attributes={"name": "P2_Speed"}
        ),
        # Tank 1 points
        make_graph_node(
            node_id="p7", node_type="point", attributes={"name": "Tank1_LL"}
        ),
        make_graph_node(
            node_id="p8", node_type="point", attributes={"name": "Tank1_HL"}
        ),
        # Tank 2 points
        make_graph_node(
            node_id="p9", node_type="point", attributes={"name": "Tank2_LL"}
        ),
        make_graph_node(
            node_id="p10", node_type="point", attributes={"name": "Tank2_Level"}
        ),
    ]

    edges = [
        make_graph_edge(source=device.id, target=p.id, edge_type="contains")
        for p in points
    ]
    graph = make_graph(nodes=[device] + points, edges=edges)

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(content=_make_pump_station_ontology()),
    )

    # then
    assert result.success is True

    # Device should be classified as Pump_Station
    device_node = next(n for n in result.graph.nodes if n.id == device.id)
    assert device_node.attrs.get("class") == "brick:Pump_Station"
    assert device_node.attrs.get("class_confidence", 0) >= 0.7

    # Check evidence includes sub-equipment info
    candidates = device_node.attrs.get("class_candidates", [])
    assert len(candidates) > 0
    assert "sub_equipment" in candidates[0]
    sub_equipment = candidates[0]["sub_equipment"]
    assert "P1" in sub_equipment
    assert "P2" in sub_equipment
    assert "Tank1" in sub_equipment
    assert "Tank2" in sub_equipment


def test_classify_creates_sub_equipment_nodes() -> None:
    """Test that sub-equipment nodes are created for composite devices."""
    # given
    device = make_graph_node(
        node_id="device:Controller1",
        node_type="device",
        attributes={"name": "Multi-Pump Controller"},
    )
    points = [
        make_graph_node(node_id="p1", node_type="point", attributes={"name": "P1_Run"}),
        make_graph_node(
            node_id="p2", node_type="point", attributes={"name": "P1_Status"}
        ),
        make_graph_node(node_id="p3", node_type="point", attributes={"name": "P2_Run"}),
        make_graph_node(
            node_id="p4", node_type="point", attributes={"name": "P2_Status"}
        ),
    ]
    edges = [
        make_graph_edge(source=device.id, target=p.id, edge_type="contains")
        for p in points
    ]
    graph = make_graph(nodes=[device] + points, edges=edges)

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(content=_make_pump_station_ontology()),
    )

    # then
    assert result.success is True

    # Should create sub-equipment nodes for P1 and P2
    equipment_nodes = [n for n in result.graph.nodes if n.type == "equipment"]
    assert len(equipment_nodes) == 2

    # Check equipment nodes have correct attributes
    p1_equip = next((n for n in equipment_nodes if "P1" in n.id), None)
    p2_equip = next((n for n in equipment_nodes if "P2" in n.id), None)
    assert p1_equip is not None
    assert p2_equip is not None
    assert p1_equip.attrs.get("class") == "brick:Pump"
    assert p2_equip.attrs.get("class") == "brick:Pump"

    # Check composition edges from device to sub-equipment (hasPart or contains)
    composition_edges = [
        e
        for e in result.graph.edges
        if e.type in ("contains", "hasPart") and e.source == device.id
    ]
    sub_equip_targets = {
        e.target for e in composition_edges if "equipment:" in e.target
    }
    assert len(sub_equip_targets) == 2

    # Check hasPoint edges from sub-equipment to points
    has_point_edges = [e for e in result.graph.edges if e.type == "hasPoint"]
    sub_equip_point_edges = [e for e in has_point_edges if "equipment:" in e.source]
    assert len(sub_equip_point_edges) == 4  # 2 points per pump


def test_classify_pump_group_without_tanks() -> None:
    """Test that multiple pumps without tanks are classified as Pump_Group."""
    # given
    device = make_graph_node(
        node_id="device:PumpController",
        node_type="device",
        attributes={"name": "Pump Group"},
    )
    points = [
        make_graph_node(node_id="p1", node_type="point", attributes={"name": "P1_Run"}),
        make_graph_node(node_id="p2", node_type="point", attributes={"name": "P2_Run"}),
        make_graph_node(node_id="p3", node_type="point", attributes={"name": "P3_Run"}),
    ]
    edges = [
        make_graph_edge(source=device.id, target=p.id, edge_type="contains")
        for p in points
    ]
    graph = make_graph(nodes=[device] + points, edges=edges)

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(content=_make_pump_station_ontology()),
    )

    # then
    assert result.success is True
    device_node = next(n for n in result.graph.nodes if n.id == device.id)
    assert device_node.attrs.get("class") == "brick:Pump_Group"


def test_classify_single_equipment_not_composite() -> None:
    """Test that a device with single equipment type is not classified as composite."""
    # given - Device with only one pump
    device = make_graph_node(
        node_id="device:SinglePump",
        node_type="device",
        attributes={"name": "Single Pump Controller"},
    )
    points = [
        make_graph_node(
            node_id="p1", node_type="point", attributes={"name": "Pump_Run"}
        ),
        make_graph_node(
            node_id="p2", node_type="point", attributes={"name": "Pump_Status"}
        ),
        make_graph_node(
            node_id="p3", node_type="point", attributes={"name": "Pump_Speed"}
        ),
    ]
    edges = [
        make_graph_edge(source=device.id, target=p.id, edge_type="contains")
        for p in points
    ]
    graph = make_graph(nodes=[device] + points, edges=edges)

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(content=_make_pump_station_ontology()),
    )

    # then
    assert result.success is True
    device_node = next(n for n in result.graph.nodes if n.id == device.id)
    # Single pump should be classified as Pump, not a composite system
    assert device_node.attrs.get("class") == "brick:Pump"
    # No sub-equipment nodes should be created
    equipment_nodes = [n for n in result.graph.nodes if n.type == "equipment"]
    assert len(equipment_nodes) == 0


def test_classify_excludes_bacnet_object_prefixes() -> None:
    """Test that BACnet object prefixes (BV, AV, AI, etc.) don't create sub-equipment."""
    # given - Device with BACnet-style point names
    device = make_graph_node(
        node_id="device:BACnetController",
        node_type="device",
        attributes={"name": "BACnet Controller"},
    )
    points = [
        # BACnet object type prefixes - should NOT create sub-equipment
        make_graph_node(
            node_id="p1", node_type="point", attributes={"name": "BV100343_OCS"}
        ),
        make_graph_node(
            node_id="p2", node_type="point", attributes={"name": "BV100344_Status"}
        ),
        make_graph_node(
            node_id="p3", node_type="point", attributes={"name": "AV200_Temp"}
        ),
        make_graph_node(
            node_id="p4", node_type="point", attributes={"name": "AI300_Flow"}
        ),
        make_graph_node(
            node_id="p5", node_type="point", attributes={"name": "BO400_Command"}
        ),
    ]
    edges = [
        make_graph_edge(source=device.id, target=p.id, edge_type="contains")
        for p in points
    ]
    graph = make_graph(nodes=[device] + points, edges=edges)

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(content=_make_pump_station_ontology()),
    )

    # then
    assert result.success is True
    # No sub-equipment nodes should be created for BACnet object prefixes
    equipment_nodes = [n for n in result.graph.nodes if n.type == "equipment"]
    assert len(equipment_nodes) == 0

    # Device should not be classified as a composite system
    device_node = next(n for n in result.graph.nodes if n.id == device.id)
    assert device_node.attrs.get("class") != "brick:Pump_Station"
    assert device_node.attrs.get("class") != "brick:Pump_Group"


def _make_ontology_with_relations() -> dict:
    """Create ontology with defined relations (domain/range)."""
    base_uri = "https://brickschema.org/schema/Brick#"
    return {
        "@graph": [
            # Classes - include all classes used by composite detection
            {
                "@id": f"{base_uri}Equipment",
                "@type": "owl:Class",
                "rdfs:label": "Equipment",
            },
            {"@id": f"{base_uri}Point", "@type": "owl:Class", "rdfs:label": "Point"},
            {
                "@id": f"{base_uri}Pump",
                "@type": "owl:Class",
                "rdfs:label": "Pump",
                "rdfs:subClassOf": {"@id": f"{base_uri}Equipment"},
            },
            {
                "@id": f"{base_uri}Pump_Station",
                "@type": "owl:Class",
                "rdfs:label": "Pump Station",
                "rdfs:subClassOf": {"@id": f"{base_uri}Equipment"},
            },
            {
                "@id": f"{base_uri}Pump_Group",
                "@type": "owl:Class",
                "rdfs:label": "Pump Group",
                "rdfs:subClassOf": {"@id": f"{base_uri}Equipment"},
            },
            {
                "@id": f"{base_uri}Sensor",
                "@type": "owl:Class",
                "rdfs:label": "Sensor",
                "rdfs:subClassOf": {"@id": f"{base_uri}Point"},
            },
            {
                "@id": f"{base_uri}Status",
                "@type": "owl:Class",
                "rdfs:label": "Status",
                "rdfs:subClassOf": {"@id": f"{base_uri}Point"},
            },
            # Relations with domain/range
            {
                "@id": f"{base_uri}hasPoint",
                "@type": "owl:ObjectProperty",
                "rdfs:label": "has point",
                "rdfs:domain": {"@id": f"{base_uri}Equipment"},
                "rdfs:range": {"@id": f"{base_uri}Point"},
            },
            {
                "@id": f"{base_uri}isPointOf",
                "@type": "owl:ObjectProperty",
                "rdfs:label": "is point of",
                "owl:inverseOf": {"@id": f"{base_uri}hasPoint"},
            },
            {
                "@id": f"{base_uri}hasPart",
                "@type": "owl:ObjectProperty",
                "rdfs:label": "has part",
                "rdfs:domain": {"@id": f"{base_uri}Equipment"},
                "rdfs:range": {"@id": f"{base_uri}Equipment"},
            },
            {
                "@id": f"{base_uri}isPartOf",
                "@type": "owl:ObjectProperty",
                "rdfs:label": "is part of",
                "owl:inverseOf": {"@id": f"{base_uri}hasPart"},
            },
        ]
    }


def test_classify_uses_ontology_relations() -> None:
    """Test that edges use relations defined in the ontology."""
    # given - Ontology with hasPoint and hasPart relations defined
    device = make_graph_node(
        node_id="device:PumpStation1",
        node_type="device",
        attributes={"name": "Pump Station 1"},
    )
    points = [
        make_graph_node(node_id="p1", node_type="point", attributes={"name": "P1_Run"}),
        make_graph_node(
            node_id="p2", node_type="point", attributes={"name": "P1_Status"}
        ),
        make_graph_node(node_id="p3", node_type="point", attributes={"name": "P2_Run"}),
        make_graph_node(
            node_id="p4", node_type="point", attributes={"name": "P2_Status"}
        ),
    ]
    edges = [
        make_graph_edge(source=device.id, target=p.id, edge_type="contains")
        for p in points
    ]
    graph = make_graph(nodes=[device] + points, edges=edges)

    # when
    result = classify_graph_sync(
        graph,
        TopologyInput(content=_make_ontology_with_relations()),
    )

    # then
    assert result.success is True

    # Check that edges have ontology_relation attribute
    inferred_edges = [e for e in result.graph.edges if e.attrs.get("inferred")]
    assert len(inferred_edges) > 0

    # Edges from sub-equipment to points should reference hasPoint
    point_edges = [e for e in inferred_edges if e.target in ["p1", "p2", "p3", "p4"]]
    for edge in point_edges:
        # Should have ontology_relation attribute
        assert "ontology_relation" in edge.attrs
        # Edge type should be hasPoint (from ontology lookup)
        assert edge.type == "hasPoint"
