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
    via_tunnel: bool = False
    tunnel: TunnelProfile | None = None


class ConnectionManager:
    def build_profile(self, device: Device) -> DeviceConnectionProfile:
        protocol = _device_protocol(device)
        port = _device_port(device, protocol)
        username = _device_username(device, protocol)
        password = _device_password(device, protocol)
        tunnels = (
            TunnelProfile(
                label="tunnel1",
                enabled=bool(device.tunnel_enabled and device.tunnel1_enabled),
                host=str(device.tunnel1_host or ""),
                port=int(device.tunnel1_port or 22),
                username=str(device.tunnel1_username or ""),
                password=str(device.tunnel1_password or ""),
                local_port_mode="auto",
                local_port=None,
            ),
            TunnelProfile(
                label="tunnel2",
                enabled=bool(device.tunnel_enabled and device.tunnel2_enabled),
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
            tunnel_enabled=bool(device.tunnel_enabled),
            tunnels=tunnels,
        )

    def iter_attempts(self, device: Device) -> list[ConnectionAttemptResult]:
        profile = self.build_profile(device)
        attempts: list[ConnectionAttemptResult] = []
        if profile.primary_address:
            attempts.append(
                ConnectionAttemptResult("primary_direct", profile.primary_address, profile.port, profile.protocol, profile.username, profile.password)
            )
        if profile.backup_address:
            attempts.append(
                ConnectionAttemptResult("backup_direct", profile.backup_address, profile.port, profile.protocol, profile.username, profile.password)
            )
        for tunnel in profile.tunnels:
            if tunnel.is_complete and profile.primary_address:
                attempts.append(
                    ConnectionAttemptResult(
                        tunnel.label,
                        profile.primary_address,
                        profile.port,
                        profile.protocol,
                        profile.username,
                        profile.password,
                        via_tunnel=True,
                        tunnel=tunnel,
                    )
                )
        return attempts


def _device_protocol(device: Device) -> str:
    if bool(device.ssh_enabled):
        return "SSH"
    if bool(device.telnet_enabled):
        return "Telnet"
    if device.protocol:
        return str(device.protocol)
    return ""


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
