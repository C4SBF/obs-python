"""Network detection utilities."""

import ipaddress
import logging
import re
import socket
import subprocess
from dataclasses import dataclass

__all__ = [
    "auto_detect_client_ip",
    "detect_local_network",
]

logger = logging.getLogger(__name__)

_SKIP_IFACE_RE = re.compile(r"^(lo|docker\d*|br-[0-9a-f]+|veth[0-9a-f]+|virbr\d+)")


def _is_virtual_interface(name: str) -> bool:
    return _SKIP_IFACE_RE.match(name) is not None


def _parse_ip_addr_output(output: str) -> list[tuple[str, str]]:
    """Parse `ip addr show` output into (interface_name, ip/cidr) pairs."""
    results: list[tuple[str, str]] = []
    current_iface = ""
    for line in output.split("\n"):
        iface_match = re.match(r"\d+:\s+(\S+?)[@:]", line)
        if iface_match:
            current_iface = iface_match.group(1)
            continue
        if "inet " in line and "/" in line:
            parts = line.split()
            for part in parts:
                if "/" in part and "." in part and not part.startswith("brd"):
                    results.append((current_iface, part))
    return results


@dataclass
class _InterfaceInfo:
    iface: str
    ip: str
    cidr: str  # e.g. "192.168.1.100/24"
    method: str  # detection method for logging


def _detect_interfaces() -> list[_InterfaceInfo]:
    """Detect local network interfaces via ip-addr / netifaces / socket fallback."""
    results: list[_InterfaceInfo] = []

    # Method 1: ip addr show (Linux)
    try:
        proc = subprocess.run(
            ["ip", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            for iface, ip_cidr in _parse_ip_addr_output(proc.stdout):
                ip_only = ip_cidr.split("/")[0]
                if ip_only.startswith("127."):
                    continue
                if _is_virtual_interface(iface):
                    logger.debug(f"Skipping virtual interface {iface} ({ip_cidr})")
                    continue
                results.append(
                    _InterfaceInfo(
                        iface=iface, ip=ip_only, cidr=ip_cidr, method="ip_addr"
                    )
                )
    except FileNotFoundError:
        logger.debug("'ip' command not available")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        logger.debug(f"ip addr method failed: {e}")

    if results:
        return results

    # Method 2: netifaces
    try:
        import netifaces

        for iface in netifaces.interfaces():
            if _is_virtual_interface(iface):
                continue
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for addr_info in addrs[netifaces.AF_INET]:
                    ip = addr_info.get("addr")
                    netmask = addr_info.get("netmask")
                    if ip and netmask and not ip.startswith("127."):
                        prefix = ipaddress.IPv4Network(
                            f"0.0.0.0/{netmask}", strict=False
                        ).prefixlen
                        results.append(
                            _InterfaceInfo(
                                iface=iface,
                                ip=ip,
                                cidr=f"{ip}/{prefix}",
                                method="netifaces",
                            )
                        )
    except ImportError:
        logger.debug("netifaces module not available")
    except (OSError, ValueError) as e:
        logger.debug(f"netifaces method failed: {e}")

    if results:
        return results

    # Method 3: ifaddr (cross-platform, works in containers)
    try:
        import ifaddr

        for adapter in ifaddr.get_adapters():
            if _is_virtual_interface(adapter.name):
                continue
            for ip_info in adapter.ips:
                # Skip IPv6 and loopback
                if not isinstance(ip_info.ip, str):
                    continue
                if ip_info.ip.startswith("127."):
                    continue
                prefix = getattr(ip_info, "network_prefix", 24)
                results.append(
                    _InterfaceInfo(
                        iface=adapter.name,
                        ip=ip_info.ip,
                        cidr=f"{ip_info.ip}/{prefix}",
                        method="ifaddr",
                    )
                )
    except ImportError:
        logger.debug("ifaddr module not available")
    except (OSError, ValueError) as e:
        logger.debug(f"ifaddr method failed: {e}")

    if results:
        return results

    # Method 4: socket (assumes /24)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]

        if local_ip and not local_ip.startswith("127."):
            results.append(
                _InterfaceInfo(
                    iface="", ip=local_ip, cidr=f"{local_ip}/24", method="socket"
                )
            )
    except OSError as e:
        logger.debug(f"socket method failed: {e}")

    return results


def detect_local_network() -> str:
    """Detect the local network subnet in CIDR notation (e.g. "192.168.1.0/24")."""
    interfaces = _detect_interfaces()
    if not interfaces:
        raise RuntimeError("Unable to detect local network")

    info = interfaces[0]
    network = ipaddress.IPv4Network(info.cidr, strict=False)
    subnet = str(network)
    logger.info(
        f"Detected local network: {subnet}"
        + (f" (via {info.iface})" if info.iface else f" (via {info.method})")
    )
    return subnet


def auto_detect_client_ip(device_address: str | None = None) -> str:
    """Auto-detect client IP as "x.x.x.x/prefix".

    If device_address is provided, uses route-based detection first.
    """
    if device_address:
        try:
            result = subprocess.run(
                ["ip", "route", "get", device_address],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0 and "src" in result.stdout:
                parts = result.stdout.split()
                src_ip = parts[parts.index("src") + 1]
                # Look up actual prefix from interfaces
                prefix = 24  # fallback
                for iface in _detect_interfaces():
                    if iface.ip == src_ip:
                        prefix = int(iface.cidr.split("/")[1])
                        break
                logger.info(
                    f"Auto-detected client IP via route to {device_address}: {src_ip}/{prefix}"
                )
                return f"{src_ip}/{prefix}"
        except FileNotFoundError:
            logger.debug("'ip' command not available")
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            logger.debug(f"Route detection failed: {e}")

    interfaces = _detect_interfaces()
    if not interfaces:
        raise RuntimeError("Unable to detect client IP")

    info = interfaces[0]
    logger.info(
        f"Auto-detected client IP: {info.cidr}"
        + (f" (via {info.iface})" if info.iface else f" (via {info.method})")
    )
    return info.cidr
