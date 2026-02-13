from __future__ import annotations

from types import SimpleNamespace

from obs.discovery import network as network_module


def test_parse_ip_addr_output_extracts_interfaces_and_cidrs() -> None:
    # given
    output = """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    inet 127.0.0.1/8 scope host lo
2: en0: <BROADCAST,UP,LOWER_UP> mtu 1500
    inet 192.168.10.7/24 brd 192.168.10.255 scope global en0
3: docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500
    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0
"""

    # when
    parsed = network_module._parse_ip_addr_output(output)

    # then
    assert ("en0", "192.168.10.7/24") in parsed
    assert ("docker0", "172.17.0.1/16") in parsed


def test_auto_detect_client_ip_prefers_route_lookup(monkeypatch) -> None:
    # given
    def _fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="10.0.0.9 via 10.0.0.1 dev en0 src 10.0.0.2 uid 501\n",
        )

    monkeypatch.setattr(network_module.subprocess, "run", _fake_run)

    # when
    client_ip = network_module.auto_detect_client_ip("10.0.0.9")

    # then
    assert client_ip == "10.0.0.2/24"


def test_auto_detect_client_ip_falls_back_to_detected_interfaces(monkeypatch) -> None:
    # given
    def _fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(network_module.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        network_module,
        "_detect_interfaces",
        lambda: [
            network_module._InterfaceInfo(
                iface="en0",
                ip="192.168.1.5",
                cidr="192.168.1.5/24",
                method="ip_addr",
            )
        ],
    )

    # when
    client_ip = network_module.auto_detect_client_ip("10.0.0.9")

    # then
    assert client_ip == "192.168.1.5/24"


def test_detect_local_network_raises_when_no_interfaces(monkeypatch) -> None:
    # given
    monkeypatch.setattr(network_module, "_detect_interfaces", lambda: [])

    # when / then
    try:
        network_module.detect_local_network()
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "Unable to detect local network" in str(exc)
