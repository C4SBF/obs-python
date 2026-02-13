"""Tests for LLM-based graph enhancement."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from obs.graph import Node
from obs.llm import (
    LLMBackend,
    LLMOptions,
    LLMResult,
    enhance_graph,
    enhance_graph_sync,
)
from obs.llm.enhance import _build_prompt, _extract_node_context, _parse_llm_response
from tests.factories import make_graph, make_graph_node


def _make_classified_node(
    node_id: str,
    name: str,
    node_class: str,
    confidence: float,
) -> Node:
    """Create a node with classification attributes."""
    return make_graph_node(
        node_id=node_id,
        node_type="point",
        attributes={
            "name": name,
            "class": node_class,
            "class_confidence": confidence,
            "class_candidates": [
                {"class": node_class, "confidence": confidence},
                {"class": "alternate:Class", "confidence": confidence - 0.1},
            ],
        },
    )


def _make_llm_response(suggestions: list[dict]) -> dict:
    """Create a mock OpenAI-compatible response."""
    return {
        "choices": [{"message": {"content": json.dumps({"suggestions": suggestions})}}]
    }


class TestExtractNodeContext:
    """Tests for _extract_node_context helper."""

    def test_extracts_basic_fields(self) -> None:
        node = make_graph_node(
            node_id="p1",
            node_type="point",
            attributes={"name": "Zone-Temp", "description": "Zone temperature sensor"},
        )

        context = _extract_node_context(node, [])

        assert context["id"] == "p1"
        assert context["type"] == "point"
        assert context["name"] == "Zone-Temp"
        assert context["description"] == "Zone temperature sensor"

    def test_includes_classification(self) -> None:
        node = _make_classified_node(
            "p1", "Zone-Temp", "brick:Temperature_Sensor", 0.85
        )

        context = _extract_node_context(node, [])

        assert context["current_class"] == "brick:Temperature_Sensor"
        assert context["current_confidence"] == 0.85
        assert "candidates" in context
        assert len(context["candidates"]) == 2

    def test_includes_relationships(self) -> None:
        node = make_graph_node(
            node_id="p1", node_type="point", attributes={"name": "Temp"}
        )
        edges = [
            ("d1", "p1", "hasPoint"),
            ("p1", "p2", "feeds"),
        ]

        context = _extract_node_context(node, edges)

        assert "relationships" in context
        assert len(context["relationships"]) == 1
        assert context["relationships"][0]["target"] == "p2"
        assert context["relationships"][0]["relation"] == "feeds"


class TestBuildPrompt:
    """Tests for prompt building."""

    def test_builds_valid_prompt(self) -> None:
        context = [
            {
                "id": "p1",
                "type": "point",
                "name": "Zone-Temp",
                "current_class": "brick:Sensor",
                "current_confidence": 0.6,
            }
        ]

        prompt = _build_prompt(context)

        assert "Zone-Temp" in prompt
        assert "brick:Sensor" in prompt
        assert "JSON" in prompt
        assert "suggestions" in prompt


class TestParseLLMResponse:
    """Tests for response parsing."""

    def test_parses_valid_json(self) -> None:
        response = json.dumps(
            {
                "suggestions": [
                    {
                        "node_id": "p1",
                        "suggested_class": "brick:Temperature_Sensor",
                        "confidence": 0.92,
                        "reasoning": "Name contains 'temp'",
                    }
                ]
            }
        )

        suggestions = _parse_llm_response(response)

        assert len(suggestions) == 1
        assert suggestions[0]["node_id"] == "p1"
        assert suggestions[0]["suggested_class"] == "brick:Temperature_Sensor"
        assert suggestions[0]["confidence"] == 0.92

    def test_parses_json_in_markdown(self) -> None:
        response = """Here's my analysis:

```json
{
  "suggestions": [
    {"node_id": "p1", "suggested_class": "brick:Sensor", "confidence": 0.9, "reasoning": "test"}
  ]
}
```
"""

        suggestions = _parse_llm_response(response)

        assert len(suggestions) == 1
        assert suggestions[0]["node_id"] == "p1"

    def test_returns_empty_on_invalid_json(self) -> None:
        response = "This is not valid JSON at all"

        suggestions = _parse_llm_response(response)

        assert suggestions == []

    def test_returns_empty_on_no_suggestions_key(self) -> None:
        response = json.dumps({"other": "data"})

        suggestions = _parse_llm_response(response)

        assert suggestions == []


class TestEnhanceGraphAPIBackend:
    """Tests for enhance_graph with API backend."""

    def test_returns_original_graph_when_no_low_confidence_nodes(self) -> None:
        # All nodes have high confidence
        node = _make_classified_node(
            "p1", "Zone-Temp", "brick:Temperature_Sensor", 0.95
        )
        graph = make_graph(nodes=[node], edges=[])
        options = LLMOptions(backend="api", min_confidence_threshold=0.7)

        result = asyncio.run(enhance_graph(graph, options=options))

        assert result.success is True
        assert result.graph is graph
        assert result.metadata["nodes_evaluated"] == 0
        assert len(result.enhancements) == 0

    def test_enhances_low_confidence_nodes(self) -> None:
        # Node with low confidence should be evaluated
        node = _make_classified_node("p1", "Zone-Temp", "brick:Sensor", 0.55)
        graph = make_graph(nodes=[node], edges=[])
        options = LLMOptions(backend="api", min_confidence_threshold=0.7)

        mock_response = _make_llm_response(
            [
                {
                    "node_id": "p1",
                    "suggested_class": "brick:Temperature_Sensor",
                    "confidence": 0.92,
                    "reasoning": "Name 'Zone-Temp' indicates temperature sensor",
                }
            ]
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_client.post.return_value = mock_response_obj
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = asyncio.run(enhance_graph(graph, options=options))

        assert result.success is True
        assert result.metadata["nodes_evaluated"] == 1
        assert result.metadata["nodes_enhanced"] == 1
        assert result.metadata["backend"] == "api"
        assert len(result.enhancements) == 1

        enhancement = result.enhancements[0]
        assert enhancement.node_id == "p1"
        assert enhancement.original_class == "brick:Sensor"
        assert enhancement.suggested_class == "brick:Temperature_Sensor"
        assert enhancement.applied is True

        # Check enhanced graph
        enhanced_node = result.graph.nodes[0]
        assert enhanced_node.attrs["class"] == "brick:Temperature_Sensor"
        assert enhanced_node.attrs["class_confidence"] == 0.92
        assert enhanced_node.attrs["llm_enhanced"] is True

    def test_does_not_apply_lower_confidence_suggestions(self) -> None:
        node = _make_classified_node("p1", "Zone-Temp", "brick:Sensor", 0.65)
        graph = make_graph(nodes=[node], edges=[])
        options = LLMOptions(backend="api", min_confidence_threshold=0.7)

        # LLM suggests with lower confidence than original
        mock_response = _make_llm_response(
            [
                {
                    "node_id": "p1",
                    "suggested_class": "brick:Temperature_Sensor",
                    "confidence": 0.60,  # Lower than 0.65
                    "reasoning": "Some reasoning",
                }
            ]
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_client.post.return_value = mock_response_obj
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = asyncio.run(enhance_graph(graph, options=options))

        assert result.success is True
        assert len(result.enhancements) == 1
        assert result.enhancements[0].applied is False
        assert result.metadata["nodes_enhanced"] == 0

        # Original class should be preserved
        assert result.graph.nodes[0].attrs["class"] == "brick:Sensor"

    def test_graceful_fallback_on_llm_error(self) -> None:
        node = _make_classified_node("p1", "Zone-Temp", "brick:Sensor", 0.55)
        graph = make_graph(nodes=[node], edges=[])
        options = LLMOptions(backend="api", min_confidence_threshold=0.7)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = asyncio.run(enhance_graph(graph, options=options))

        assert result.success is False
        assert len(result.errors) > 0
        # Original graph should be returned
        assert result.graph.nodes[0].attrs["class"] == "brick:Sensor"

    def test_preserves_original_graph_reference(self) -> None:
        node = _make_classified_node("p1", "Zone-Temp", "brick:Sensor", 0.55)
        graph = make_graph(nodes=[node], edges=[])
        options = LLMOptions(backend="api", min_confidence_threshold=0.7)

        mock_response = _make_llm_response(
            [
                {
                    "node_id": "p1",
                    "suggested_class": "brick:Temperature_Sensor",
                    "confidence": 0.92,
                    "reasoning": "test",
                }
            ]
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_client.post.return_value = mock_response_obj
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = asyncio.run(enhance_graph(graph, options=options))

        # Original graph should be preserved for comparison
        assert result.original_graph is graph
        assert result.original_graph.nodes[0].attrs["class"] == "brick:Sensor"
        # Enhanced graph should be different
        assert result.graph.nodes[0].attrs["class"] == "brick:Temperature_Sensor"


class TestEnhanceGraphTransformersBackend:
    """Tests for enhance_graph with transformers backend."""

    def test_uses_transformers_backend_by_default(self) -> None:
        options = LLMOptions()
        assert options.backend == LLMBackend.TRANSFORMERS

    def test_enhances_with_transformers_backend(self) -> None:
        node = _make_classified_node("p1", "Zone-Temp", "brick:Sensor", 0.55)
        graph = make_graph(nodes=[node], edges=[])
        options = LLMOptions(backend="transformers", min_confidence_threshold=0.7)

        response_json = json.dumps(
            {
                "suggestions": [
                    {
                        "node_id": "p1",
                        "suggested_class": "brick:Temperature_Sensor",
                        "confidence": 0.92,
                        "reasoning": "Temperature in name",
                    }
                ]
            }
        )

        with patch("obs.llm.enhance._call_llm_transformers_sync") as mock_call:
            mock_call.return_value = (response_json, 0.5)

            result = asyncio.run(enhance_graph(graph, options=options))

        assert result.success is True
        assert result.metadata["backend"] == "transformers"
        assert result.metadata["nodes_enhanced"] == 1

        enhanced_node = result.graph.nodes[0]
        assert enhanced_node.attrs["class"] == "brick:Temperature_Sensor"

    def test_transformers_fallback_on_error(self) -> None:
        node = _make_classified_node("p1", "Zone-Temp", "brick:Sensor", 0.55)
        graph = make_graph(nodes=[node], edges=[])
        options = LLMOptions(backend="transformers", min_confidence_threshold=0.7)

        with patch("obs.llm.enhance._call_llm_transformers_sync") as mock_call:
            mock_call.side_effect = Exception("Model not found")

            result = asyncio.run(enhance_graph(graph, options=options))

        assert result.success is False
        assert len(result.errors) > 0
        assert result.metadata["backend"] == "transformers"


class TestEnhanceGraphSync:
    """Tests for synchronous wrapper."""

    def test_sync_wrapper_works(self) -> None:
        node = _make_classified_node(
            "p1", "Zone-Temp", "brick:Temperature_Sensor", 0.95
        )
        graph = make_graph(nodes=[node], edges=[])
        # Use API backend to avoid transformers import in tests
        options = LLMOptions(backend="api")

        result = enhance_graph_sync(graph, options=options)

        assert isinstance(result, LLMResult)
        assert result.success is True


class TestLLMOptions:
    """Tests for LLMOptions configuration."""

    def test_default_options(self) -> None:
        options = LLMOptions()

        assert options.backend == LLMBackend.TRANSFORMERS
        assert options.model == "HuggingFaceTB/SmolLM2-1.7B-Instruct"
        assert options.device == "auto"
        assert options.base_url == "http://localhost:11434/v1"
        assert options.api_key is None
        assert options.timeout == 30.0
        assert options.temperature == 0.1
        assert options.min_confidence_threshold == 0.7

    def test_api_backend_options(self) -> None:
        options = LLMOptions(
            backend="api",
            base_url="http://custom:8080/v1",
            model="llama2",
            api_key="sk-test",
            temperature=0.5,
        )

        assert options.backend == LLMBackend.API
        assert options.base_url == "http://custom:8080/v1"
        assert options.model == "llama2"
        assert options.api_key == "sk-test"
        assert options.temperature == 0.5

    def test_transformers_backend_options(self) -> None:
        options = LLMOptions(
            backend="transformers",
            model="HuggingFaceTB/SmolLM2-360M-Instruct",
            device="cuda",
            torch_dtype="float16",
        )

        assert options.backend == LLMBackend.TRANSFORMERS
        assert options.model == "HuggingFaceTB/SmolLM2-360M-Instruct"
        assert options.device == "cuda"
        assert options.torch_dtype == "float16"

    def test_backend_string_conversion(self) -> None:
        options = LLMOptions(backend="api")
        assert options.backend == LLMBackend.API

        options = LLMOptions(backend="transformers")
        assert options.backend == LLMBackend.TRANSFORMERS


class TestEnhancementTracking:
    """Tests for enhancement tracking and reporting."""

    def test_tracks_multiple_enhancements(self) -> None:
        nodes = [
            _make_classified_node("p1", "Zone-Temp", "brick:Sensor", 0.55),
            _make_classified_node("p2", "Flow-Rate", "brick:Sensor", 0.60),
            _make_classified_node(
                "p3", "Pressure", "brick:Sensor", 0.95
            ),  # High confidence
        ]
        graph = make_graph(nodes=nodes, edges=[])
        options = LLMOptions(backend="api", min_confidence_threshold=0.7)

        mock_response = _make_llm_response(
            [
                {
                    "node_id": "p1",
                    "suggested_class": "brick:Temperature_Sensor",
                    "confidence": 0.92,
                    "reasoning": "Temperature indicator",
                },
                {
                    "node_id": "p2",
                    "suggested_class": "brick:Flow_Sensor",
                    "confidence": 0.88,
                    "reasoning": "Flow indicator",
                },
            ]
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_client.post.return_value = mock_response_obj
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = asyncio.run(enhance_graph(graph, options=options))

        # Only p1 and p2 should be evaluated (p3 has high confidence)
        assert result.metadata["nodes_evaluated"] == 2
        assert result.metadata["nodes_enhanced"] == 2
        assert len(result.enhancements) == 2

        # Verify original node (p3) unchanged
        p3_node = next(n for n in result.graph.nodes if n.id == "p3")
        assert p3_node.attrs["class"] == "brick:Sensor"
        assert "llm_enhanced" not in p3_node.attrs

    def test_timings_include_llm_metrics(self) -> None:
        node = _make_classified_node("p1", "Zone-Temp", "brick:Sensor", 0.55)
        graph = make_graph(nodes=[node], edges=[])
        options = LLMOptions(backend="api", min_confidence_threshold=0.7)

        mock_response = _make_llm_response([])

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_client.post.return_value = mock_response_obj
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = asyncio.run(enhance_graph(graph, options=options))

        assert result.timings.llm_call_count == 1
        assert result.timings.llm_total_seconds >= 0
        assert result.timings.duration_seconds >= 0
