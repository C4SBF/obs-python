"""LLM enhancement module data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from obs.graph import Graph


class LLMBackend(StrEnum):
    """Available LLM backends."""

    API = "api"  # OpenAI-compatible API (Ollama, vLLM, OpenAI, etc.)
    TRANSFORMERS = "transformers"  # Direct HuggingFace transformers


@dataclass(slots=True)
class LLMOptions:
    """Configuration for LLM-based classification enhancement.

    Attributes:
        backend: Which backend to use - "api" for OpenAI-compatible servers,
                 "transformers" for direct HuggingFace inference.
        model: Model name. For API backend, this is the model name sent to the server.
               For transformers backend, this is the HuggingFace model ID
               (e.g., "HuggingFaceTB/SmolLM2-1.7B-Instruct").
        base_url: API endpoint URL (only used with API backend).
        api_key: API key for authentication (only used with API backend).
        device: Device for transformers backend ("auto", "cuda", "cpu", "mps").
        torch_dtype: Dtype for transformers backend ("auto", "float16", "bfloat16", "float32").
        timeout: Request timeout in seconds (API backend only).
        temperature: Sampling temperature (lower = more deterministic).
        max_tokens: Maximum tokens to generate.
        batch_size: Number of nodes to process per LLM call.
        min_confidence_threshold: Only enhance nodes below this confidence.
        force: If True, apply enhancement even if LLM confidence <= original.
        metadata: Additional metadata to include in results.
    """

    backend: LLMBackend | str = LLMBackend.TRANSFORMERS
    model: str = "HuggingFaceTB/SmolLM2-1.7B-Instruct"
    # API backend options
    base_url: str = "http://localhost:11434/v1"
    api_key: str | None = None
    # Transformers backend options
    device: str = "auto"
    torch_dtype: str = "auto"
    # Common options
    timeout: float = 30.0
    temperature: float = 0.1
    max_tokens: int = 2048
    batch_size: int = 10
    min_confidence_threshold: float = 0.7
    force: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize backend to enum."""
        if isinstance(self.backend, str):
            self.backend = LLMBackend(self.backend)


@dataclass(slots=True)
class LLMTimings:
    """Timing information for LLM enhancement."""

    started_at_utc: str
    finished_at_utc: str
    duration_seconds: float
    llm_call_count: int = 0
    llm_total_seconds: float = 0.0


@dataclass(slots=True)
class Enhancement:
    """Record of a single classification enhancement."""

    node_id: str
    original_class: str | None
    original_confidence: float
    suggested_class: str
    llm_confidence: float
    reasoning: str
    applied: bool


@dataclass(slots=True)
class LLMResult:
    """Result of LLM-based graph enhancement."""

    graph: Graph  # Enhanced graph
    original_graph: Graph  # Input for comparison
    timings: LLMTimings
    success: bool
    errors: list[str] = field(default_factory=list)
    enhancements: list[Enhancement] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
