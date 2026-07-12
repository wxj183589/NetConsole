from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal


OmniPeekRole = Literal["trackside_ap", "onboard_mr"]
OmniPeekEntryKind = Literal[
    "trackside_physical",
    "trackside_r1",
    "trackside_r2",
    "onboard_physical",
    "onboard_r1",
    "onboard_r2",
]

SOURCE_AC_FIT_AP = "AC FIT-AP资源"
SOURCE_AP_EXTENSION = "AP扩展信息"
SOURCE_DEVICE_MANAGEMENT = "设备管理"

ROLE_LABELS: dict[OmniPeekRole, str] = {
    "trackside_ap": "轨旁AP",
    "onboard_mr": "车载MR",
}

ENTRY_KIND_LABELS: dict[OmniPeekEntryKind, str] = {
    "trackside_physical": "轨旁AP物理MAC",
    "trackside_r1": "轨旁AP R1",
    "trackside_r2": "轨旁AP R2",
    "onboard_physical": "车载MR物理MAC",
    "onboard_r1": "车载MR R1",
    "onboard_r2": "车载MR R2",
}

ENTRY_KIND_GROUP_SUFFIX: dict[OmniPeekEntryKind, str] = {
    "trackside_physical": "轨旁AP物理MAC组",
    "trackside_r1": "轨旁AP R1组",
    "trackside_r2": "轨旁AP R2组",
    "onboard_physical": "车载MR物理MAC组",
    "onboard_r1": "车载MR R1组",
    "onboard_r2": "车载MR R2组",
}

ENTRY_KIND_NAME_SUFFIX: dict[OmniPeekEntryKind, str] = {
    "trackside_physical": "物理MAC",
    "trackside_r1": "R1",
    "trackside_r2": "R2",
    "onboard_physical": "物理MAC",
    "onboard_r1": "R1",
    "onboard_r2": "R2",
}

DEFAULT_OMNIPEEK_COLORS: dict[OmniPeekEntryKind, str] = {
    "trackside_physical": "#00FF00",
    "trackside_r1": "#0070C0",
    "trackside_r2": "#FFC000",
    "onboard_physical": "#7030A0",
    "onboard_r1": "#00B0F0",
    "onboard_r2": "#FF0000",
}

OMNIPEEK_ENTRY_KIND_ORDER: tuple[OmniPeekEntryKind, ...] = (
    "trackside_physical",
    "trackside_r1",
    "trackside_r2",
    "onboard_physical",
    "onboard_r1",
    "onboard_r2",
)


@dataclass
class OmniPeekDeviceItem:
    role: OmniPeekRole
    name: str
    physical_mac: str = ""
    system_name: str = ""
    location: str = ""
    source: str = ""
    sources: list[str] = field(default_factory=list)
    raw: dict[str, object | None] = field(default_factory=dict)
    key: str = ""
    selected: bool = True
    force_export: bool = False
    radio_mode: str = "auto"
    export_physical: bool = True
    export_r1: bool = True
    export_r2: bool = True
    normalized_physical_mac: str = ""
    r1_mac: str = ""
    r2_mac: str = ""
    r1_source: str = ""
    r2_source: str = ""
    status: str = "正常"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OmniPeekNameEntry:
    name: str
    mac: str
    group: str
    color: str
    kind: OmniPeekEntryKind
    item_key: str


@dataclass
class OmniPeekExportConfig:
    line_name: str
    output_path: Path
    include_ac_fit_ap: bool = True
    include_ap_extensions: bool = True
    include_device_mr: bool = True
    export_trackside_physical: bool = True
    export_trackside_r1: bool = True
    export_trackside_r2: bool = True
    export_onboard_physical: bool = True
    export_onboard_r1: bool = True
    export_onboard_r2: bool = True
    onboard_radio_mode: str = "auto"
    enable_h3c_derivation: bool = True
    colors: dict[OmniPeekEntryKind, str] = field(default_factory=lambda: dict(DEFAULT_OMNIPEEK_COLORS))
    mod_time: datetime | None = None


@dataclass(frozen=True)
class OmniPeekExportResult:
    output_path: Path
    log_path: Path
    counts: dict[OmniPeekEntryKind, int]
    skipped_count: int
    error_count: int
    source_counts: dict[str, int]
    warnings: list[str] = field(default_factory=list)

    @property
    def total_entries(self) -> int:
        return sum(self.counts.values())
