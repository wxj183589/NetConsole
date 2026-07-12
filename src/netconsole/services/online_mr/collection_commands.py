from __future__ import annotations


CONFIG_COLLECT_COMMANDS: tuple[str, ...] = (
    "screen-length disable",
    "display current-configuration",
    "quit",
)

INIT_COMMANDS: tuple[str, ...] = (
    "screen-length disable",
    "terminal logging level 7",
    "terminal monitor",
    "system-view",
    "user-interface vty 0 31",
    "idle-timeout 1440 0",
    "return",
    "system-view",
    "probe",
    "return",
)

TERMINAL_MONITOR_INIT_COMMANDS: tuple[str, ...] = (
    "screen-length disable",
    "terminal monitor",
    "terminal logging level 7",
)

NORMAL_DISPLAY_PREPARE_COMMANDS: tuple[str, ...] = ("screen-length disable",)
PROBE_STREAM_PREPARE_COMMANDS: tuple[str, ...] = ("screen-length disable", "system-view", "probe")

TASK_COMMANDS: dict[str, tuple[str, ...]] = {
    "mesh_link": ("display clock", "display wlan mesh-link"),
    "channel_busy": ("display clock", "display ar5drv 1 channelbusy"),
    "ap_radio_statistics": ("display clock", "display ar5drv 1 statistics"),
    "switch_history": ("display clock", "display wlan mesh-link switch-history"),
    "interface_rate": ("display clock", "dis counters rate inbound interface", "dis counters rate outbound interface"),
    "wireless_status": (
        "display clock",
        "display ar5drv 1 client all rssi",
        "display ar5drv 1 client all status",
    ),
}


def stream_prepare_commands(task_type: str) -> tuple[str, ...]:
    if task_type in {"channel_busy", "ap_radio_statistics", "wireless_status"}:
        return PROBE_STREAM_PREPARE_COMMANDS
    return NORMAL_DISPLAY_PREPARE_COMMANDS


def repeat_command_group(task_type: str, *, interval: int | None = None, radio_id: int = 1) -> tuple[str, ...]:
    delay = max(1, int(interval or 1))
    if task_type == "mesh_link":
        return ("display clock", "display wlan mesh-link", f"repeat 2 delay {delay}")
    if task_type == "channel_busy":
        return ("display clock", f"display ar5drv {radio_id} channelbusy", f"repeat 2 delay {delay}")
    if task_type == "ap_radio_statistics":
        return ("display clock", f"display ar5drv {radio_id} statistics", f"repeat 2 delay {delay}")
    if task_type == "wireless_status":
        return (
            "display clock",
            f"display ar5drv {radio_id} client all rssi",
            f"display ar5drv {radio_id} client all status",
            f"repeat 3 delay {delay}",
        )
    if task_type == "switch_history":
        return ("display clock", "display wlan mesh-link switch-history", f"repeat 2 delay {delay}")
    if task_type == "interface_rate":
        return (
            "display clock",
            "dis counters rate inbound interface",
            "dis counters rate outbound interface",
            f"repeat 3 delay {delay}",
        )
    raise ValueError(f"unsupported repeat task: {task_type}")
