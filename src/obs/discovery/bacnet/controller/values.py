"""Conversions from bacpypes3 values to the plain data this package returns."""

from __future__ import annotations

from typing import Any

from bacpypes3.primitivedata import Boolean, Null


def normalize_object_type(object_type: str) -> str:
    """``"binary-output"`` -> ``"binaryOutput"``, the form used in this package."""
    if "-" not in object_type:
        return object_type
    first, *rest = object_type.split("-")
    return first + "".join(word.capitalize() for word in rest)


def to_native(value: Any) -> bool | int | float | str | None:
    """A BACnet value (bacpypes3 ``AnyAtomic``, atomic or native) as plain data.

    Null -> ``None`` (release, never 0), Boolean -> ``bool``, Real ->
    ``float``, Unsigned / Integer / Enumerated -> ``int`` (binary objects
    send Enumerated 0/1), anything else -> ``str``.
    """
    get_value = getattr(value, "get_value", None)
    if callable(get_value):
        value = get_value()
    if value is None or isinstance(value, Null):
        return None
    if isinstance(value, bool | Boolean):
        return bool(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, int):
        return int(value)
    return str(value)
