from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.demo_data import insert_demo_devices


DEFAULT_SITE = "demo"
INVALID_SITE_NAME_CHARS = set('<>:"/\\|?*')


@dataclass(frozen=True)
class Site:
    name: str
    root_path: Path
    database_path: Path
    display_name: str = ""
    line_name: str = ""
    system_type: str = ""
    network_domain: str = "default"
    remark: str = ""
    schema_version: int = 1


class SiteManager:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def ensure_demo_site(self) -> Site:
        return self.init_site_database(DEFAULT_SITE, with_demo_data=True)

    def ensure_default_site(self) -> Site:
        return self.ensure_demo_site()

    def ensure_site(self, site_name: str) -> Site:
        return self.init_site_database(site_name, with_demo_data=(site_name == DEFAULT_SITE))

    def create_site(
        self,
        site_name: str,
        *,
        line_name: str = "",
        system_type: str = "",
        network_domain: str = "default",
        display_name: str = "",
        remark: str = "",
        mesh_analysis_params: dict[str, object] | None = None,
    ) -> Site:
        site_name = self.validate_site_name(site_name)
        if site_name in self.list_sites():
            raise ValueError(f"Site already exists: {site_name}")
        site = self.init_site_database(site_name, with_demo_data=False)
        self.save_site_metadata(
            site_name,
            {
                "display_name": display_name or site_name,
                "line_name": line_name,
                "system_type": system_type,
                "network_domain": network_domain or "default",
                "remark": remark,
                "mesh_analysis_params": mesh_analysis_params,
            },
        )
        self.switch_site(site_name)
        return self.ensure_site(site_name)

    def list_sites(self) -> list[str]:
        self.paths.sites_dir.mkdir(parents=True, exist_ok=True)
        sites = [path.name for path in self.paths.sites_dir.iterdir() if path.is_dir()]
        return sorted(sites, key=lambda name: (name != DEFAULT_SITE, name.casefold()))

    def switch_site(self, site_name: str) -> Site:
        site_name = self.validate_site_name(site_name)
        if site_name == DEFAULT_SITE:
            self.ensure_demo_site()
        if site_name not in self.list_sites():
            raise ValueError(f"Site does not exist: {site_name}")
        site = self.init_site_database(site_name, with_demo_data=(site_name == DEFAULT_SITE))
        config = self._load_config()
        config["current_site"] = site_name
        recent_sites = [site_name]
        for name in config.get("recent_sites", []):
            if isinstance(name, str) and name != site_name and (self.paths.site_dir(name)).is_dir():
                recent_sites.append(name)
        config["recent_sites"] = recent_sites[:10]
        self._save_config(config)
        return site

    def get_current_site(self) -> str:
        self.ensure_demo_site()
        config = self._load_config()
        current_site = config.get("current_site", DEFAULT_SITE)
        if not isinstance(current_site, str) or current_site not in self.list_sites():
            current_site = DEFAULT_SITE
            config["current_site"] = DEFAULT_SITE
            config["recent_sites"] = self._normalize_recent_sites(config.get("recent_sites", []), DEFAULT_SITE)
            self._save_config(config)
        return current_site

    def validate_site_name(self, site_name: str) -> str:
        name = site_name.strip()
        if not name:
            raise ValueError("Site name cannot be empty")
        if name in {".", ".."} or any(char in INVALID_SITE_NAME_CHARS for char in name):
            raise ValueError("Site name contains invalid path characters")
        if any(ord(char) < 32 for char in name):
            raise ValueError("Site name contains invalid control characters")
        if Path(name).name != name:
            raise ValueError("Site name cannot contain path separators")
        return name

    def ensure_site_dirs(self, site_name: str) -> Path:
        return self.paths.ensure_site_dirs(self.validate_site_name(site_name))

    def init_site_database(self, site_name: str, with_demo_data: bool = False) -> Site:
        site_name = self.validate_site_name(site_name)
        root_path = self.ensure_site_dirs(site_name)
        database = Database(self.paths.site_db_path(site_name))
        first_database = not database.exists()
        database.initialize()
        if first_database and with_demo_data:
            insert_demo_devices(DeviceRepository(database))
        DeviceGroupRepository(database, site_name).ensure_default_groups()
        metadata = self.load_site_metadata(site_name)
        return Site(
            name=site_name,
            root_path=root_path,
            database_path=database.path,
            display_name=str(metadata.get("display_name") or site_name),
            line_name=str(metadata.get("line_name") or ""),
            system_type=str(metadata.get("system_type") or ""),
            network_domain=str(metadata.get("network_domain") or "default"),
            remark=str(metadata.get("remark") or ""),
            schema_version=int(metadata.get("schema_version") or 1),
        )

    def load_site_metadata(self, site_name: str) -> dict[str, object]:
        path = self.paths.site_dir(self.validate_site_name(site_name)) / "site_meta.json"
        if not path.exists():
            return {
                "display_name": site_name,
                "line_name": "",
                "system_type": "",
                "network_domain": "default",
                "remark": "",
                "schema_version": 1,
            }
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("display_name", site_name)
        data.setdefault("line_name", "")
        data.setdefault("system_type", "")
        data.setdefault("network_domain", "default")
        data.setdefault("remark", "")
        data.setdefault("schema_version", 1)
        return data

    def save_site_metadata(self, site_name: str, metadata: dict[str, object]) -> None:
        site_name = self.validate_site_name(site_name)
        root_path = self.ensure_site_dirs(site_name)
        current = self.load_site_metadata(site_name)
        now = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        payload = {
            **current,
            **{key: value for key, value in metadata.items() if value is not None},
            "display_name": str(metadata.get("display_name") or current.get("display_name") or site_name),
            "updated_at": now,
            "schema_version": 1,
        }
        payload.setdefault("created_at", now)
        with (root_path / "site_meta.json").open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

    def ensure_app_config(self) -> dict[str, object]:
        self.ensure_demo_site()
        config = self._load_config()
        current_site = config.get("current_site", DEFAULT_SITE)
        if not isinstance(current_site, str) or not (self.paths.site_dir(current_site)).is_dir():
            current_site = DEFAULT_SITE
        normalized = {
            "current_site": current_site,
            "recent_sites": self._normalize_recent_sites(config.get("recent_sites", []), current_site),
        }
        self._save_config(normalized)
        return normalized

    def _load_config(self) -> dict[str, object]:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.paths.app_config_path.exists():
            config = {"current_site": DEFAULT_SITE, "recent_sites": [DEFAULT_SITE]}
            self._save_config(config)
            return config
        try:
            with self.paths.app_config_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _save_config(self, config: dict[str, object]) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        with self.paths.app_config_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)

    def _normalize_recent_sites(self, value: object, current_site: str) -> list[str]:
        recent_sites = [current_site]
        if isinstance(value, list):
            for name in value:
                if isinstance(name, str) and name != current_site and (self.paths.site_dir(name)).is_dir():
                    recent_sites.append(name)
        if DEFAULT_SITE not in recent_sites and self.paths.site_dir(DEFAULT_SITE).is_dir():
            recent_sites.append(DEFAULT_SITE)
        return recent_sites[:10]
