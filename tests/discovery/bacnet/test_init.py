from __future__ import annotations

import obs.discovery.bacnet as bacnet


def test_init_exports_new_api_symbols() -> None:
    # given
    expected = {
        "scan_bacnet_network",
        "scan_bacnet_network_sync",
        "discover_bacnet_objects",
        "discover_bacnet_objects_sync",
        "BACnetDevice",
        "BACnetObject",
        "BACnetNetworkScanResult",
        "BACnetObjectsDiscoveryResult",
    }

    # when
    exported = set(bacnet.__all__)

    # then
    assert expected.issubset(exported)
