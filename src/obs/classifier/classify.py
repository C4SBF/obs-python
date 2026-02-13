"""Graph classification entry points."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Any

import yaml

from obs.graph import Edge, Graph, GraphMeta, Node

from .types import (
    ClassifyInput,
    ClassifyOptions,
    ClassifyResult,
    TopologyInput,
    build_timings,
    utc_now,
)

__all__ = [
    "classify_graph",
    "classify_graph_sync",
]


_TOKEN_RE = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True)
class _OntologyClass:
    class_id: str
    label: str
    parents: set[str]
    children: set[str]


@dataclass(slots=True)
class _OntologyRelation:
    """Represents an ontology relation/property with domain and range."""

    relation_id: str
    label: str
    domain: set[str]  # Classes that can be the source
    range: set[str]  # Classes that can be the target
    inverse_of: str | None = None


@dataclass(slots=True)
class _OntologyIndex:
    classes: dict[str, _OntologyClass]
    relations: set[str]
    namespace_prefix: str = ""
    # Token -> list of (class_id, weight) for fast keyword lookup
    token_index: dict[str, list[tuple[str, float]]] | None = None
    # Equipment type -> set of class_ids that have affinity with that equipment
    equipment_affinity: dict[str, set[str]] | None = None
    # Relation definitions with domain/range
    relation_defs: dict[str, _OntologyRelation] | None = None


@dataclass(slots=True)
class _Candidate:
    class_id: str
    score: float
    evidence: list[str]


def _normalize_text(value: str) -> str:
    normalized = _TOKEN_RE.sub(" ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _split_tokens(value: str) -> list[str]:
    txt = _normalize_text(value)
    return [token for token in txt.split(" ") if token]


def _extract_namespace_prefix(uri: str) -> str:
    """Extract namespace prefix from a URI (e.g., 'https://brickschema.org/schema/Brick#' -> 'brick')."""
    if "#" in uri:
        base = uri.rsplit("#", 1)[0]
    elif "/" in uri:
        base = uri.rsplit("/", 1)[0]
    else:
        return ""
    # Extract last meaningful segment as prefix
    parts = [p for p in base.split("/") if p and p not in ("http:", "https:", "schema")]
    if parts:
        # Use last part, lowercase, as prefix (e.g., "Brick" -> "brick")
        return parts[-1].lower().replace(".", "_")
    return ""


def _compact_id(raw: str, default_prefix: str = "") -> str:
    """Compact a URI to prefix:localname format."""
    # Already compacted
    if ":" in raw and not raw.startswith(("http://", "https://")):
        return raw
    # Extract local name and build compact form
    if "#" in raw:
        local = raw.split("#")[-1]
        prefix = _extract_namespace_prefix(raw) or default_prefix
    elif "/" in raw:
        local = raw.rsplit("/", 1)[-1]
        prefix = _extract_namespace_prefix(raw) or default_prefix
    else:
        return raw
    if prefix:
        return f"{prefix}:{local}"
    return local


def _extract_ref_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("@id", "id"):
            if key in value and isinstance(value[key], str):
                return value[key]
    return None


def _extract_labels(node: dict[str, Any]) -> str | None:
    # Try multiple label predicates (compact and full URI forms)
    label_keys = [
        "rdfs:label",
        "label",
        "http://www.w3.org/2000/01/rdf-schema#label",
    ]
    label = None
    for key in label_keys:
        if key in node:
            label = node[key]
            break
    if label is None:
        return None
    if isinstance(label, str):
        return label
    if isinstance(label, dict):
        raw = label.get("@value")
        return raw if isinstance(raw, str) else None
    if isinstance(label, list):
        for item in label:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                raw = item.get("@value")
                if isinstance(raw, str):
                    return raw
    return None


def _type_values(node: dict[str, Any]) -> list[str]:
    raw_type = node.get("@type") or node.get("type")
    if isinstance(raw_type, str):
        return [raw_type]
    if isinstance(raw_type, list):
        return [entry for entry in raw_type if isinstance(entry, str)]
    return []


def _is_class_node(node: dict[str, Any]) -> bool:
    types = _type_values(node)
    # Check for both compact and full URI forms
    return any("Class" in t or "owl#Class" in t for t in types)


def _is_relation_node(node: dict[str, Any]) -> bool:
    types = _type_values(node)
    # Check for both compact and full URI forms
    return any("ObjectProperty" in t or "owl#ObjectProperty" in t for t in types)


def _extract_ref_ids(value: Any, prefix: str) -> set[str]:
    """Extract and compact multiple reference IDs from a value (single or list)."""
    result: set[str] = set()
    if isinstance(value, str):
        result.add(_compact_id(value, prefix))
    elif isinstance(value, dict):
        ref = _extract_ref_id(value)
        if ref:
            result.add(_compact_id(ref, prefix))
    elif isinstance(value, list):
        for item in value:
            ref = (
                _extract_ref_id(item)
                if isinstance(item, dict)
                else (item if isinstance(item, str) else None)
            )
            if ref:
                result.add(_compact_id(ref, prefix))
    return result


def _build_ontology_index(payload: Any) -> _OntologyIndex:
    classes: dict[str, _OntologyClass] = {}
    relations: set[str] = set()
    relation_defs: dict[str, _OntologyRelation] = {}
    detected_prefix: str = ""

    graph_nodes: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("@graph"), list):
        graph_nodes = [node for node in payload["@graph"] if isinstance(node, dict)]
    elif isinstance(payload, list):
        graph_nodes = [node for node in payload if isinstance(node, dict)]
    elif isinstance(payload, dict):
        graph_nodes = [payload]

    # First pass: detect namespace prefix from URIs
    for node in graph_nodes:
        raw_id = _extract_ref_id(node.get("@id") or node.get("id"))
        if raw_id and ("http://" in raw_id or "https://" in raw_id):
            detected_prefix = _extract_namespace_prefix(raw_id)
            if detected_prefix:
                break

    for node in graph_nodes:
        raw_id = _extract_ref_id(node.get("@id") or node.get("id"))
        if not raw_id:
            continue
        compact_id = _compact_id(raw_id, detected_prefix)

        if _is_relation_node(node):
            relations.add(compact_id)
            # Extract domain and range for the relation
            domain = _extract_ref_ids(
                node.get("rdfs:domain")
                or node.get("domain")
                or node.get("schema:domainIncludes"),
                detected_prefix,
            )
            range_ = _extract_ref_ids(
                node.get("rdfs:range")
                or node.get("range")
                or node.get("schema:rangeIncludes"),
                detected_prefix,
            )
            inverse_raw = node.get("owl:inverseOf") or node.get("inverseOf")
            inverse_ref = _extract_ref_id(inverse_raw) if inverse_raw else None
            inverse_of = (
                _compact_id(inverse_ref, detected_prefix) if inverse_ref else None
            )
            label = _extract_labels(node) or compact_id.split(":", 1)[-1]
            relation_defs[compact_id] = _OntologyRelation(
                relation_id=compact_id,
                label=label,
                domain=domain,
                range=range_,
                inverse_of=inverse_of,
            )
            continue
        if not _is_class_node(node):
            continue

        parent_raw = node.get("rdfs:subClassOf") or node.get("subClassOf")
        parents: set[str] = set()
        if isinstance(parent_raw, list):
            for entry in parent_raw:
                parent_id = _extract_ref_id(entry)
                if parent_id:
                    parents.add(_compact_id(parent_id, detected_prefix))
        else:
            parent_id = _extract_ref_id(parent_raw)
            if parent_id:
                parents.add(_compact_id(parent_id, detected_prefix))

        label = _extract_labels(node) or compact_id.split(":", 1)[-1]
        classes[compact_id] = _OntologyClass(
            class_id=compact_id,
            label=label,
            parents=parents,
            children=set(),
        )

    for class_id, klass in classes.items():
        for parent in list(klass.parents):
            if parent in classes:
                classes[parent].children.add(class_id)

    # Build token index: map tokens from class labels to classes
    token_index: dict[str, list[tuple[str, float]]] = {}
    for class_id, klass in classes.items():
        # Extract tokens from label (e.g., "Reheat_Valve" -> ["reheat", "valve"])
        label_tokens = _split_tokens(klass.label)
        # Also extract from class local name if different
        local_name = class_id.split(":", 1)[-1] if ":" in class_id else class_id
        name_tokens = _split_tokens(local_name)
        all_tokens = set(label_tokens + name_tokens)

        # All tokens get high weight - we'll compute coverage-based scoring at match time
        for token in all_tokens:
            if len(token) < 2:
                continue
            if token not in token_index:
                token_index[token] = []
            token_index[token].append((class_id, 1.0))

    # Build equipment affinity index: map equipment types to point classes
    # This helps us prefer point types that belong to the detected equipment
    equipment_keywords: dict[str, list[str]] = {
        "ahu": [
            "ahu",
            "air_handling",
            "airhandling",
            "airhandler",
            "supply_air",
            "return_air",
            "mixed_air",
            "outside_air",
        ],
        "vav": ["vav", "variable_air_volume", "reheat"],
        "fcu": ["fcu", "fan_coil", "fancoil"],
        "chiller": [
            "chiller",
            "chilled_water",
            "chilledwater",
            "leaving_chilled",
            "entering_chilled",
        ],
        "boiler": ["boiler", "hot_water", "hotwater", "leaving_hot", "entering_hot"],
        "pump": ["pump"],
        "zone": [
            "zone_air",
            "room_air",
            "space_air",
            "zone_temperature",
            "room_temperature",
        ],
        "meter": [
            "_meter",
            "electrical_meter",
            "power_meter",
            "energy_meter",
            "gas_meter",
            "water_meter",
        ],
    }

    equipment_affinity: dict[str, set[str]] = {k: set() for k in equipment_keywords}
    for class_id, klass in classes.items():
        class_name_lower = class_id.lower()
        label_lower = klass.label.lower().replace(" ", "_")
        combined = f"{class_name_lower} {label_lower}"

        # Check for equipment affinity based on class name/label
        for equip_type, keywords in equipment_keywords.items():
            if any(kw in combined for kw in keywords):
                # For meter, only include actual meter classes
                if equip_type == "meter" and "meter" not in combined:
                    continue
                equipment_affinity[equip_type].add(class_id)

    return _OntologyIndex(
        classes=classes,
        relations=relations,
        namespace_prefix=detected_prefix,
        token_index=token_index,
        equipment_affinity=equipment_affinity,
        relation_defs=relation_defs,
    )


def _get_class_ancestors(class_id: str, index: _OntologyIndex) -> set[str]:
    """Get all ancestor classes (including self) for a class."""
    ancestors = {class_id}
    if class_id not in index.classes:
        return ancestors
    frontier = list(index.classes[class_id].parents)
    while frontier:
        parent = frontier.pop()
        if parent in ancestors:
            continue
        ancestors.add(parent)
        if parent in index.classes:
            frontier.extend(index.classes[parent].parents)
    return ancestors


def _infer_class_category(class_id: str | None) -> str | None:
    """Infer the category of a class from its name (Equipment, Point, Location, etc.)."""
    if not class_id:
        return None

    local = class_id.split(":")[-1] if ":" in class_id else class_id
    local_lower = local.lower()

    # Check for point indicators
    point_keywords = {
        "sensor",
        "setpoint",
        "command",
        "status",
        "alarm",
        "point",
        "meter",
    }
    if any(kw in local_lower for kw in point_keywords):
        return "point"

    # Check for location indicators
    location_keywords = {
        "building",
        "floor",
        "room",
        "space",
        "zone",
        "site",
        "location",
    }
    if any(kw in local_lower for kw in location_keywords):
        return "location"

    # Default to equipment for everything else
    return "equipment"


def _find_relation_for_edge(
    source_class: str | None,
    target_class: str | None,
    index: _OntologyIndex | None,
    default: str = "hasPoint",
) -> str:
    """Find the appropriate relation for an edge based on source/target classes.

    First checks the ontology for relations with matching domain/range.
    Falls back to sensible defaults based on inferred class categories.
    """
    # First, try ontology-defined relations
    if index and index.relation_defs and source_class and target_class:
        source_ancestors = _get_class_ancestors(source_class, index)
        target_ancestors = _get_class_ancestors(target_class, index)

        for rel_id, rel_def in index.relation_defs.items():
            has_domain = bool(rel_def.domain)
            has_range = bool(rel_def.range)

            if not (has_domain and has_range):
                continue

            domain_match = bool(source_ancestors & rel_def.domain)
            range_match = bool(target_ancestors & rel_def.range)

            if domain_match and range_match:
                local_name = rel_id.split(":")[-1] if ":" in rel_id else rel_id
                return local_name

    # Fall back to defaults based on class categories
    source_cat = _infer_class_category(source_class)
    target_cat = _infer_class_category(target_class)

    # Equipment -> Point = hasPoint
    if source_cat == "equipment" and target_cat == "point":
        return "hasPoint"

    # Equipment -> Equipment = hasPart (for composition)
    if source_cat == "equipment" and target_cat == "equipment":
        return "hasPart"

    # Location -> Location = contains
    if source_cat == "location" and target_cat == "location":
        return "contains"

    # Location -> Equipment = contains
    if source_cat == "location" and target_cat == "equipment":
        return "contains"

    return default


def _resolve_topology(topology: TopologyInput) -> tuple[str, Any]:
    if topology.content is not None:
        ref = topology.id or topology.url or "inline"
        return ref, topology.content

    if topology.url:
        with urllib.request.urlopen(topology.url, timeout=20) as response:
            payload = response.read().decode("utf-8")
        fmt = topology.format or (
            "json" if topology.url.endswith((".json", ".jsonld")) else "yaml"
        )
        if fmt == "json":
            return topology.url, json.loads(payload)
        return topology.url, yaml.safe_load(payload)

    if topology.id:
        # ID-only topology references are allowed, but no ontology payload is available.
        return topology.id, None

    raise ValueError("Topology must include one of: id, url, content")


def _node_attr(node: Node, key: str) -> str:
    value = node.attrs.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _split_compound_words(tokens: list[str]) -> list[str]:
    """Split compound words like 'airflow' into constituent parts ['air', 'flow', 'airflow']."""
    # Common HVAC compound words and their parts
    compounds = {
        "airflow": ["air", "flow"],
        "setpoint": ["set", "point"],
        "waterflow": ["water", "flow"],
        "damperposition": ["damper", "position"],
        "valveposition": ["valve", "position"],
        "fanspeed": ["fan", "speed"],
        "pumpspeed": ["pump", "speed"],
        "supplyair": ["supply", "air"],
        "returnair": ["return", "air"],
        "outsideair": ["outside", "air"],
        "exhaustair": ["exhaust", "air"],
        "hotwater": ["hot", "water"],
        "chilledwater": ["chilled", "water"],
        "mixedair": ["mixed", "air"],
    }
    result = []
    for token in tokens:
        result.append(token)
        if token in compounds:
            result.extend(compounds[token])
    return result


def _extract_node_tokens(node: Node) -> tuple[list[str], list[str]]:
    """Extract tokens from node name and description."""
    name = (_node_attr(node, "name") or node.id).lower()
    description = _node_attr(node, "description").lower()
    name_tokens = _split_compound_words(_split_tokens(name))
    desc_tokens = (
        _split_compound_words(_split_tokens(description)) if description else []
    )
    return name_tokens, desc_tokens


def _normalize_unit(unit: str) -> str:
    """Normalize unit strings to standard abbreviations."""
    unit = unit.lower().replace("-", "").replace("_", "").replace(" ", "")
    unit_map = {
        "cubicfeetperminute": "cfm",
        "cubicfeetminute": "cfm",
        "cubicmetersecond": "m3/s",
        "cubicmeterhour": "m3/h",
        "litersecond": "l/s",
        "literminute": "l/min",
        "gallonsperminute": "gpm",
        "gallonperminute": "gpm",
        "degreesfahrenheit": "f",
        "degreefahrenheit": "f",
        "degreescelsius": "c",
        "degreecelsius": "c",
        "fahrenheit": "f",
        "celsius": "c",
        "kelvin": "k",
        "pascal": "pa",
        "kilopascal": "kpa",
        "poundspersquareinch": "psi",
        "incheswatercolumn": "inwc",
        "incheswater": "inwc",
        "percent": "%",
        "percentrelativehumidity": "%rh",
        "relativehumidity": "%rh",
    }
    return unit_map.get(unit, unit)


# =============================================================================
# Point Classification Helpers - Detect function, equipment, medium from names
# =============================================================================


def _detect_point_function(name: str) -> str:
    """Detect if point is sensor, setpoint, command, or status from its name."""
    name_lower = name.lower()

    # Command indicators (check BEFORE setpoint - "cmd" is unambiguous)
    if any(
        x in name_lower
        for x in ["-cmd", "_cmd", "command", "enable", "start", "stop", "reset"]
    ):
        return "command"

    # Setpoint indicators - be careful not to match "speed" which contains "sp"
    # Check for -sp or _sp followed by end or another separator
    setpoint_patterns = ["setpoint", "setpt", "stpt", "-sp-", "_sp_", "-spt", "_spt"]
    if any(p in name_lower for p in setpoint_patterns):
        return "setpoint"
    # Also check for -sp or _sp at end of name
    if name_lower.endswith("-sp") or name_lower.endswith("_sp"):
        return "setpoint"

    # Status indicators
    if any(
        x in name_lower for x in ["status", "state", "alarm", "fault", "-sts", "_sts"]
    ):
        return "status"

    # Position can be sensor or command - check for cmd suffix
    if "position" in name_lower or "-pos" in name_lower or "_pos" in name_lower:
        if any(x in name_lower for x in ["cmd", "command", "setpoint", "sp"]):
            return "command"
        return "sensor"  # Position without cmd suffix is usually a sensor

    # Default: it's a sensor/measurement
    return "sensor"


def _detect_equipment_type(name: str) -> str | None:
    """Detect equipment type from name."""
    name_lower = name.lower()

    # Check for specific equipment types (order matters - more specific first)
    if (
        "ahu" in name_lower
        or "air-handling" in name_lower
        or "airhandler" in name_lower
    ):
        return "ahu"
    if "vav" in name_lower:
        return "vav"
    if "fcu" in name_lower or "fan-coil" in name_lower or "fancoil" in name_lower:
        return "fcu"
    if "chiller" in name_lower or "-chw-" in name_lower:
        return "chiller"
    if "boiler" in name_lower or "-hw-" in name_lower or "-hhw-" in name_lower:
        return "boiler"
    if "pump" in name_lower:
        return "pump"
    if "meter" in name_lower:
        return "meter"
    # Zone detection - look for zone/room keywords
    if "zone" in name_lower or "room" in name_lower or "space" in name_lower:
        return "zone"
    return None


def _detect_medium(name: str) -> str | None:
    """Detect what medium/substance the point relates to."""
    name_lower = name.lower()

    # Order matters - check more specific patterns first
    if any(x in name_lower for x in ["chw", "chilled-water", "chilledwater", "cw-"]):
        return "chilled_water"
    if any(x in name_lower for x in ["-hw-", "hot-water", "hotwater", "hhw"]):
        return "hot_water"
    if any(
        x in name_lower
        for x in ["supply-air", "supplyair", "-sa-", "sa-temp", "sa-flow"]
    ):
        return "supply_air"
    if any(
        x in name_lower
        for x in ["return-air", "returnair", "-ra-", "ra-temp", "ra-flow"]
    ):
        return "return_air"
    if any(x in name_lower for x in ["mixed-air", "mixedair", "-ma-", "ma-temp"]):
        return "mixed_air"
    if any(x in name_lower for x in ["outside-air", "outsideair", "-oa-", "oa-temp"]):
        return "outside_air"
    if any(x in name_lower for x in ["exhaust", "-ea-"]):
        return "exhaust_air"
    if any(x in name_lower for x in ["zone", "room", "space"]):
        return "zone"
    return None


# Pattern to extract equipment prefixes like P1, P2, Tank1, Pump_1
_SUB_EQUIPMENT_PREFIX_RE = re.compile(r"^([A-Za-z]+[-_]?\d+)[-_]")

# BACnet object type prefixes to exclude from sub-equipment detection
# These are object identifiers, not equipment names
_BACNET_OBJECT_PREFIXES = frozenset(
    {
        "ai",
        "ao",
        "av",  # Analog Input/Output/Value
        "bi",
        "bo",
        "bv",  # Binary Input/Output/Value
        "mi",
        "mo",
        "mv",  # Multi-state Input/Output/Value
        "msi",
        "mso",
        "msv",  # Multi-state Input/Output/Value (alternate)
        "lp",
        "loop",  # Loop
        "dev",
        "device",  # Device
        "file",
        "grp",
        "group",  # File, Group
        "prg",
        "program",  # Program
        "sch",
        "schedule",  # Schedule
        "cal",
        "calendar",  # Calendar
        "cmd",
        "command",  # Command
        "nc",
        "notif",  # Notification Class
        "trend",
        "tl",  # Trend Log
        "obj",  # Generic object
    }
)


def _infer_equipment_type_from_prefix(prefix: str) -> str | None:
    """Infer equipment type from a prefix like P1, Tank2, etc.

    Returns equipment type name (e.g., "pump", "tank") or None if not recognized.
    The actual ontology class should be resolved separately using the ontology index.
    """
    prefix_lower = prefix.lower()
    # Remove trailing numbers and separators for type detection
    base = re.sub(r"[-_]?\d+$", "", prefix_lower)

    # Skip BACnet object type prefixes
    if base in _BACNET_OBJECT_PREFIXES:
        return None

    # Map common prefixes to equipment types (ontology-agnostic)
    type_map: dict[str, str] = {
        "p": "pump",
        "pump": "pump",
        "pmp": "pump",
        "tank": "tank",
        "tk": "tank",
        "vfd": "vfd",
        "valve": "valve",
        "vlv": "valve",
        "fan": "fan",
        "sensor": "sensor",
        "meter": "meter",
        "ahu": "ahu",
        "vav": "vav",
        "fcu": "fcu",
        "chiller": "chiller",
        "chl": "chiller",
        "boiler": "boiler",
        "blr": "boiler",
        "ctu": "cooling_tower",
        "ct": "cooling_tower",
    }

    for key, equip_type in type_map.items():
        if base == key or prefix_lower.startswith(key):
            return equip_type

    # No match - don't create generic equipment for unknown prefixes
    return None


def _resolve_equipment_class(equip_type: str, index: _OntologyIndex | None) -> str:
    """Resolve an equipment type name to an ontology class.

    Searches the ontology for a class matching the equipment type.
    If no match found, constructs a class URI using the ontology namespace.
    """
    # Normalize equipment type to title case for class name (e.g., "pump" -> "Pump")
    type_title = equip_type.replace("_", " ").title().replace(" ", "_")

    if not index or not index.classes:
        # No ontology - use generic prefix
        return f"equip:{type_title}"

    # Normalize the equipment type for matching
    equip_type_lower = equip_type.lower().replace("_", "")

    # First pass: exact matches
    for class_id, klass in index.classes.items():
        class_local = class_id.split(":")[-1] if ":" in class_id else class_id
        class_lower = class_local.lower().replace("_", "")
        label_lower = klass.label.lower().replace("_", "").replace(" ", "")

        if class_lower == equip_type_lower or label_lower == equip_type_lower:
            return class_id

    # Second pass: partial matches (type contained in class name)
    for class_id, klass in index.classes.items():
        class_local = class_id.split(":")[-1] if ":" in class_id else class_id
        class_lower = class_local.lower().replace("_", "")
        if class_lower.startswith(equip_type_lower) or class_lower.endswith(
            equip_type_lower
        ):
            return class_id

    # No match found - construct class using ontology namespace
    prefix = index.namespace_prefix or "equip"
    return f"{prefix}:{type_title}"


def _detect_sub_equipment(
    point_nodes: list[Node], index: _OntologyIndex | None
) -> dict[str, dict]:
    """Detect sub-equipment from point name patterns.

    Parses point names to extract equipment prefixes (P1, P2, Tank1, etc.)
    and groups points by their parent equipment. Excludes BACnet object type
    prefixes (BV, AV, AI, etc.) which are identifiers, not equipment names.

    Returns: {
        "P1": {"type": "pump", "points": [...], "class": "<ontology:Pump>"},
        "P2": {"type": "pump", "points": [...], "class": "<ontology:Pump>"},
        "Tank1": {"type": "tank", "points": [...], "class": "<ontology:Tank>"},
    }
    """
    sub_equipment: dict[str, dict] = {}

    for point in point_nodes:
        point_name = point.attrs.get("name", "") or point.id

        # Try to extract equipment prefix
        match = _SUB_EQUIPMENT_PREFIX_RE.match(point_name)
        if not match:
            continue

        prefix = match.group(1)

        # Check if this is a known equipment type (not a BACnet object prefix)
        equip_type = _infer_equipment_type_from_prefix(prefix)
        if equip_type is None:
            # Skip unknown prefixes (likely BACnet object types like BV, AV, etc.)
            continue

        # Normalize prefix (e.g., "P-1" -> "P1", "Pump_1" -> "Pump1")
        normalized_prefix = prefix.replace("-", "").replace("_", "")

        if normalized_prefix not in sub_equipment:
            # Resolve equipment type to ontology class
            equip_class = _resolve_equipment_class(equip_type, index)
            sub_equipment[normalized_prefix] = {
                "type": equip_type,
                "points": [],
                "class": equip_class,  # May be None if not in ontology
                "original_prefix": prefix,
            }

        sub_equipment[normalized_prefix]["points"].append(point)

    return sub_equipment


def _classify_composite_system(
    sub_equipment: dict[str, dict],
    index: _OntologyIndex | None,
) -> tuple[str | None, list[str]]:
    """Classify a device as a composite system based on detected sub-equipment.

    Returns: (class_id, evidence_list) where class_id is resolved from the ontology
    or constructed using the ontology namespace.
    """
    if not sub_equipment:
        return None, []

    # Count equipment types
    type_counts: dict[str, int] = {}
    for equip_info in sub_equipment.values():
        equip_type = equip_info["type"]
        type_counts[equip_type] = type_counts.get(equip_type, 0) + 1

    evidence: list[str] = []
    for equip_type, count in sorted(type_counts.items()):
        prefixes = [
            info["original_prefix"]
            for info in sub_equipment.values()
            if info["type"] == equip_type
        ]
        evidence.append(f"detected {count} {equip_type}(s): {', '.join(prefixes)}")

    # Determine composite system type (ontology-agnostic names)
    has_pumps = type_counts.get("pump", 0) >= 1
    has_tanks = type_counts.get("tank", 0) >= 1
    has_multiple_pumps = type_counts.get("pump", 0) >= 2

    system_type: str | None = None

    # Multiple pumps + tanks = Pump Station
    if has_multiple_pumps and has_tanks:
        evidence.append("composite pattern: pump_station (multiple pumps + tanks)")
        system_type = "pump_station"

    # Multiple pumps only = Pump Group
    elif has_multiple_pumps:
        evidence.append("composite pattern: pump_group (multiple pumps)")
        system_type = "pump_group"

    # Pumps + tanks (but single pump) = Water System
    elif has_pumps and has_tanks:
        evidence.append("composite pattern: water_system (pump + tanks)")
        system_type = "water_system"

    # Multiple of any equipment type = generic system
    elif sum(type_counts.values()) >= 3:
        evidence.append(
            f"composite pattern: equipment_system ({sum(type_counts.values())} sub-equipment)"
        )
        system_type = "equipment_system"

    if system_type is None:
        return None, evidence

    # Resolve system type to ontology class (always returns a class)
    system_class = _resolve_equipment_class(system_type, index)
    return system_class, evidence


# Conflicting term pairs - if entity has one, class shouldn't have the other
_CONFLICT_PAIRS: list[tuple[set[str], set[str]]] = [
    # Temperature system conflicts
    (
        {"chiller", "chw", "chilled", "cooling"},
        {"boiler", "hot", "heating", "hw", "hhw", "htg"},
    ),
    # Air path conflicts
    ({"supply", "sa"}, {"return", "ra", "exhaust", "ea"}),
    ({"mixed", "ma"}, {"supply", "sa", "return", "ra"}),
    ({"outside", "oa", "outdoor"}, {"return", "ra", "supply", "sa"}),
    # Location conflicts
    (
        {"zone", "room", "space"},
        {"supply", "return", "mixed", "outside", "outdoor", "discharge"},
    ),
    # Equipment conflicts
    ({"ahu"}, {"vav", "fcu", "chiller", "boiler", "pump"}),
    ({"chiller"}, {"boiler", "ahu", "vav", "fcu"}),
]


def _compute_conflict_penalty(entity_tokens: set[str], class_tokens: set[str]) -> float:
    """Compute penalty for conflicting terms between entity and class."""
    penalty = 0.0
    for group_a, group_b in _CONFLICT_PAIRS:
        entity_has_a = bool(entity_tokens & group_a)
        entity_has_b = bool(entity_tokens & group_b)
        class_has_a = bool(class_tokens & group_a)
        class_has_b = bool(class_tokens & group_b)

        # Penalize if entity has A but class has B (or vice versa)
        if (entity_has_a and class_has_b) or (entity_has_b and class_has_a):
            penalty += 0.25

    return min(penalty, 0.6)  # Cap total penalty


def _filter_by_function(
    candidates: list[_Candidate],
    function: str,
    index: _OntologyIndex,
) -> list[_Candidate]:
    """Filter candidates that don't match the detected point function."""
    if not candidates:
        return candidates

    filtered = []
    for cand in candidates:
        class_lower = cand.class_id.lower()

        if function == "sensor":
            # Sensors should NOT match setpoint or command classes
            if "setpoint" in class_lower or "command" in class_lower:
                continue
            # Also reject "limit" which are setpoints
            if "limit" in class_lower and "sensor" not in class_lower:
                continue

        elif function == "setpoint":
            # Setpoints should prefer setpoint classes, reject pure sensors
            if "sensor" in class_lower and "setpoint" not in class_lower:
                continue

        elif function == "command":
            # Commands should match command/enable classes
            if "sensor" in class_lower and "command" not in class_lower:
                continue
            if "setpoint" in class_lower and "command" not in class_lower:
                continue

        elif function == "status":
            # Status points should match status classes
            if "setpoint" in class_lower or "command" in class_lower:
                if "status" not in class_lower:
                    continue

        filtered.append(cand)

    # If filtering removed everything, return original (don't lose all candidates)
    return filtered if filtered else candidates


def _rule_terms(node: Node) -> list[tuple[str, float, str]]:
    """Extract feature-based terms from node attributes (quantity, unit, type, etc.)."""
    quantity = _node_attr(node, "quantity").lower()
    unit = _normalize_unit(_node_attr(node, "unit"))
    data_type = _node_attr(node, "data_type").lower()
    point_type = _node_attr(node, "point_type").lower()
    medium = _node_attr(node, "medium").lower()

    terms: list[tuple[str, float, str]] = []

    # Node type based
    if node.type == "device":
        terms.append(("equipment", 0.4, "device node"))
    if node.type == "point":
        terms.append(("point", 0.3, "point node"))

    # Quantity/unit based rules - strong signals for sensor types
    if quantity == "temperature" or unit in {"c", "f", "k", "degf", "degc"}:
        terms.append(("temperature", 0.92, "quantity/unit"))
    if quantity == "flow" or unit in {
        "cfm",
        "m3/s",
        "m3/h",
        "l/s",
        "l/min",
        "l/h",
        "gpm",
    }:
        terms.append(("flow", 0.92, "quantity/unit"))
        terms.append(
            ("air", 0.7, "flow unit suggests air")
        )  # CFM typically means air flow
    if quantity == "pressure" or unit in {"pa", "kpa", "psi", "inwc", "inh2o"}:
        terms.append(("pressure", 0.92, "quantity/unit"))
    if quantity == "humidity" or unit in {"%rh", "rh"}:
        terms.append(("humidity", 0.92, "quantity/unit"))

    # Point type based rules
    if point_type.startswith("binary") or data_type == "bool":
        terms.append(("binary", 0.6, "binary type"))
    if point_type.startswith("analog") or medium == "analog":
        terms.append(("analog", 0.5, "analog type"))

    return terms


def _lexical_score(term: str, klass: _OntologyClass) -> float:
    term_n = _normalize_text(term)
    label_n = _normalize_text(klass.label)
    id_n = _normalize_text(klass.class_id.split(":", 1)[-1])
    ratio = max(
        SequenceMatcher(a=term_n, b=label_n).ratio(),
        SequenceMatcher(a=term_n, b=id_n).ratio(),
    )
    if term_n and (term_n in label_n or term_n in id_n):
        ratio = max(ratio, 0.75)
    return ratio


def _seed_candidates(node: Node, index: _OntologyIndex | None) -> list[_Candidate]:
    if not index or not index.classes:
        return []

    # Extract name and detect point characteristics
    name = _node_attr(node, "name") or node.id
    name_tokens, desc_tokens = _extract_node_tokens(node)
    all_tokens = set(name_tokens + desc_tokens)

    # Detect point function (sensor, setpoint, command, status)
    point_function = _detect_point_function(name)

    scored: dict[str, _Candidate] = {}

    def add_candidate(class_id: str, score: float, evidence: str) -> None:
        existing = scored.get(class_id)
        if existing is None:
            scored[class_id] = _Candidate(class_id, score, [evidence])
        else:
            # Accumulate score for multiple matching tokens, with diminishing returns
            new_score = min(1.0, existing.score + score * 0.4)
            scored[class_id] = _Candidate(
                class_id, new_score, existing.evidence + [evidence]
            )

    # 1. Direct token matching against ontology token index (highest priority)
    if index.token_index:
        # Count how many tokens from each class match (exact matches only)
        class_token_matches: dict[str, list[str]] = {}
        for token in all_tokens:
            if token in index.token_index:
                for class_id, _ in index.token_index[token]:
                    if class_id not in class_token_matches:
                        class_token_matches[class_id] = []
                    class_token_matches[class_id].append(token)

        # Score classes based on token coverage AND match count
        for class_id, matched_tokens in class_token_matches.items():
            klass = index.classes.get(class_id)
            if not klass:
                continue
            # Get all tokens from the class label
            class_label_tokens = set(_split_tokens(klass.label))
            if not class_label_tokens:
                continue

            matched_set = set(matched_tokens)
            matched_count = len(matched_set & class_label_tokens)
            class_token_count = len(class_label_tokens)
            coverage = matched_count / class_token_count

            # Base scoring: more matching tokens = better
            base_score = 0.60
            coverage_bonus = coverage * 0.10 * class_token_count
            match_bonus = matched_count * 0.08

            # Apply conflict penalty (e.g., "Chiller" in name but "Hot_Water" in class)
            conflict_penalty = _compute_conflict_penalty(all_tokens, class_label_tokens)

            # Penalize overly specific classes when we don't have enough matching tokens
            # e.g., "Zone-Temp" (2 meaningful tokens) shouldn't match a 5-token class
            specificity_penalty = 0.0
            entity_meaningful_tokens = len([t for t in all_tokens if len(t) > 3])
            if class_token_count > entity_meaningful_tokens + 2 and coverage < 0.8:
                specificity_penalty = 0.15

            score = max(
                0.1,
                min(
                    0.99,
                    base_score
                    + coverage_bonus
                    + match_bonus
                    - conflict_penalty
                    - specificity_penalty,
                ),
            )
            evidence = f"name tokens [{', '.join(sorted(matched_set))}] match class"
            add_candidate(class_id, score, evidence)

    # 2. Feature-based terms (quantity, unit, type, etc.)
    terms = _rule_terms(node)
    for term, weight, evidence in terms:
        # Match feature terms against ontology using token index
        term_tokens = _split_tokens(term)
        if index.token_index:
            for token in term_tokens:
                if token in index.token_index:
                    for class_id, _ in index.token_index[token]:
                        # Feature terms are strong signals - use the weight directly
                        add_candidate(class_id, weight, f"{evidence}: {term}")

    # 3. Fallback: lexical matching for remaining unmatched cases
    if not scored:
        for token in all_tokens:
            if len(token) < 3:
                continue
            for class_id, klass in index.classes.items():
                lexical = _lexical_score(token, klass)
                if lexical >= 0.7:
                    add_candidate(class_id, lexical * 0.6, f"lexical match: {token}")

    if not scored:
        return []

    # 4. Apply equipment affinity boost
    # If point belongs to known equipment type, boost candidates that have affinity
    equipment_type = _detect_equipment_type(name)
    if equipment_type and index.equipment_affinity:
        affinity_classes = index.equipment_affinity.get(equipment_type, set())
        if affinity_classes:
            boosted: dict[str, _Candidate] = {}
            for class_id, cand in scored.items():
                if class_id in affinity_classes:
                    # Boost score for classes with equipment affinity
                    new_score = min(0.99, cand.score + 0.12)
                    boosted[class_id] = _Candidate(
                        class_id,
                        new_score,
                        cand.evidence + [f"equipment affinity: {equipment_type}"],
                    )
                else:
                    boosted[class_id] = cand
            scored = boosted

    # 5. Filter candidates by detected point function (sensor vs setpoint vs command)
    candidates = list(scored.values())
    candidates = _filter_by_function(candidates, point_function, index)

    # Sort and return top candidates
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    return ranked[:20]


def _expand_candidates(
    candidates: list[_Candidate],
    index: _OntologyIndex | None,
) -> list[_Candidate]:
    if not index or not index.classes:
        return candidates

    aggregated: dict[str, _Candidate] = {cand.class_id: cand for cand in candidates}

    def add_candidate(class_id: str, score: float, reason: str) -> None:
        if class_id not in index.classes:
            return
        existing = aggregated.get(class_id)
        if existing is None or score > existing.score:
            evidence = [] if existing is None else list(existing.evidence)
            evidence.append(reason)
            aggregated[class_id] = _Candidate(class_id, score, evidence)

    for seed in list(candidates):
        if seed.class_id not in index.classes:
            continue
        klass = index.classes[seed.class_id]
        depth = 1
        frontier = list(klass.children)
        seen: set[str] = set()
        while frontier and depth <= 2:
            next_frontier: list[str] = []
            for child_id in frontier:
                if child_id in seen:
                    continue
                seen.add(child_id)
                add_candidate(
                    child_id,
                    seed.score * (0.9**depth),
                    f"descendant of {seed.class_id}",
                )
                next_frontier.extend(index.classes[child_id].children)
            frontier = next_frontier
            depth += 1

        for parent_id in klass.parents:
            add_candidate(
                parent_id,
                seed.score * 0.75,
                f"parent of {seed.class_id}",
            )

    ranked = sorted(aggregated.values(), key=lambda c: c.score, reverse=True)
    return ranked[:30]


def _select_class(
    candidates: list[_Candidate], min_confidence: float
) -> tuple[str | None, float]:
    if not candidates:
        return None, 0.0

    # Sort by score descending
    sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)
    best = sorted_candidates[0]

    # Calculate ambiguity penalty based on score distribution
    # If multiple candidates have similar scores, reduce confidence
    adjusted_score = best.score

    if len(sorted_candidates) >= 2:
        second_best = sorted_candidates[1]
        score_gap = best.score - second_best.score

        # Small gap = high ambiguity = lower confidence
        # Gap of 0.0 -> 25% penalty, gap of 0.2+ -> no penalty
        ambiguity_penalty = max(0, 0.25 * (1 - min(score_gap / 0.20, 1.0)))
        adjusted_score -= ambiguity_penalty

        # Additional penalty if many candidates are close to the best
        # Count candidates within 0.15 of the best score
        close_candidates = sum(
            1 for c in sorted_candidates if best.score - c.score < 0.15
        )
        if close_candidates >= 4:
            # Many similar options = more uncertainty
            crowding_penalty = min(0.15, (close_candidates - 3) * 0.03)
            adjusted_score -= crowding_penalty

    # Ensure score stays in valid range
    adjusted_score = max(0.0, min(0.99, adjusted_score))

    # Always return best class - confidence indicates certainty level
    # Low confidence classes are candidates for AI enhancement
    return best.class_id, adjusted_score


@dataclass(slots=True)
class _DeviceClassification:
    """Result of device classification including sub-equipment info."""

    class_id: str | None
    confidence: float
    evidence: list[str]
    sub_equipment: dict[str, dict]
    is_composite: bool = False


def _infer_device_class_from_points(
    device_node: Node,
    point_nodes: list[Node],
    index: _OntologyIndex | None,
) -> _DeviceClassification:
    """Infer device class from its associated points.

    For large devices with multiple sub-equipment (pumps, tanks, etc.),
    classifies as a composite system and extracts sub-equipment info.
    Class resolution is done via the ontology index.
    """
    if not point_nodes:
        return _DeviceClassification(None, 0.0, [], {})

    # First, detect sub-equipment from point naming patterns
    sub_equipment = _detect_sub_equipment(point_nodes, index)

    # If we have multiple sub-equipment, consider this a composite system
    if len(sub_equipment) >= 2:
        composite_class, composite_evidence = _classify_composite_system(
            sub_equipment, index
        )
        if composite_class:
            # Calculate confidence based on how many points are covered by sub-equipment
            covered_points = sum(len(info["points"]) for info in sub_equipment.values())
            coverage_ratio = covered_points / len(point_nodes)
            # Higher confidence when more points follow the naming pattern
            confidence = min(0.95, 0.70 + coverage_ratio * 0.20)
            composite_evidence.append(
                f"sub-equipment coverage: {covered_points}/{len(point_nodes)} points"
            )
            return _DeviceClassification(
                class_id=composite_class,
                confidence=confidence,
                evidence=composite_evidence,
                sub_equipment=sub_equipment,
                is_composite=True,
            )

    # Fall back to single-equipment detection via voting
    equipment_votes: dict[str, int] = {}
    for point in point_nodes:
        point_name = point.attrs.get("name", "") or point.id
        equip_type = _detect_equipment_type(point_name)
        if equip_type:
            equipment_votes[equip_type] = equipment_votes.get(equip_type, 0) + 1

    if not equipment_votes:
        # Try to infer from device name
        device_name = device_node.attrs.get("name", "") or device_node.id
        equip_type = _detect_equipment_type(device_name)
        if equip_type:
            equipment_votes[equip_type] = 1

    # Also check device name for location patterns
    device_name_lower = (device_node.attrs.get("name", "") or device_node.id).lower()
    if not equipment_votes:
        floor_pattern = re.compile(
            r"floor[-_]?\d+|level[-_]?\d+|\d+(?:st|nd|rd|th)[-_]?floor"
        )
        if floor_pattern.search(device_name_lower):
            equipment_votes["floor"] = 1
        elif "building" in device_name_lower:
            equipment_votes["building"] = 1

    if not equipment_votes:
        return _DeviceClassification(None, 0.0, [], sub_equipment)

    # Get the most voted equipment type
    best_equip = max(equipment_votes, key=lambda k: equipment_votes[k])
    vote_count = equipment_votes[best_equip]
    total_points = len(point_nodes)

    # Resolve equipment type to ontology class
    class_id = _resolve_equipment_class(best_equip, index)

    if not class_id:
        return _DeviceClassification(None, 0.0, [], sub_equipment)

    # Confidence based on vote ratio
    confidence = min(0.95, 0.6 + (vote_count / max(total_points, 1)) * 0.35)
    evidence = (
        f"inferred from {vote_count}/{total_points} points with {best_equip} prefix"
    )

    return _DeviceClassification(
        class_id=class_id,
        confidence=confidence,
        evidence=[evidence],
        sub_equipment=sub_equipment,
        is_composite=False,
    )


def _enrich_graph(
    graph: Graph,
    *,
    topology_ref: str,
    index: _OntologyIndex | None,
    min_confidence: float,
) -> Graph:
    nodes: list[Node] = []
    edges = list(graph.edges)
    has_point_pairs = {
        (edge.source, edge.target) for edge in edges if edge.type == "hasPoint"
    }

    # Build device -> points mapping for device classification
    node_by_id = {n.id: n for n in graph.nodes}
    device_points: dict[str, list[Node]] = {}
    for edge in edges:
        if edge.type in ("hasPoint", "contains"):
            if edge.source not in device_points:
                device_points[edge.source] = []
            target_node = node_by_id.get(edge.target)
            if target_node:
                device_points[edge.source].append(target_node)

    # Track points that belong to sub-equipment (to update hasPoint edges)
    # Maps point_id -> (sub_equipment_id, sub_equipment_class)
    point_to_sub_equipment: dict[str, tuple[str, str]] = {}

    for node in graph.nodes:
        attrs = dict(node.attrs)

        # For device nodes, try to infer class from points first
        if node.type == "device":
            points = device_points.get(node.id, [])
            classification = _infer_device_class_from_points(node, points, index)

            if classification.class_id and classification.confidence >= min_confidence:
                attrs["class"] = classification.class_id
                attrs["class_confidence"] = round(classification.confidence, 4)

                # Build class_candidates with sub-equipment info for composite systems
                candidate_info: dict[str, Any] = {
                    "class": classification.class_id,
                    "confidence": round(classification.confidence, 4),
                    "evidence": classification.evidence[:8],
                }
                if classification.sub_equipment:
                    candidate_info["sub_equipment"] = list(
                        classification.sub_equipment.keys()
                    )

                attrs["class_candidates"] = [candidate_info]
                attrs["topology_ref"] = topology_ref

                # Create sub-equipment nodes for composite systems
                if classification.is_composite and classification.sub_equipment:
                    for equip_id, equip_info in classification.sub_equipment.items():
                        # Create unique node ID for sub-equipment
                        sub_equip_node_id = f"equipment:{node.id}:{equip_id}"

                        # Create the sub-equipment node
                        sub_equip_attrs: dict[str, Any] = {
                            "name": equip_id,
                            "class": equip_info["class"],
                            "class_confidence": 0.85,
                            "parent_device": node.id,
                            "topology_ref": topology_ref,
                            "inferred": True,
                        }
                        sub_equip_node = Node(
                            id=sub_equip_node_id,
                            type="equipment",
                            tags=[equip_info["type"]],
                            attrs=sub_equip_attrs,
                        )
                        nodes.append(sub_equip_node)

                        # Find appropriate relation from ontology for device -> sub-equipment
                        device_to_equip_rel = _find_relation_for_edge(
                            classification.class_id,  # e.g., brick:Pump_Station
                            equip_info["class"],  # e.g., brick:Pump
                            index,
                            default="contains",
                        )
                        # Use local name for edge type (e.g., "brick:contains" -> "contains")
                        edge_type = (
                            device_to_equip_rel.split(":")[-1]
                            if ":" in device_to_equip_rel
                            else device_to_equip_rel
                        )
                        edges.append(
                            Edge(
                                source=node.id,
                                target=sub_equip_node_id,
                                type=edge_type,
                                attrs={
                                    "inferred": True,
                                    "ontology_relation": device_to_equip_rel,
                                },
                            )
                        )

                        # Map points to their sub-equipment (with class info for relation lookup)
                        for point in equip_info["points"]:
                            point_to_sub_equipment[point.id] = (
                                sub_equip_node_id,
                                equip_info["class"],
                            )

                nodes.append(replace(node, attrs=attrs))
                continue

        seeded = _seed_candidates(node, index)
        candidates = _expand_candidates(seeded, index)
        selected_class, selected_confidence = _select_class(candidates, min_confidence)

        if selected_class is not None:
            attrs["class"] = selected_class

        attrs["class_confidence"] = round(selected_confidence, 4)
        attrs["class_candidates"] = [
            {
                "class": cand.class_id,
                "confidence": round(cand.score, 4),
                "evidence": cand.evidence[:4],
            }
            for cand in candidates[:8]
        ]
        attrs["topology_ref"] = topology_ref

        nodes.append(replace(node, attrs=attrs))

    # Build a map of node_id -> class for relation lookup
    node_classes: dict[str, str | None] = {}
    for n in nodes:
        node_classes[n.id] = n.attrs.get("class")

    # Add hasPoint edges for contains relationships
    for edge in graph.edges:
        if edge.type != "contains":
            continue
        if (edge.source, edge.target) in has_point_pairs:
            continue
        # Find appropriate relation based on source/target classes
        source_class = node_classes.get(edge.source)
        target_class = node_classes.get(edge.target)
        relation = _find_relation_for_edge(
            source_class, target_class, index, default="hasPoint"
        )
        edge_type = relation.split(":")[-1] if ":" in relation else relation
        edges.append(
            Edge(
                source=edge.source,
                target=edge.target,
                type=edge_type,
                attrs={
                    "inferred": True,
                    "source_relation": "contains",
                    "ontology_relation": relation,
                },
            )
        )

    # Add edges from sub-equipment to their points
    for point_id, (sub_equip_id, sub_equip_class) in point_to_sub_equipment.items():
        point_class = node_classes.get(point_id)
        relation = _find_relation_for_edge(
            sub_equip_class, point_class, index, default="hasPoint"
        )
        edge_type = relation.split(":")[-1] if ":" in relation else relation
        edges.append(
            Edge(
                source=sub_equip_id,
                target=point_id,
                type=edge_type,
                attrs={
                    "inferred": True,
                    "source_relation": "sub_equipment_detection",
                    "ontology_relation": relation,
                },
            )
        )

    # Build enriched metadata
    meta = GraphMeta(
        created_at=graph.meta.created_at,
        source="classification",
        input=dict(graph.meta.input),
        timings=dict(graph.meta.timings),
        success=graph.meta.success,
        errors=list(graph.meta.errors),
        error_details=list(graph.meta.error_details),
        extra={
            **graph.meta.extra,
            "classifier": {
                "version": "graph-v2",
                "topology_ref": topology_ref,
                "min_confidence": min_confidence,
                "ontology": {
                    "class_count": 0 if index is None else len(index.classes),
                    "relation_count": 0 if index is None else len(index.relations),
                },
            },
        },
    )
    return Graph(nodes=nodes, edges=edges, meta=meta)


async def classify_graph(
    graph: Graph,
    topology: TopologyInput,
    *,
    options: ClassifyOptions | None = None,
    metadata: dict[str, Any] | None = None,
) -> ClassifyResult:
    started = utc_now()
    run_options = options or ClassifyOptions()
    input_payload = ClassifyInput(
        graph=graph,
        topology=topology,
        options=run_options,
        metadata={} if metadata is None else dict(metadata),
    )
    try:
        topology_ref, topology_payload = _resolve_topology(topology)
        index = (
            _build_ontology_index(topology_payload)
            if topology_payload is not None
            else None
        )
        enriched = _enrich_graph(
            graph,
            topology_ref=topology_ref,
            index=index,
            min_confidence=run_options.min_confidence,
        )
        finished = utc_now()
        return ClassifyResult(
            input=input_payload,
            graph=enriched,
            timings=build_timings(started, finished),
            success=True,
            metadata={"topology_ref": topology_ref},
        )
    except (ValueError, OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        finished = utc_now()
        return ClassifyResult(
            input=input_payload,
            graph=graph,
            timings=build_timings(started, finished),
            success=False,
            errors=[str(exc)],
        )


def classify_graph_sync(
    graph: Graph,
    topology: TopologyInput,
    *,
    options: ClassifyOptions | None = None,
    metadata: dict[str, Any] | None = None,
) -> ClassifyResult:
    return asyncio.run(
        classify_graph(
            graph,
            topology,
            options=options,
            metadata=metadata,
        )
    )
