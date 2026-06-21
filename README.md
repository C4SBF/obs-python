# Open Building Stack (Python)

A Python library for BACnet device discovery and classification. Scans building automation networks, discovers devices and objects, and produces structured graph representations.

## Features

- **Network scanning** — Discover BACnet devices on local or remote networks
- **Object discovery** — Enumerate all objects on discovered devices
- **Graph representation** — Convert discovery results to a normalized graph structure
- **Classification** — Classify discovered devices and objects using ontology-based topology rules
- **LLM enhancement** — Optionally refine classifications using local or API-based LLMs

## Installation

```bash
pip install openbuildingstack
```

With optional network interface detection:

```bash
pip install openbuildingstack[network]
```

With optional LLM-based classification enhancement:

```bash
pip install openbuildingstack[ai]
```

## Quick Start

```python
import obs

# Scan the network for BACnet devices
result = obs.scan_network_sync()

# Convert to a graph structure
graph = obs.network_scan_result_to_graph(result)

# Classify the graph against a Brick ontology
topology = obs.TopologyInput(url="https://brickschema.org/schema/Brick.ttl")
classified = obs.classify_graph_sync(graph, topology)

# Serialize to JSON or YAML
obs.dump_json(classified.graph, "classified.json")
obs.dump_yaml(classified.graph, "classified.yaml")
```

### LLM Enhancement

After classification, low-confidence nodes can be refined with an LLM:

```python
from obs import enhance_graph_sync, LLMOptions

# Using local transformers (default, self-contained)
options = LLMOptions(backend="transformers", model="HuggingFaceTB/SmolLM2-1.7B-Instruct")
enhanced = enhance_graph_sync(classified.graph, options=options)

# Or using an OpenAI-compatible API (Ollama, vLLM, etc.)
options = LLMOptions(backend="api", base_url="http://localhost:11434/v1", model="smollm2")
enhanced = enhance_graph_sync(classified.graph, options=options)
```

### Async API

All scan, classify, and enhance functions have async variants:

```python
import asyncio
import obs

async def main():
    result = await obs.scan_network()
    graph = obs.network_scan_result_to_graph(result)
    classified = await obs.classify_graph(graph, obs.TopologyInput(url="..."))
    enhanced = await obs.enhance_graph(classified.graph)

asyncio.run(main())
```

## Development

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install all dependencies (including AI extras for full test coverage)
uv sync --extra network --extra ai

# Set up pre-commit hooks (includes commit message validation)
pre-commit install --hook-type pre-commit --hook-type commit-msg

# Run tests
uv run pytest

# Run linters
pre-commit run --all-files
```

### Commit Messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automatic versioning and release notes. Commit messages are validated by pre-commit hooks.

**Format:** `<type>: <description>`

| Type       | Description             | Version Bump  |
|------------|-------------------------|---------------|
| `feat`     | New feature             | Minor (0.X.0) |
| `fix`      | Bug fix                 | Patch (0.0.X) |
| `perf`     | Performance improvement | Patch (0.0.X) |
| `docs`     | Documentation only      | No release    |
| `style`    | Code style (formatting) | No release    |
| `refactor` | Code refactoring        | No release    |
| `test`     | Adding/updating tests   | No release    |
| `ci`       | CI/CD changes           | No release    |
| `chore`    | Maintenance tasks       | No release    |
| `build`    | Build system changes    | No release    |

**Examples:**
```bash
git commit -m "feat: add BACnet point reading"
git commit -m "fix: resolve network timeout on slow devices"
git commit -m "docs: update installation instructions"
```

**Breaking changes:** Add `!` after the type or include `BREAKING CHANGE:` in the body for major version bumps (X.0.0):
```bash
git commit -m "feat!: redesign discovery API"
```

## License

Source code is licensed under the [MIT License](License.md). Specifications are subject to the [Community Specification License 1.0](https://github.com/CommunitySpecification/1.0).
