"""Pure site identity and metadata helpers shared by data gateways."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from netconsole.core.paths import PathResolver


DEFAULT_SITE = "demo"
INVALID_SITE_NAME_CHARS = set('<>:"/\\|?*')


def validate_site_name(site_name: str) -> str:
    name = str(site_name or "").strip()
    if not name:
        raise ValueError("Site name cannot be empty")
    if name in {".", ".."} or any(char in INVALID_SITE_NAME_CHARS for char in name):
        raise ValueError("Site name contains invalid path characters")
    if any(ord(char) < 32 for char in name):
        raise ValueError("Site name contains invalid control characters")
    if Path(name).name != name:
        raise ValueError("Site name cannot contain path separators")
    return name


def load_site_metadata(paths: PathResolver, site_name: str) -> dict[str, object]:
    site_name = validate_site_name(site_name)
    path = paths.site_dir(site_name) / "site_meta.json"
    if not path.exists():
        return _default_site_metadata(site_name)
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


def save_site_metadata(paths: PathResolver, site_name: str, metadata: dict[str, object]) -> None:
    site_name = validate_site_name(site_name)
    root_path = paths.ensure_site_dirs(site_name)
    current = load_site_metadata(paths, site_name)
    from datetime import datetime

    now = datetime.now().isoformat(timespec="seconds")
    payload = {
        **current,
        **{key: value for key, value in metadata.items() if value is not None},
        "display_name": str(metadata.get("display_name") or current.get("display_name") or site_name),
        "updated_at": now,
        "schema_version": 1,
    }
    payload.setdefault("created_at", now)
    temporary = root_path / f".site_meta.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, root_path / "site_meta.json")
    finally:
        temporary.unlink(missing_ok=True)


def current_site_name(paths: PathResolver) -> str:
    config_path = paths.app_config_path
    if not config_path.exists() and paths.legacy_app_config_path.is_file():
        config_path = paths.legacy_app_config_path
    try:
        data = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    config = data if isinstance(data, dict) else {}
    existing = sorted(path.name for path in paths.sites_dir.glob("*") if path.is_dir())
    current = config.get("current_site")
    if isinstance(current, str) and current in existing:
        return current
    if len(existing) == 1:
        return existing[0]
    if not existing:
        return DEFAULT_SITE
    raise RuntimeError("当前数据根包含多个局点，但没有有效的当前局点配置")


def _default_site_metadata(site_name: str) -> dict[str, object]:
    return {
        "display_name": site_name,
        "line_name": "",
        "system_type": "",
        "network_domain": "default",
        "remark": "",
        "schema_version": 1,
    }


__all__ = [
    "DEFAULT_SITE",
    "INVALID_SITE_NAME_CHARS",
    "current_site_name",
    "load_site_metadata",
    "save_site_metadata",
    "validate_site_name",
]
