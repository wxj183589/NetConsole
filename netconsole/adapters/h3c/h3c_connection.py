from __future__ import annotations

from typing import Any

from netconsole.models.device import Device

try:
    from netmiko import ConnectHandler
except ImportError:  # pragma: no cover
    ConnectHandler = None  # type: ignore[assignment]


H3C_ENCODING = "gb2312"
H3C_FALLBACK_ENCODING = "utf-8"


def execute_h3c_command(conn: Any, cmd: str) -> str:
    try:
        return conn.send_command(cmd, encoding=H3C_ENCODING)
    except UnicodeDecodeError:
        return conn.send_command(cmd, encoding=H3C_FALLBACK_ENCODING)


class H3CConnection:
    def __init__(self, device: Device) -> None:
        self.device = device
        self.conn: Any | None = None

    def params(self) -> dict[str, object]:
        return {
            "device_type": "hp_comware",
            "host": self.device.ip_address,
            "username": self.device.ssh_username or self.device.telnet_username or "",
            "password": self.device.ssh_password or self.device.telnet_password or "",
            "port": int(self.device.ssh_port or self.device.telnet_port or 22),
            "encoding": H3C_ENCODING,
            "session_log": None,
            "global_delay_factor": 1,
        }

    def connect(self) -> Any:
        if ConnectHandler is None:
            raise RuntimeError("netmiko is not installed")
        self.conn = ConnectHandler(**self.params())
        return self.conn

    def send(self, cmd: str) -> str:
        if self.conn is None:
            self.connect()
        return execute_h3c_command(self.conn, cmd)

    def disconnect(self) -> None:
        if self.conn is not None:
            self.conn.disconnect()
            self.conn = None

