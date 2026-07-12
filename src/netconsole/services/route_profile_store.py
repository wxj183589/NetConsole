from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RouteProfileEntry:
    destination_prefix: str
    next_hop: str
    interface_alias: str
    metric: int = 10
    persistent: bool = True
    remark: str = ""
    netmask: str = ""
    interface_index: int = 0


@dataclass(frozen=True)
class RouteProfile:
    profile_name: str
    routes: list[RouteProfileEntry] = field(default_factory=list)


class RouteProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[RouteProfile]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [_route_profile_from_dict(row) for row in data.get("route_profiles", []) if isinstance(row, dict)]

    def save(self, profiles: list[RouteProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"route_profiles": [asdict(profile) for profile in profiles]}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, profile: RouteProfile) -> None:
        profiles = [row for row in self.load() if row.profile_name != profile.profile_name]
        profiles.append(profile)
        self.save(profiles)

    def delete(self, profile_name: str) -> None:
        self.save([row for row in self.load() if row.profile_name != profile_name])


def _route_profile_from_dict(row: dict) -> RouteProfile:
    routes = row.get("routes") if isinstance(row.get("routes"), list) else []
    return RouteProfile(
        profile_name=str(row.get("profile_name", "")),
        routes=[
            RouteProfileEntry(
                destination_prefix=str(item.get("destination_prefix", "")),
                next_hop=str(item.get("next_hop", "")),
                interface_alias=str(item.get("interface_alias", "")),
                metric=int(item.get("metric", 10) or 10),
                persistent=bool(item.get("persistent", True)),
                remark=str(item.get("remark", "")),
                netmask=str(item.get("netmask", "")),
                interface_index=int(item.get("interface_index", 0) or 0),
            )
            for item in routes
            if isinstance(item, dict) and str(item.get("destination_prefix", "")).strip()
        ],
    )
