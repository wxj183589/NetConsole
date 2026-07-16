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


class H3cAcCommandProfile:
    """H3C AC command profile. V5/V7 currently reuse the verified V9 command set."""

    def __init__(self, device: Device | None = None) -> None:
        self.device = device
        self.version = self._detect_version()

    @property
    def fit_ap_resource_commands(self) -> tuple[str, ...]:
        return (
            "screen-length disable",
            "display wlan ap all",
            "display wlan ap all address",
            "display wlan ap all radio",
            "display wlan ap all connection-record",
            "display wlan ap all radio type",
            "display wlan ap unauthenticated",
            "display wlan ap all lldp",
        )

    @property
    def ac_info_commands(self) -> tuple[str, ...]:
        return (
            "screen-length disable",
            "display cpu-usage",
            "display memory",
            "display version",
            "display device",
            "display device manuinfo",
            "display ip https",
            "display ip https | include port",
        )

    @property
    def persist_auto_ap_commands(self) -> tuple[str, ...]:
        return (
            "system-view",
            "wlan auto-ap persistent all",
            "save force",
            "return",
            "quit",
        )

    @property
    def enable_ap_remote_login_commands(self) -> tuple[str, ...]:
        return (
            "screen-length disable",
            "system-view",
            "probe",
            "wlan ap-execute all exec-console enable",
            "return",
            "quit",
        )

    def _detect_version(self) -> str:
        if self.device is None:
            return "V9"
        text = " ".join(
            str(value or "")
            for value in (
                getattr(self.device, "model", None),
                getattr(self.device, "remark", None),
                getattr(self.device, "sysname", None),
                getattr(self.device, "software_version", None),
            )
        ).upper()
        for version in ("V5", "V7", "V9"):
            if version in text:
                return version
        return "V9"
