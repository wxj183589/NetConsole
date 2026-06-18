from __future__ import annotations

from netconsole.models.device import Device


class H3CCommandProfile:
    def __init__(self, device: Device) -> None:
        self.device = device
        self.version = self._detect_version()

    def get_command(self, name: str) -> str:
        commands = {
            "V5": {
                "interface": "display interface",
                "optical": "display transceiver",
                "lldp": "display lldp neighbor-information list",
            },
            "V7": {
                "interface": "display interface brief",
                "optical": "display transceiver diagnosis interface",
                "lldp": "display lldp neighbor-information verbose",
            },
            "V9": {
                "interface": "display interface all",
                "optical": "display optical-module",
                "lldp": "display lldp neighbor-information verbose",
            },
        }
        return commands.get(self.version, commands["V7"])[name]

    def _detect_version(self) -> str:
        text = " ".join(
            str(value or "")
            for value in (
                getattr(self.device, "model", None),
                getattr(self.device, "remark", None),
                getattr(self.device, "sysname", None),
            )
        ).upper()
        for version in ("V5", "V7", "V9"):
            if version in text:
                return version
        return "V7"
