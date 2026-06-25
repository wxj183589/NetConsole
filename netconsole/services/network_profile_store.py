from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AdapterMatch:
    name: str = ""
    mac: str = ""
    description_keyword: str = ""


@dataclass(frozen=True)
class SecondaryIp:
    ip_address: str
    prefix_length: int


@dataclass(frozen=True)
class AdapterProfile:
    profile_name: str
    adapter_match: AdapterMatch = field(default_factory=AdapterMatch)
    mode: str = "dhcp"
    ip_address: str = ""
    prefix_length: int = 24
    gateway: str = ""
    dns: list[str] = field(default_factory=list)
    secondary_ips: list[SecondaryIp] = field(default_factory=list)
    vlan_id: int = 0
    remark: str = ""


class NetworkProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[AdapterProfile]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [_adapter_profile_from_dict(row) for row in data.get("adapter_profiles", []) if isinstance(row, dict)]

    def save(self, profiles: list[AdapterProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"adapter_profiles": [asdict(profile) for profile in profiles]}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, profile: AdapterProfile) -> None:
        profiles = [row for row in self.load() if row.profile_name != profile.profile_name]
        profiles.append(profile)
        self.save(profiles)

    def delete(self, profile_name: str) -> None:
        self.save([row for row in self.load() if row.profile_name != profile_name])


def _adapter_profile_from_dict(row: dict) -> AdapterProfile:
    match = row.get("adapter_match") if isinstance(row.get("adapter_match"), dict) else {}
    secondaries = row.get("secondary_ips") if isinstance(row.get("secondary_ips"), list) else []
    return AdapterProfile(
        profile_name=str(row.get("profile_name", "")),
        adapter_match=AdapterMatch(
            name=str(match.get("name", "")),
            mac=str(match.get("mac", "")),
            description_keyword=str(match.get("description_keyword", "")),
        ),
        mode=str(row.get("mode", "dhcp")),
        ip_address=str(row.get("ip_address", "")),
        prefix_length=int(row.get("prefix_length", 24) or 24),
        gateway=str(row.get("gateway", "")),
        dns=[str(item) for item in row.get("dns", []) if str(item).strip()],
        secondary_ips=[
            SecondaryIp(str(item.get("ip_address", "")), int(item.get("prefix_length", 24) or 24))
            for item in secondaries
            if isinstance(item, dict) and str(item.get("ip_address", "")).strip()
        ],
        vlan_id=int(row.get("vlan_id", 0) or 0),
        remark=str(row.get("remark", "")),
    )
