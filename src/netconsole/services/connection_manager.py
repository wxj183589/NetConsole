from __future__ import annotations

from dataclasses import dataclass

from netconsole.models.device import Device


@dataclass(frozen=True)
class TunnelProfile:
    label: str
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    local_port_mode: str = "auto"
    local_port: int | None = None

    @property
    def is_complete(self) -> bool:
        return bool(self.enabled and self.host and self.port and self.username)


@dataclass(frozen=True)
class DeviceConnectionProfile:
    device_uuid: str
    device_name: str
    primary_address: str
    backup_address: str
    protocol: str
    port: int
    username: str
    password: str
    tunnel_enabled: bool
    tunnels: tuple[TunnelProfile, ...]


@dataclass(frozen=True)
class ConnectionAttemptResult:
    label: str
    host: str
    port: int
    protocol: str
    username: str
    password: str
    target_role: str
    via_tunnel: bool = False
    tunnel: TunnelProfile | None = None
    tunnel_label: str = ""


class ConnectionManager:
    def build_profile(self, device: Device) -> DeviceConnectionProfile:
        protocol = _device_protocol(device)
        port = _device_port(device, protocol)
        username = _device_username(device, protocol)
        password = _device_password(device, protocol)
        tunnels = (
            TunnelProfile(
                label="tunnel1",
                enabled=_tunnel_host_enabled(device.tunnel1_host),
                host=str(device.tunnel1_host or ""),
                port=int(device.tunnel1_port or 22),
                username=str(device.tunnel1_username or ""),
                password=str(device.tunnel1_password or ""),
                local_port_mode="auto",
                local_port=None,
            ),
            TunnelProfile(
                label="tunnel2",
                enabled=_tunnel_host_enabled(device.tunnel2_host),
                host=str(device.tunnel2_host or ""),
                port=int(device.tunnel2_port or 22),
                username=str(device.tunnel2_username or ""),
                password=str(device.tunnel2_password or ""),
                local_port_mode="auto",
                local_port=None,
            ),
        )
        return DeviceConnectionProfile(
            device_uuid=str(device.device_uuid or ""),
            device_name=str(device.name or ""),
            primary_address=str(device.primary_address or ""),
            backup_address=str(device.backup_address or ""),
            protocol=protocol,
            port=port,
            username=username,
            password=password,
            tunnel_enabled=_tunnel_host_enabled(device.tunnel1_host) or _tunnel_host_enabled(device.tunnel2_host),
            tunnels=tunnels,
        )

    def iter_attempts(self, device: Device) -> list[ConnectionAttemptResult]:
        profile = self.build_profile(device)
        attempts: list[ConnectionAttemptResult] = []
        addresses = _connection_addresses(profile)
        for protocol, port, username, password in _device_protocol_attempts(device):
            suffix = "" if protocol == profile.protocol else f"_{protocol.casefold()}"
            for target_role, address in addresses:
                attempts.append(
                    ConnectionAttemptResult(
                        f"{target_role}_direct{suffix}",
                        address,
                        port,
                        protocol,
                        username,
                        password,
                        target_role,
                    )
                )
            for tunnel in profile.tunnels:
                if not tunnel.is_complete:
                    continue
                for target_role, address in addresses:
                    attempts.append(
                        ConnectionAttemptResult(
                            f"{tunnel.label}_{target_role}{suffix}",
                            address,
                            port,
                            protocol,
                            username,
                            password,
                            target_role,
                            via_tunnel=True,
                            tunnel=tunnel,
                            tunnel_label=tunnel.label,
                        )
                    )
        return attempts


def _connection_addresses(
    profile: DeviceConnectionProfile,
) -> list[tuple[str, str]]:
    addresses: list[tuple[str, str]] = []
    seen: set[str] = set()
    for target_role, raw_address in (
        ("primary", profile.primary_address),
        ("backup", profile.backup_address),
    ):
        address = str(raw_address or "").strip()
        identity = address.casefold()
        if not address or identity in seen:
            continue
        seen.add(identity)
        addresses.append((target_role, address))
    return addresses


def _device_protocol(device: Device) -> str:
    if bool(device.ssh_enabled):
        return "SSH"
    if bool(device.telnet_enabled):
        return "Telnet"
    if device.protocol:
        return str(device.protocol)
    return ""


def _device_protocol_attempts(device: Device) -> list[tuple[str, int, str, str]]:
    attempts: list[tuple[str, int, str, str]] = []
    if bool(device.ssh_enabled):
        attempts.append(("SSH", int(device.ssh_port or 22), str(device.ssh_username or ""), str(device.ssh_password or "")))
    if bool(device.telnet_enabled):
        attempts.append(("Telnet", int(device.telnet_port or 23), str(device.telnet_username or ""), str(device.telnet_password or "")))
    if attempts:
        return attempts
    protocol = _device_protocol(device)
    if not protocol:
        return []
    return [(protocol, _device_port(device, protocol), _device_username(device, protocol), _device_password(device, protocol))]


def _device_port(device: Device, protocol: str) -> int:
    if protocol.casefold() == "telnet":
        return int(device.telnet_port or 23)
    if protocol.casefold() == "ssh":
        return int(device.ssh_port or 22)
    return int(device.port or 0)


def _device_username(device: Device, protocol: str) -> str:
    if protocol.casefold() == "telnet":
        return str(device.telnet_username or "")
    if protocol.casefold() == "ssh":
        return str(device.ssh_username or "")
    return str(device.username or "")


def _device_password(device: Device, protocol: str) -> str:
    if protocol.casefold() == "telnet":
        return str(device.telnet_password or "")
    if protocol.casefold() == "ssh":
        return str(device.ssh_password or "")
    return str(device.password or "")


def _tunnel_host_enabled(value: object) -> bool:
    return bool(str(value or "").strip())
