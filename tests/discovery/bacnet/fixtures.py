from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from obs.discovery.bacnet.controller import BACnetController


@pytest.fixture
def bacnet_mock() -> Mock:
    mock = Mock()
    mock.localDevice = Mock()
    mock.localDevice.objectIdentifier = ("device", 9999)
    mock.who_is = AsyncMock(return_value=[])
    mock.read = AsyncMock(return_value=None)
    mock.readMultiple = AsyncMock(return_value={})
    return mock


@pytest.fixture
def initialized_controller(bacnet_mock: Mock) -> BACnetController:
    controller = BACnetController(client_ip="192.168.1.2/24")
    controller._initialized = True
    controller.bacnet = bacnet_mock
    return controller
