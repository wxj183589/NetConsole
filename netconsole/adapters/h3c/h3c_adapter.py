from __future__ import annotations

from netconsole.adapters.h3c.h3c_command_profile import H3CCommandProfile
from netconsole.adapters.h3c.h3c_connection import H3CConnection
from netconsole.adapters.h3c.h3c_parser import H3CParser
from netconsole.models.device import Device


class H3CAdapter:
    def __init__(self, device: Device) -> None:
        self.device = device
        self.conn = H3CConnection(device)
        self.profile = H3CCommandProfile(device)
        self.parser = H3CParser()

    def collect_all(self) -> dict[str, object]:
        return {
            "system": self.get_system_info(),
            "interfaces": self.get_interfaces(),
            "optical": self.get_optical(),
            "lldp": self.get_lldp(),
        }

    def get_system_info(self) -> str:
        return self.conn.send("display version")

    def get_interfaces(self) -> list[dict[str, object | None]]:
        return self.parser.parse_interfaces(self.conn.send(self.profile.get_command("interface")))

    def get_optical(self) -> list[dict[str, object | None]]:
        return self.parser.parse_optical(self.conn.send(self.profile.get_command("optical")))

    def get_lldp(self) -> list[dict[str, object | None]]:
        return self.parser.parse_lldp(self.conn.send(self.profile.get_command("lldp")))
