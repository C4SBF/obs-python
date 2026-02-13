"""LLM-based graph classification enhancement."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import replace
from datetime import datetime
from typing import Any

from obs.graph import Graph, Node

from .types import Enhancement, LLMBackend, LLMOptions, LLMResult, LLMTimings

logger = logging.getLogger(__name__)

__all__ = [
    "enhance_graph",
    "enhance_graph_sync",
]


# Module-level cache for transformers model/tokenizer
_transformers_cache: dict[str, Any] = {}


def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now().astimezone()


def _build_timings(
    started: datetime,
    finished: datetime,
    llm_call_count: int = 0,
    llm_total_seconds: float = 0.0,
) -> LLMTimings:
    """Build timing information."""
    return LLMTimings(
        started_at_utc=started.isoformat(),
        finished_at_utc=finished.isoformat(),
        duration_seconds=(finished - started).total_seconds(),
        llm_call_count=llm_call_count,
        llm_total_seconds=llm_total_seconds,
    )


def _extract_node_context(
    node: Node, edges: list[tuple[str, str, str]]
) -> dict[str, Any]:
    """Extract relevant context from a node for LLM processing."""
    context: dict[str, Any] = {
        "id": node.id,
        "type": node.type,
        "name": node.attrs.get("name", ""),
        "description": node.attrs.get("description", ""),
    }

    # Include current classification if present
    if "class" in node.attrs:
        context["current_class"] = node.attrs["class"]
    if "class_confidence" in node.attrs:
        context["current_confidence"] = node.attrs["class_confidence"]

    # Include top candidates if available
    candidates = node.attrs.get("class_candidates", [])
    if candidates:
        context["candidates"] = [
            {"class": c.get("class", ""), "confidence": c.get("confidence", 0)}
            for c in candidates[:5]
        ]

    # Include relevant edges for relationship context
    related_edges = [
        {"relation": rel, "target": target}
        for source, target, rel in edges
        if source == node.id
    ]
    if related_edges:
        context["relationships"] = related_edges[:5]

    return context


def _build_prompt(nodes_context: list[dict[str, Any]]) -> str:
    """Build the LLM prompt for classification enhancement."""
    nodes_json = json.dumps(nodes_context, indent=2)

    return f"""You are a building automation system classifier. Review the following node classifications and suggest improvements.

For each node, analyze:
1. The node's name and description
2. The current classification and confidence
3. Alternative candidates
4. Relationship context

Output a JSON object with your suggestions. Only include nodes where you have a better classification with higher confidence than the current one.

Format:
{{
  "suggestions": [
    {{
      "node_id": "<id>",
      "suggested_class": "<ontology_class>",
      "confidence": <0.0-1.0>,
      "reasoning": "<brief explanation>"
    }}
  ]
}}

If no improvements are needed, return: {{"suggestions": []}}

Nodes to review:
{nodes_json}

Respond with valid JSON only:"""


def _parse_llm_response(response_text: str) -> list[dict[str, Any]]:
    """Parse LLM response, with fallback regex extraction if JSON parsing fails."""
    # Try direct JSON parsing first
    try:
        data = json.loads(response_text)
        if isinstance(data, dict) and "suggestions" in data:
            return data["suggestions"]
        return []
    except json.JSONDecodeError:
        pass

    # Fallback: try to extract JSON from markdown code block
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict) and "suggestions" in data:
                return data["suggestions"]
        except json.JSONDecodeError:
            pass

    # Fallback: try to find any JSON object in the response
    json_match = re.search(
        r"\{[^{}]*\"suggestions\"[^{}]*\[.*?\][^{}]*\}", response_text, re.DOTALL
    )
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            if isinstance(data, dict) and "suggestions" in data:
                return data["suggestions"]
        except json.JSONDecodeError:
            pass

    return []


# =============================================================================
# API Backend (httpx + OpenAI-compatible servers)
# =============================================================================


async def _call_llm_api(
    prompt: str,
    options: LLMOptions,
) -> tuple[str, float]:
    """Call the LLM API and return (response_text, duration_seconds)."""
    import httpx

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if options.api_key:
        headers["Authorization"] = f"Bearer {options.api_key}"

    payload = {
        "model": options.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": options.temperature,
        "max_tokens": options.max_tokens,
    }

    start_time = _utc_now()

    async with httpx.AsyncClient(timeout=options.timeout) as client:
        response = await client.post(
            f"{options.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

    duration = (_utc_now() - start_time).total_seconds()
    data = response.json()

    # Extract response content (OpenAI-compatible format)
    content = ""
    if "choices" in data and data["choices"]:
        message = data["choices"][0].get("message", {})
        content = message.get("content", "")

    return content, duration


# =============================================================================
# Transformers Backend (direct HuggingFace inference)
# =============================================================================


def _get_torch_dtype(dtype_str: str) -> Any:
    """Convert dtype string to torch dtype."""
    import torch

    dtype_map = {
        "auto": "auto",
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    return dtype_map.get(dtype_str.lower(), "auto")


def _get_device(device_str: str) -> str:
    """Determine the best device to use."""
    if device_str != "auto":
        return device_str

    import torch

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_transformers_model(options: LLMOptions) -> tuple[Any, Any]:
    """Load or retrieve cached transformers model and tokenizer."""
    cache_key = f"{options.model}:{options.device}:{options.torch_dtype}"

    if cache_key in _transformers_cache:
        return _transformers_cache[cache_key]

    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = _get_device(options.device)
    torch_dtype = _get_torch_dtype(options.torch_dtype)

    tokenizer = AutoTokenizer.from_pretrained(options.model)

    # Set pad token if not set
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs: dict[str, Any] = {
        "device_map": device if device != "cpu" else None,
    }
    if torch_dtype != "auto":
        model_kwargs["torch_dtype"] = torch_dtype

    model = AutoModelForCausalLM.from_pretrained(options.model, **model_kwargs)

    # Move to device if not using device_map
    if device == "cpu" or model_kwargs.get("device_map") is None:
        model = model.to(device)

    model.eval()

    _transformers_cache[cache_key] = (model, tokenizer)
    return model, tokenizer


def _call_llm_transformers_sync(
    prompt: str,
    options: LLMOptions,
) -> tuple[str, float]:
    """Call transformers model synchronously and return (response_text, duration_seconds)."""
    import torch

    start_time = _utc_now()

    model, tokenizer = _load_transformers_model(options)
    device = _get_device(options.device)

    # Format as chat message for instruct models
    messages = [{"role": "user", "content": prompt}]

    # Use chat template if available
    if hasattr(tokenizer, "apply_chat_template"):
        input_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    else:
        input_text = prompt

    inputs = tokenizer(input_text, return_tensors="pt", padding=True, truncation=True)
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=options.max_tokens,
            temperature=options.temperature if options.temperature > 0 else None,
            do_sample=options.temperature > 0,
            pad_token_id=tokenizer.pad_token_id,
        )

    # Decode only the generated tokens (exclude input)
    input_length = inputs["input_ids"].shape[1]
    generated_tokens = outputs[0][input_length:]
    response_text = tokenizer.decode(generated_tokens, skip_special_tokens=True)

    duration = (_utc_now() - start_time).total_seconds()
    return response_text, duration


async def _call_llm_transformers(
    prompt: str,
    options: LLMOptions,
) -> tuple[str, float]:
    """Call transformers model asynchronously (runs sync code in executor)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _call_llm_transformers_sync, prompt, options
    )


# =============================================================================
# Unified LLM Interface
# =============================================================================


async def _call_llm(
    prompt: str,
    options: LLMOptions,
) -> tuple[str, float]:
    """Call LLM using the configured backend."""
    if options.backend == LLMBackend.API:
        return await _call_llm_api(prompt, options)
    elif options.backend == LLMBackend.TRANSFORMERS:
        return await _call_llm_transformers(prompt, options)
    else:
        raise ValueError(f"Unknown backend: {options.backend}")


def _select_nodes_for_enhancement(
    graph: Graph,
    options: LLMOptions,
) -> list[Node]:
    """Select nodes that would benefit from LLM enhancement."""
    nodes_to_enhance: list[Node] = []

    for node in graph.nodes:
        # Skip nodes without classification
        if "class" not in node.attrs:
            continue

        confidence = node.attrs.get("class_confidence", 0.0)

        # Only enhance nodes below the confidence threshold
        if confidence < options.min_confidence_threshold:
            nodes_to_enhance.append(node)

    return nodes_to_enhance


def _apply_enhancements(
    graph: Graph,
    enhancements: list[Enhancement],
) -> Graph:
    """Apply approved enhancements to create a new graph."""
    # Build enhancement lookup
    enhancement_map = {e.node_id: e for e in enhancements if e.applied}

    if not enhancement_map:
        return graph

    # Create new nodes with enhancements applied
    new_nodes: list[Node] = []
    for node in graph.nodes:
        enhancement = enhancement_map.get(node.id)
        if enhancement:
            new_attrs = dict(node.attrs)
            new_attrs["class"] = enhancement.suggested_class
            new_attrs["class_confidence"] = enhancement.llm_confidence
            new_attrs["llm_enhanced"] = True
            new_attrs["llm_reasoning"] = enhancement.reasoning
            # Preserve original classification
            new_attrs["original_class"] = enhancement.original_class
            new_attrs["original_confidence"] = enhancement.original_confidence
            new_nodes.append(replace(node, attrs=new_attrs))
        else:
            new_nodes.append(node)

    return Graph(
        nodes=new_nodes,
        edges=list(graph.edges),
        meta=graph.meta,
    )


async def enhance_graph(
    graph: Graph,
    *,
    options: LLMOptions | None = None,
) -> LLMResult:
    """Enhance classified graph using LLM.

    This function takes a graph that has already been classified by the
    rule-based classifier and uses an LLM to improve classifications for
    low-confidence nodes.

    Args:
        graph: A classified graph (output from classify_graph)
        options: LLM configuration options. Defaults to transformers backend
                 with SmolLM2-1.7B-Instruct model.

    Returns:
        LLMResult containing the enhanced graph and enhancement details

    Example:
        # Using transformers backend (default, self-contained)
        options = LLMOptions(backend="transformers", model="HuggingFaceTB/SmolLM2-1.7B-Instruct")
        result = await enhance_graph(classified_graph, options=options)

        # Using API backend (requires running Ollama or similar)
        options = LLMOptions(backend="api", base_url="http://localhost:11434/v1", model="smollm2")
        result = await enhance_graph(classified_graph, options=options)
    """
    started = _utc_now()
    opts = options or LLMOptions()
    errors: list[str] = []
    enhancements: list[Enhancement] = []
    llm_call_count = 0
    llm_total_seconds = 0.0

    try:
        # Select nodes that need enhancement
        nodes_to_enhance = _select_nodes_for_enhancement(graph, opts)

        if not nodes_to_enhance:
            # No nodes need enhancement
            finished = _utc_now()
            return LLMResult(
                graph=graph,
                original_graph=graph,
                timings=_build_timings(started, finished),
                success=True,
                enhancements=[],
                metadata={
                    "nodes_evaluated": 0,
                    "nodes_enhanced": 0,
                    "backend": str(opts.backend),
                },
            )

        # Build edge lookup for context
        edges = [(e.source, e.target, e.type) for e in graph.edges]

        # Process nodes in batches
        for i in range(0, len(nodes_to_enhance), opts.batch_size):
            batch = nodes_to_enhance[i : i + opts.batch_size]

            # Extract context for each node
            nodes_context = [_extract_node_context(node, edges) for node in batch]

            # Build and send prompt
            prompt = _build_prompt(nodes_context)
            logger.debug("LLM prompt:\n%s", prompt)

            try:
                response_text, call_duration = await _call_llm(prompt, opts)
                llm_call_count += 1
                llm_total_seconds += call_duration

                # Parse response
                suggestions = _parse_llm_response(response_text)

                # Create enhancement records
                for suggestion in suggestions:
                    node_id = suggestion.get("node_id", "")
                    suggested_class = suggestion.get("suggested_class", "")
                    llm_confidence = float(suggestion.get("confidence", 0))
                    reasoning = suggestion.get("reasoning", "")

                    # Find the original node
                    original_node = next(
                        (n for n in batch if n.id == node_id),
                        None,
                    )
                    if not original_node:
                        continue

                    original_class = original_node.attrs.get("class")
                    original_confidence = original_node.attrs.get(
                        "class_confidence", 0.0
                    )

                    # Apply if LLM confidence is higher, or if force mode is enabled
                    should_apply = suggested_class and (
                        opts.force or llm_confidence > original_confidence
                    )

                    enhancements.append(
                        Enhancement(
                            node_id=node_id,
                            original_class=original_class,
                            original_confidence=original_confidence,
                            suggested_class=suggested_class,
                            llm_confidence=llm_confidence,
                            reasoning=reasoning,
                            applied=should_apply,
                        )
                    )

            except Exception as e:
                errors.append(f"LLM call failed for batch {i // opts.batch_size}: {e}")
                # Continue with remaining batches

        # Apply enhancements to create new graph
        enhanced_graph = _apply_enhancements(graph, enhancements)

        finished = _utc_now()
        applied_count = sum(1 for e in enhancements if e.applied)

        return LLMResult(
            graph=enhanced_graph,
            original_graph=graph,
            timings=_build_timings(
                started, finished, llm_call_count, llm_total_seconds
            ),
            success=len(errors) == 0,
            errors=errors,
            enhancements=enhancements,
            metadata={
                "nodes_evaluated": len(nodes_to_enhance),
                "nodes_enhanced": applied_count,
                "model": opts.model,
                "backend": str(opts.backend),
            },
        )

    except Exception as e:
        # Graceful fallback: return original graph on any error
        finished = _utc_now()
        return LLMResult(
            graph=graph,
            original_graph=graph,
            timings=_build_timings(
                started, finished, llm_call_count, llm_total_seconds
            ),
            success=False,
            errors=[str(e)],
            enhancements=enhancements,
            metadata={"backend": str(opts.backend)},
        )


def enhance_graph_sync(
    graph: Graph,
    *,
    options: LLMOptions | None = None,
) -> LLMResult:
    """Synchronous wrapper for enhance_graph.

    Args:
        graph: A classified graph (output from classify_graph)
        options: LLM configuration options

    Returns:
        LLMResult containing the enhanced graph and enhancement details
    """
    return asyncio.run(enhance_graph(graph, options=options))
