"""Shared root-level authority for storage retirement and migration tools.

SiteRegistry proves site identity, but it is not sufficient authority for a
whole-data-root operation.  This module keeps the root, manifest, site set and
operation capability separate so maintenance scripts can fail closed before
creating staging directories or retirement destinations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from netconsole.core.runtime_environment import data_environment
from netconsole.core.runtime_mode import DataEnvironmentInfo


STORAGE_RETIREMENT_AUTHORIZED = "STORAGE_RETIREMENT_AUTHORIZED"
DATA_ROOT_MIGRATION_AUTHORIZED = "DATA_ROOT_MIGRATION_AUTHORIZED"
LEGACY_RUNTIME_MIGRATION_AUTHORIZED = "LEGACY_RUNTIME_MIGRATION_AUTHORIZED"


class StorageAuthorityError(RuntimeError):
    """A storage root, target or operation capability failed closed."""


@dataclass(frozen=True)
class StorageRootAuthority:
    root: Path
    environment: DataEnvironmentInfo
    installation_id: str
    manifest_sha256: str
    registry_sha256: str
    site_inventory_digest: str
    canonical_site_ids: tuple[str, ...]

    @property
    def is_production(self) -> bool:
        return self.environment.is_production

    @property
    def identity(self) -> str:
        return _digest(
            {
                "root": str(self.root),
                "installation_id": self.installation_id,
                "manifest_sha256": self.manifest_sha256,
                "registry_sha256": self.registry_sha256,
                "site_inventory_digest": self.site_inventory_digest,
                "canonical_site_ids": list(self.canonical_site_ids),
                "environment": self.environment.mode.value,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "environment": self.environment.mode.value,
            "installation_id": self.installation_id,
            "manifest_sha256": self.manifest_sha256,
            "registry_sha256": self.registry_sha256,
            "site_inventory_digest": self.site_inventory_digest,
            "canonical_site_ids": list(self.canonical_site_ids),
            "identity": self.identity,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((payload + "\n").encode("utf-8")).hexdigest()


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(int(getattr(path.lstat(), "st_file_attributes", 0) or 0) & 0x400)
    except (FileNotFoundError, OSError):
        return False


def _has_reparse_ancestor(path: Path, stop: Path) -> bool:
    current = path
    stop = stop.resolve()
    while True:
        if _is_reparse(current):
            return True
        if current == stop:
            return False
        if current.parent == current:
            return True
        current = current.parent


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise StorageAuthorityError(f"{label} is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise StorageAuthorityError(f"{label} must be a JSON object")
    return value


def _registry_snapshot(root: Path) -> tuple[str, str, tuple[str, ...]]:
    registry_path = root / "config" / "site_registry.json"
    if not registry_path.is_file() or _is_reparse(registry_path):
        raise StorageAuthorityError("PRODUCTION_SITE_REGISTRY_UNAVAILABLE")
    payload = _read_object(registry_path, "site_registry.json")
    raw_sites = payload.get("sites")
    if not isinstance(raw_sites, list) or not raw_sites:
        raise StorageAuthorityError("PRODUCTION_SITE_REGISTRY_EMPTY")
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    sites_root = (root / "sites").resolve()
    if _has_reparse_ancestor(root / "sites", root):
        raise StorageAuthorityError("PRODUCTION_SITE_REGISTRY_REPARSE")
    for item in raw_sites:
        if not isinstance(item, Mapping):
            raise StorageAuthorityError("PRODUCTION_SITE_REGISTRY_INVALID")
        site_id = str(item.get("site_id") or "").strip()
        relative = str(item.get("relative_path") or "").replace("\\", "/")
        if not site_id or site_id in seen or not relative or Path(relative).is_absolute():
            raise StorageAuthorityError("PRODUCTION_SITE_REGISTRY_INVALID")
        relative_path = Path(relative)
        if ".." in relative_path.parts:
            raise StorageAuthorityError("PRODUCTION_SITE_REGISTRY_PATH_ESCAPE")
        site_root = (root / relative_path).resolve(strict=False)
        if (
            site_root.parent != sites_root
            or not site_root.is_dir()
            or _has_reparse_ancestor(root / relative_path, root)
        ):
            raise StorageAuthorityError("PRODUCTION_SITE_REGISTRY_IDENTITY_MISMATCH")
        seen.add(site_id)
        records.append({"site_id": site_id, "relative_path": relative_path.as_posix()})
    records.sort(key=lambda item: item["site_id"].casefold())
    inventory = _digest({"sites": records})
    return _sha256(registry_path), inventory, tuple(item["site_id"] for item in records)


def resolve_storage_root_authority(data_root: str | Path) -> StorageRootAuthority:
    root = Path(data_root).expanduser().resolve(strict=True)
    if not root.is_dir() or _is_reparse(root):
        raise StorageAuthorityError("STORAGE_ROOT_INVALID")
    try:
        environment = data_environment(root)
    except RuntimeError as exc:
        raise StorageAuthorityError("STORAGE_ROOT_ENVIRONMENT_UNAVAILABLE") from exc
    manifest_path = root / "config" / "storage-manifest.json"
    registry_path = root / "config" / "site_registry.json"
    if environment.is_production:
        if not manifest_path.is_file() or _is_reparse(manifest_path):
            raise StorageAuthorityError("PRODUCTION_STORAGE_MANIFEST_UNAVAILABLE")
        manifest = _read_object(manifest_path, "storage-manifest.json")
        if Path(str(manifest.get("data_root") or "")).expanduser().resolve() != root:
            raise StorageAuthorityError("PRODUCTION_STORAGE_MANIFEST_ROOT_MISMATCH")
        installation_id = str(manifest.get("installation_id") or "").strip()
        if not installation_id:
            raise StorageAuthorityError("PRODUCTION_STORAGE_INSTALLATION_ID_MISSING")
        registry_sha, inventory, site_ids = _registry_snapshot(root)
        return StorageRootAuthority(
            root=root,
            environment=environment,
            installation_id=installation_id,
            manifest_sha256=_sha256(manifest_path),
            registry_sha256=registry_sha,
            site_inventory_digest=inventory,
            canonical_site_ids=site_ids,
        )
    # Development/test roots remain usable without a persistent manifest.  If
    # one exists, include it in the plan identity but never treat it as a
    # Production authority by path name alone.
    manifest_sha = _sha256(manifest_path) if manifest_path.is_file() and not _is_reparse(manifest_path) else ""
    registry_sha = ""
    inventory = ""
    site_ids: tuple[str, ...] = ()
    if registry_path.is_file() and not _is_reparse(registry_path):
        try:
            registry_sha, inventory, site_ids = _registry_snapshot(root)
        except StorageAuthorityError:
            registry_sha = _sha256(registry_path)
    return StorageRootAuthority(root, environment, "", manifest_sha, registry_sha, inventory, site_ids)


def require_storage_operation(
    authority: StorageRootAuthority,
    operation: str,
    *,
    allow_production_write: bool = False,
    authorization_token: str = "",
) -> None:
    """Require operator intent plus an operation-specific capability in Production."""

    if not authority.is_production:
        return
    expected = {
        "STORAGE_RETIREMENT": STORAGE_RETIREMENT_AUTHORIZED,
        "DATA_ROOT_MIGRATION": DATA_ROOT_MIGRATION_AUTHORIZED,
        "LEGACY_RUNTIME_MIGRATION": LEGACY_RUNTIME_MIGRATION_AUTHORIZED,
    }.get(str(operation))
    if expected is None:
        raise StorageAuthorityError("OPERATION_NOT_AUTHORIZED")
    if not allow_production_write:
        raise StorageAuthorityError("PRODUCTION_OPERATOR_INTENT_REQUIRED")
    if str(authorization_token or "") != expected:
        raise StorageAuthorityError("OPERATION_NOT_AUTHORIZED")


def assert_safe_external_target(
    source_root: str | Path,
    target_root: str | Path,
    *,
    require_explicit: bool = True,
) -> Path:
    source = Path(source_root).expanduser().resolve(strict=True)
    target_raw = Path(target_root).expanduser()
    if require_explicit and not str(target_root).strip():
        raise StorageAuthorityError("TARGET_ROOT_EXPLICIT_REQUIRED")
    if not target_raw.is_absolute():
        raise StorageAuthorityError("TARGET_ROOT_MUST_BE_ABSOLUTE")
    target = target_raw.resolve(strict=False)
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise StorageAuthorityError("SOURCE_TARGET_OVERLAP")
    if _has_reparse_ancestor(target.parent, Path(target.anchor)):
        raise StorageAuthorityError("TARGET_REPARSE_OR_JUNCTION")
    if target.exists():
        if _is_reparse(target):
            raise StorageAuthorityError("TARGET_REPARSE_OR_JUNCTION")
        if any((target / name).exists() for name in ("runtime_mode.json", "config/storage-manifest.json")):
            raise StorageAuthorityError("TARGET_ACTIVE_NETCONSOLE_ROOT")
    return target


__all__ = [
    "DATA_ROOT_MIGRATION_AUTHORIZED",
    "LEGACY_RUNTIME_MIGRATION_AUTHORIZED",
    "STORAGE_RETIREMENT_AUTHORIZED",
    "StorageAuthorityError",
    "StorageRootAuthority",
    "assert_safe_external_target",
    "require_storage_operation",
    "resolve_storage_root_authority",
]
