"""LLM-based classification enhancement module.

This module provides optional LLM enhancement for the rule-based classifier.
It uses a local LLM to refine classifications for low-confidence nodes.

Two backends are available:
- **transformers** (default): Direct HuggingFace inference, self-contained
- **api**: OpenAI-compatible API (Ollama, vLLM, OpenAI, etc.)

Example usage:
    >>> from obs.llm import enhance_graph_sync, LLMOptions

    # Using transformers backend (default, self-contained)
    >>> options = LLMOptions(backend="transformers", model="HuggingFaceTB/SmolLM2-1.7B-Instruct")
    >>> result = enhance_graph_sync(classified_graph, options=options)

    # Using API backend (requires running Ollama or similar)
    >>> options = LLMOptions(backend="api", base_url="http://localhost:11434/v1", model="smollm2")
    >>> result = enhance_graph_sync(classified_graph, options=options)
"""

from .enhance import enhance_graph, enhance_graph_sync
from .types import Enhancement, LLMBackend, LLMOptions, LLMResult, LLMTimings

__all__ = [
    # Core functions
    "enhance_graph",
    "enhance_graph_sync",
    # Types
    "LLMBackend",
    "LLMOptions",
    "LLMResult",
    "LLMTimings",
    "Enhancement",
]
