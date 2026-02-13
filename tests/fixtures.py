from __future__ import annotations

import pytest

from obs.discovery.types import Device, Point
from tests.factories import make_discovery_device, make_discovery_point


@pytest.fixture
def discovery_point() -> Point:
    return make_discovery_point()


@pytest.fixture
def discovery_device(discovery_point: Point) -> Device:
    return make_discovery_device(points=[discovery_point])
