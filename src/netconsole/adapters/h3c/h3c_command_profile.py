from __future__ import annotations

from netconsole.models.device import Device
from netconsole.services.device_command_profile_service import resolve_h3c_capability


class H3cAcCommandProfile:
    """H3C AC read-only capability adapter.

    The adapter keeps the historical property API used by AC services, while
    command ownership is centralized in the Comware family capability
    resolver.  Release strings are diagnostic metadata and do not select a
    separate allow-list unless a future override is explicitly registered.
    """

    def __init__(self, device: Device | None = None) -> None:
        self.device = device
        self.version = self._detect_version()

    @property
    def fit_ap_resource_commands(self) -> tuple[str, ...]:
        return self._capability_commands(
            "session_prepare",
            "wlan_ap_all",
            "wlan_ap_address",
            "wlan_ap_radio",
            "wlan_ap_radio_verbose",
            "wlan_ap_connection_record",
            "wlan_ap_radio_type",
            "wlan_ap_unauthenticated",
            "wlan_ap_lldp",
        )

    @property
    def fit_ap_detail_commands(self) -> tuple[str, ...]:
        """Legacy bulk sequence retained for callers outside the Web detail path."""
        return self._capability_commands(
            "session_prepare",
            "wlan_ap_all",
            "wlan_ap_address",
            "wlan_ap_radio",
            "wlan_ap_radio_verbose",
            "wlan_ap_connection_record",
            "wlan_ap_radio_type",
            "wlan_ap_lldp",
        )

    @property
    def fit_ap_verbose_all_commands(self) -> tuple[str, ...]:
        return self._capability_commands("session_prepare", "wlan_ap_verbose_all")

    def fit_ap_verbose_commands(self, ap_name: str) -> tuple[str, ...]:
        name = str(ap_name or "").strip()
        if not name:
            return self._capability_commands("session_prepare")
        return self._capability_commands(
            "session_prepare",
            "wlan_ap_verbose_name",
            command_suffix=name,
        )

    @property
    def ac_info_commands(self) -> tuple[str, ...]:
        return self._capability_commands(
            "session_prepare",
            "cpu_usage",
            "memory",
            "version",
            "device",
            "device_manuinfo",
            "https",
            "https_port",
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

    def _capability_commands(
        self,
        *capabilities: str,
        command_suffix: str = "",
    ) -> tuple[str, ...]:
        commands: list[str] = []
        for capability in capabilities:
            if self.device is None:
                # Keep the adapter's existing public behavior for legacy
                # callers that construct a profile before loading a Device.
                resolved_commands = _LEGACY_AC_CAPABILITIES.get(capability)
                if resolved_commands is None:
                    raise KeyError(capability)
                commands.extend(resolved_commands)
                continue
            resolved = resolve_h3c_capability(self.device, capability)
            command = resolved.commands[0]
            if command_suffix:
                command = command.replace("<name>", command_suffix).replace(
                    "{name}", command_suffix
                )
            commands.append(command)
        return tuple(commands)


_LEGACY_AC_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "session_prepare": ("screen-length disable",),
    "wlan_ap_verbose_all": ("display wlan ap all verbose",),
    "wlan_ap_verbose_name": ("display wlan ap name <name> verbose",),
    "cpu_usage": ("display cpu-usage",),
    "memory": ("display memory",),
    "version": ("display version",),
    "device": ("display device",),
    "device_manuinfo": ("display device manuinfo",),
    "https": ("display ip https",),
    "https_port": ("display ip https | include port",),
}
