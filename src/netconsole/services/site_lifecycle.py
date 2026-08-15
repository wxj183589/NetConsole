from __future__ import annotations

import gc
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.sites import DEFAULT_SITE, SiteManager
from netconsole.services.site_storage import SiteRecord, SiteRegistryRepository, SiteStorageError, storage_lock


AUDIT_SCHEMA_VERSION = 1
DEMO_SEED_VERSION = "2026.07.21.1"
DEMO_MAX_BYTES = 50 * 1024 * 1024
_SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_TRANSIENT_SUFFIXES = {"-wal", "-shm", "-journal"}
_DEMO_MANIFEST_NAME = "demo_seed_manifest.json"
_DEFAULT_TABLES = {
    "schema_metadata",
    "task_schema_meta",
    "task_result_storage_rollout",
    "online_mr_task_session_schema",
    "agent_schema_meta",
    "device_groups",
    "ap_identity_entities",
    "ap_identity_mac_aliases",
    "ap_identity_h3c_prefixes",
    "ap_identity_conflicts",
    "ap_identity_index_state",
    "ap_identity_source_state",
}
_DEFAULT_DEVICE_GROUP_NAMES = {"COCC", "BOCC", "车站", "车载-MR", "车载-3SW"}
_REFERENCE_TEXT_SUFFIXES = {".json", ".jsonl", ".toml", ".yaml", ".yml"}
_KNOWN_DEMO_DEVICE_NAMES = frozenset(
    {
        "Huawei SW-SSH-Only",
        "Ruijie SW-Telnet-Password",
        "H3C SW-Same-SSH-Telnet",
        "H3C AC-Different-SSH-Telnet",
        "H3C FW-SSH-SNMPv2c",
        "AC",
        "SW01",
        "SW02",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_expired(value: str) -> bool:
    try:
        return datetime.fromisoformat(value) <= datetime.now(timezone.utc)
    except ValueError:
        return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _file_manifest(root: Path, *, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = exclude or set()
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.is_symlink() or path.name in excluded:
            continue
        entries.append(
            {
                "relative_path": _relative(root, path),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return entries


def _manifest_digest(entries: list[dict[str, Any]]) -> str:
    value = json.dumps(entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _verify_file_manifest(root: Path, expected: list[dict[str, Any]]) -> bool:
    if not root.is_dir() or root.is_symlink():
        return False
    if any(path.is_symlink() for path in root.rglob("*")):
        return False
    actual = _file_manifest(root)
    def normalized(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            [
                {
                    "relative_path": str(item.get("relative_path") or ""),
                    "size": int(item.get("size") or 0),
                    "sha256": str(item.get("sha256") or ""),
                }
                for item in items
            ],
            key=lambda item: item["relative_path"].casefold(),
        )
    return normalized(actual) == normalized(expected)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _bootstrap_path(paths: PathResolver) -> Path:
    return paths.electron_dir / "user-data" / "bootstrap.json"


def _database_summary(path: Path) -> tuple[dict[str, int], str, int]:
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        return {}, f"error:{type(exc).__name__}", 0
    try:
        quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        tables = [str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts: dict[str, int] = {}
        business_rows = 0
        for table in tables:
            safe = table.replace('"', '""')
            try:
                count = int(connection.execute(f'SELECT COUNT(*) FROM "{safe}"').fetchone()[0])
            except sqlite3.Error:
                count = 0
            counts[table] = count
            if table not in _DEFAULT_TABLES:
                business_rows += count
        return counts, quick, business_rows
    finally:
        connection.close()


def _has_custom_device_groups(path: Path) -> bool:
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return True
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_groups'"
        ).fetchone()
        if table is None:
            return False
        names = {str(row[0]) for row in connection.execute("SELECT name FROM device_groups")}
        return bool(names - _DEFAULT_DEVICE_GROUP_NAMES)
    except sqlite3.Error:
        return True
    finally:
        connection.close()


def _is_sqlite_sidecar(path: Path) -> bool:
    return path.name.casefold().endswith(tuple(_TRANSIENT_SUFFIXES))


def _finalize_sqlite_files(root: Path) -> None:
    gc.collect()
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix.casefold() not in _SQLITE_SUFFIXES:
            continue
        connection = sqlite3.connect(path, timeout=5)
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
    gc.collect()


def _registry_records(paths: PathResolver) -> list[SiteRecord]:
    repository = SiteRegistryRepository(paths)
    raw = repository._load()  # read-only access; list() may persist discovery
    records: list[SiteRecord] = []
    for item in raw.get("sites", []):
        if not isinstance(item, dict):
            continue
        try:
            site_id = str(item.get("site_id") or "")
            root = repository._resolve_root(str(item.get("relative_path") or f"sites/{site_id}"))
            if not root.is_dir():
                continue
            records.append(
                SiteRecord(
                    site_id=site_id,
                    display_name=str(item.get("display_name") or site_id),
                    root_path=root,
                    created_at=str(item.get("created_at") or ""),
                    updated_at=str(item.get("updated_at") or ""),
                    remark=str(item.get("remark") or ""),
                    line_name=str(item.get("line_name") or "").strip() or None,
                    project_type=str(item.get("project_type") or "").strip()
                    or None,
                )
            )
        except (SiteStorageError, ValueError):
            continue
    return records


def _legacy_site_id(directory_name: str, used: set[str]) -> str:
    candidate = directory_name.casefold()
    if candidate and candidate not in used and all(char.isalnum() or char in "_-" for char in candidate):
        return candidate
    digest = hashlib.sha256(directory_name.encode("utf-8")).hexdigest()
    for length in (12, 16, 24, 32, 40, 64):
        candidate = f"legacy-{digest[:length]}"
        if candidate not in used:
            return candidate
    raise SiteStorageError("SITE_REGISTRY_CONFLICT", "历史局点标识发生冲突")


class SiteAuditService:
    """只读审计当前数据根；输出的 manifest 可作为后续清理的不可变输入。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def site_exists(self, site_ref: str) -> bool:
        wanted = str(site_ref or "").strip().casefold()
        if not wanted:
            return False
        if any(
            wanted in {record.site_id.casefold(), record.root_path.name.casefold()}
            for record in _registry_records(self.paths)
        ):
            return True
        return any(
            path.is_dir() and not path.is_symlink() and path.name.casefold() == wanted
            for path in self.paths.sites_dir.glob("*")
        )

    def audit_all(
        self,
        *,
        site_id: str | None = None,
        output: Path | None = None,
        check_cancel: Callable[[], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        registry = _registry_records(self.paths)
        by_path = {record.root_path.resolve(): record for record in registry}
        by_id = {record.site_id: record for record in registry}
        used = set(by_id)
        app_config = _read_json(self.paths.app_config_path)
        current_dir = str(app_config.get("current_site") or "")
        bootstrap = _read_json(_bootstrap_path(self.paths))
        bootstrap_active = str(bootstrap.get("active_site_id") or "")
        directories = [path for path in sorted(self.paths.sites_dir.glob("*"), key=lambda item: item.name.casefold()) if path.is_dir() and not path.is_symlink()]
        selected = []
        for directory in directories:
            record = by_path.get(directory.resolve())
            current_id = record.site_id if record else _legacy_site_id(directory.name, used)
            if site_id and site_id not in {current_id, directory.name}:
                continue
            selected.append((directory, record, current_id))
        results: list[dict[str, Any]] = []
        for index, (directory, record, resolved_site_id) in enumerate(selected, start=1):
            if check_cancel:
                check_cancel()
            results.append(
                self._audit_one(
                    directory,
                    record,
                    resolved_site_id,
                    app_config=app_config,
                    current_dir=current_dir,
                    bootstrap=bootstrap,
                    bootstrap_active=bootstrap_active,
                    registry=registry,
                )
            )
            if progress:
                progress(index, len(selected), f"已审计局点 {directory.name}")
        manifest_id = f"site-audit-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:8]}"
        manifest_path = self.paths.migrations_dir / "site-audits" / f"{manifest_id}.json"
        payload: dict[str, Any] = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "manifest_path": _relative(self.paths.data_root, manifest_path),
            "generated_at": _now(),
            "data_root": str(self.paths.data_root.resolve()),
            "site_count": len(results),
            "sites": results,
        }
        _atomic_json(manifest_path, payload)
        latest = self.paths.migrations_dir / "site-audits" / "latest.json"
        _atomic_json(latest, payload)
        if output is not None and output.resolve() != manifest_path.resolve():
            _atomic_json(output, payload)
        return payload

    def latest(self, site_id: str | None = None) -> dict[str, Any] | None:
        path = self.paths.migrations_dir / "site-audits" / "latest.json"
        if not path.is_file():
            return None
        payload = _read_json(path)
        if site_id is None:
            return payload
        return next((item for item in payload.get("sites", []) if item.get("site_id") == site_id), None)

    def _audit_one(
        self,
        directory: Path,
        record: SiteRecord | None,
        site_id: str,
        *,
        app_config: dict[str, Any],
        current_dir: str,
        bootstrap: dict[str, Any],
        bootstrap_active: str,
        registry: list[SiteRecord],
    ) -> dict[str, Any]:
        metadata = _read_json(directory / "site_meta.json")
        unsafe_entries = [path for path in directory.rglob("*") if path.is_symlink()]
        files = [path for path in directory.rglob("*") if path.is_file() and not path.is_symlink()]
        database_files: list[dict[str, Any]] = []
        table_counts: dict[str, dict[str, int]] = {}
        business_rows = 0
        for path in files:
            if path.suffix.casefold() not in _SQLITE_SUFFIXES:
                continue
            counts, quick, rows = _database_summary(path)
            relative = _relative(directory, path)
            database_files.append({"relative_path": relative, "size": path.stat().st_size, "quick_check": quick, "table_counts": counts})
            table_counts[relative] = counts
            business_rows += rows
            if _has_custom_device_groups(path):
                business_rows += 1
        file_manifest = _file_manifest(directory)
        raw_files = [path for path in files if any(part.casefold() in {"raw", "raw_logs", "logs"} for part in path.relative_to(directory).parts)]
        parsed_files = [path for path in files if "parsed" in {part.casefold() for part in path.relative_to(directory).parts} and path.suffix.casefold() in _SQLITE_SUFFIXES]
        report_files = [path for path in files if any(part.casefold() in {"reports", "report", "outputs", "artifacts"} for part in path.relative_to(directory).parts) and path.suffix.casefold() not in _TRANSIENT_SUFFIXES]
        task_count = sum(counts.get("task_snapshots", 0) for counts in table_counts.values())
        session_count = sum(counts.get("online_mr_task_sessions", 0) + counts.get("vehicle_mr_online_sessions", 0) for counts in table_counts.values())
        mesh_source_count = sum(counts.get("source_files", 0) for counts in table_counts.values()) + len([path for path in raw_files if "mesh" in path.name.casefold()])
        is_demo = site_id == DEFAULT_SITE or directory.name == DEFAULT_SITE
        managed_demo = bool(metadata.get("managed_demo") is True)
        known_demo = is_demo and self._looks_like_legacy_demo(table_counts, directory)
        current = directory.name.casefold() == current_dir.casefold() or site_id == bootstrap_active
        referenced: list[str] = []
        if record:
            referenced.append("registry")
        if directory.name in [str(item) for item in app_config.get("recent_sites", []) if isinstance(item, str)]:
            referenced.append("app_config.recent_sites")
        if current:
            referenced.append("app_config.current_site")
        is_bootstrap = str(bootstrap.get("active_site_id") or "") in {site_id, directory.name}
        if is_bootstrap:
            referenced.append("bootstrap.active_site_id")
        duplicate_candidates = [item.site_id for item in registry if item.site_id == directory.name and item.root_path.resolve() != directory.resolve()]
        if current:
            classification = "active_site"
        elif managed_demo:
            classification = "managed_demo"
        elif is_demo and known_demo:
            classification = "legacy_demo"
        elif not business_rows and not raw_files and not parsed_files and not report_files and site_id.startswith("legacy-"):
            classification = "empty_shell"
        elif site_id.startswith("legacy-") and duplicate_candidates:
            classification = "legacy_alias"
        elif site_id.startswith("legacy-"):
            classification = "legacy_valid"
        else:
            classification = "normal_site"
        unknown_files = [
            path
            for path in files
            if _relative(directory, path) != "site_meta.json"
            and path.suffix.casefold() not in _SQLITE_SUFFIXES
            and not _is_sqlite_sidecar(path)
        ]
        damaged_databases = [item for item in database_files if item.get("quick_check") != "ok"]
        unique_business_data = bool(
            business_rows
            or raw_files
            or parsed_files
            or report_files
            or unsafe_entries
            or unknown_files
            or damaged_databases
        )
        external_references = []
        if not current and not is_bootstrap and not unique_business_data:
            external_references = self._external_references(directory, site_id, registry)
        referenced.extend(external_references)
        can_delete = not current and not is_bootstrap and not unique_business_data and not external_references
        demo_pristine = managed_demo and self._managed_demo_pristine(directory, file_manifest)
        raw_bytes = sum(int(path.stat().st_size) for path in raw_files)
        legacy_demo_replaceable = bool(
            is_demo
            and known_demo
            and not session_count
            and not report_files
            and raw_bytes <= 1 * 1024 * 1024
            and not unsafe_entries
            and not unknown_files
            and not damaged_databases
        )
        if classification == "legacy_demo":
            recommended = "backup_then_rebuild"
        elif can_delete:
            recommended = "safe_delete_to_recycle"
        else:
            recommended = "keep_and_review"
        return {
            "display_name": record.display_name if record else str(metadata.get("display_name") or directory.name),
            "site_id": site_id,
            "physical_path": str(directory.resolve()),
            "total_size": sum(item["size"] for item in file_manifest),
            "file_count": len(files),
            "directory_count": len([path for path in directory.rglob("*") if path.is_dir()]),
            "latest_modified_at": max((datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds") for path in files), default=""),
            "is_current": current,
            "is_registered": record is not None,
            "is_referenced_by_bootstrap": is_bootstrap,
            "is_demo": is_demo,
            "managed_demo": managed_demo,
            "demo_seed_version": str(metadata.get("seed_version") or ""),
            "migration_source": str(metadata.get("migration_source") or ""),
            "migration_status": str(metadata.get("migration_status") or ("managed" if managed_demo else "legacy_unmarked")),
            "database_files": database_files,
            "database_table_counts": table_counts,
            "raw_log_count": len(raw_files),
            "parsed_database_count": len(parsed_files),
            "report_count": len(report_files),
            "artifact_count": len([path for path in files if "artifact" in path.name.casefold()]),
            "task_count": task_count,
            "online_mr_session_count": session_count,
            "mesh_source_count": mesh_source_count,
            "unique_business_data": unique_business_data,
            "duplicate_candidates": duplicate_candidates,
            "referenced_records": referenced,
            "classification": classification,
            "recommended_action": recommended,
            "can_delete": can_delete,
            "safe_to_replace": bool(is_demo and (demo_pristine or legacy_demo_replaceable) and not current and not is_bootstrap),
            "demo_pristine": demo_pristine,
            "legacy_demo_replaceable": legacy_demo_replaceable,
            "unsafe_entry_count": len(unsafe_entries),
            "unknown_file_count": len(unknown_files),
            "file_manifest": file_manifest,
        }

    def _external_references(self, directory: Path, site_id: str, registry: list[SiteRecord]) -> list[str]:
        tokens = {site_id}
        directory_name = directory.name
        if not any(item.site_id == directory_name and item.root_path.resolve() != directory.resolve() for item in registry):
            tokens.add(directory_name)
        references: list[str] = []
        for site in registry:
            if site.root_path.resolve() == directory.resolve():
                continue
            for database in site.root_path.rglob("*"):
                if database.is_symlink() or not database.is_file() or database.suffix.casefold() not in _SQLITE_SUFFIXES:
                    continue
                references.extend(self._database_references(database, tokens))
                if references:
                    return references[:20]
        excluded_roots = {
            directory.resolve(),
            self.paths.archive_dir.resolve(),
            self.paths.migrations_dir.resolve(),
            self.paths.temp_dir.resolve(),
        }
        excluded_files = {SiteRegistryRepository(self.paths).path.resolve(), self.paths.app_config_path.resolve()}
        for path in self.paths.data_dir.rglob("*"):
            if path.is_symlink() or not path.is_file() or path.suffix.casefold() not in _REFERENCE_TEXT_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in excluded_files:
                continue
            if any(resolved == root or resolved.is_relative_to(root) for root in excluded_roots):
                continue
            try:
                if path.stat().st_size > 5 * 1024 * 1024:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                references.append(f"text-unreadable:{_relative(self.paths.data_root, path)}")
                return references
            if any(token in text for token in tokens):
                references.append(f"text:{_relative(self.paths.data_root, path)}")
                return references
        return references

    def _database_references(self, database: Path, tokens: set[str]) -> list[str]:
        if not tokens:
            return []
        try:
            connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=3)
        except sqlite3.Error:
            return [f"sqlite-unreadable:{_relative(self.paths.data_root, database)}"]
        try:
            matches: list[str] = []
            tables = [str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                safe_table = table.replace('"', '""')
                try:
                    columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{safe_table}")')]
                except sqlite3.Error:
                    continue
                for column in columns:
                    safe_column = column.replace('"', '""')
                    placeholders = ",".join("?" for _ in tokens)
                    try:
                        row = connection.execute(
                            f'SELECT 1 FROM "{safe_table}" WHERE typeof("{safe_column}") = \'text\' '
                            f'AND "{safe_column}" IN ({placeholders}) LIMIT 1',
                            tuple(tokens),
                        ).fetchone()
                    except sqlite3.Error:
                        continue
                    if row is not None:
                        matches.append(
                            f"sqlite:{_relative(self.paths.data_root, database)}:{table}.{column}"
                        )
                        if len(matches) >= 20:
                            return matches
            return matches
        finally:
            connection.close()

    @staticmethod
    def _managed_demo_pristine(directory: Path, file_manifest: list[dict[str, Any]]) -> bool:
        seed_manifest = _read_json(directory / _DEMO_MANIFEST_NAME)
        expected = seed_manifest.get("files")
        if not isinstance(expected, list):
            return False
        actual = [
            item
            for item in file_manifest
            if item.get("relative_path") != _DEMO_MANIFEST_NAME
            and not str(item.get("relative_path") or "").casefold().endswith(tuple(_TRANSIENT_SUFFIXES))
        ]
        stable_expected = [
            item
            for item in expected
            if isinstance(item, dict)
            and not str(item.get("relative_path") or "").casefold().endswith(tuple(_TRANSIENT_SUFFIXES))
        ]
        expected_digest = _manifest_digest(stable_expected)
        return (
            str(seed_manifest.get("manifest_sha256") or "") == expected_digest
            and expected_digest == _manifest_digest(actual)
            and stable_expected == actual
        )

    @staticmethod
    def _looks_like_legacy_demo(table_counts: dict[str, dict[str, int]], directory: Path) -> bool:
        devices_path = directory / "db" / "devices.db"
        if not devices_path.is_file():
            return False
        try:
            connection = sqlite3.connect(f"{devices_path.resolve().as_uri()}?mode=ro", uri=True)
            names = {str(row[0]) for row in connection.execute("SELECT name FROM devices")}
            connection.close()
        except sqlite3.Error:
            return False
        return bool(names) and names.issubset(_KNOWN_DEMO_DEVICE_NAMES) and len(names) <= len(_KNOWN_DEMO_DEVICE_NAMES)


class SiteCleanupApplicationService:
    """二阶段、可恢复的局点回收：只把目录移入受控回收区，不永久删除。"""

    def __init__(self, paths: PathResolver, sites: object | None = None) -> None:
        self.paths = paths
        self.auditor = SiteAuditService(paths)
        self.registry = SiteRegistryRepository(paths)
        if sites is None:
            from netconsole.services.site_storage import SiteApplicationService

            sites = SiteApplicationService(paths)
        self.sites = sites
        self._recover_incomplete_transactions()

    def trash_site(
        self, site_id: str, *, confirm_display_name: str
    ) -> dict[str, Any]:
        record = self.registry.get(site_id)
        if str(confirm_display_name or "") != record.display_name:
            raise SiteStorageError(
                "SITE_TRASH_CONFIRMATION_MISMATCH", "输入的局点名称与当前名称不一致"
            )
        self._validate_trash_target(record)
        self.sites.ensure_no_active_tasks_anywhere()

        with storage_lock(self.paths, "site-mutation"):
            record = self.registry.get(site_id)
            if str(confirm_display_name or "") != record.display_name:
                raise SiteStorageError(
                    "SITE_TRASH_CONFIRMATION_MISMATCH",
                    "局点名称已变化，请重新确认",
                )
            self._validate_trash_target(record)
            self.sites.ensure_no_active_tasks_anywhere()

            source = record.root_path
            trash_root = self.paths.trash_dir
            if trash_root.exists() and (
                trash_root.is_symlink() or not trash_root.is_dir()
            ):
                raise SiteStorageError(
                    "SITE_TRASH_PATH_INVALID", "局点回收目录必须是普通目录"
                )
            trash_root.mkdir(parents=True, exist_ok=True)
            if trash_root.is_symlink():
                raise SiteStorageError(
                    "SITE_TRASH_PATH_INVALID", "局点回收目录不能是符号链接"
                )
            resolved_trash = trash_root.resolve()
            if resolved_trash.parent != self.paths.data_root.resolve():
                raise SiteStorageError("SITE_TRASH_PATH_INVALID", "局点回收目录越界")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            destination = resolved_trash / f"{record.site_id}-{stamp}"
            if destination.exists():
                raise SiteStorageError("SITE_TRASH_CONFLICT", "局点回收目标已存在")

            registry_existed = self.registry.path.is_file()
            registry_backup = (
                self.registry.path.read_bytes() if registry_existed else b""
            )
            app_existed = self.paths.app_config_path.is_file()
            app_backup = (
                self.paths.app_config_path.read_bytes() if app_existed else b""
            )
            try:
                _finalize_sqlite_files(source)
                os.replace(source, destination)
            except (OSError, sqlite3.Error) as exc:
                app_logger.log_warning(
                    "SITE_TRASH_MOVE_BLOCKED",
                    "site_id="
                    f"{record.site_id} error_type={type(exc).__name__} "
                    f"errno={getattr(exc, 'errno', '')} "
                    f"winerror={getattr(exc, 'winerror', '')}",
                )
                raise SiteStorageError(
                    "SITE_TRASH_LOCKED",
                    "局点目录或数据库正在使用，暂时无法删除",
                    details={
                        "error_type": type(exc).__name__,
                        "errno": getattr(exc, "errno", None),
                        "winerror": getattr(exc, "winerror", None),
                    },
                ) from exc

            try:
                self.registry.unregister(record.site_id, source)
                self._remove_from_recent_sites(source.name)
                _atomic_json(
                    destination / ".netconsole-trash.json",
                    {
                        "schema_version": 1,
                        "site_id": record.site_id,
                        "display_name": record.display_name,
                        "line_name": record.line_name,
                        "project_type": record.project_type,
                        "source_relative_path": _relative(
                            self.paths.data_root, source
                        ),
                        "trashed_at": _now(),
                        "recoverable": True,
                    },
                )
            except Exception as exc:
                try:
                    os.replace(destination, source)
                except OSError as rollback_exc:
                    raise SiteStorageError(
                        "SITE_TRASH_ROLLBACK_FAILED",
                        "局点回收未完成且目录回滚失败，请停止操作并检查诊断日志",
                    ) from rollback_exc
                if registry_existed:
                    _atomic_bytes(self.registry.path, registry_backup)
                else:
                    self.registry.path.unlink(missing_ok=True)
                if app_existed:
                    _atomic_bytes(self.paths.app_config_path, app_backup)
                else:
                    self.paths.app_config_path.unlink(missing_ok=True)
                if isinstance(exc, SiteStorageError):
                    raise
                raise SiteStorageError(
                    "SITE_TRASH_FAILED", "局点回收失败，原目录和 Registry 已恢复"
                ) from exc
        return {
            "site_id": record.site_id,
            "display_name": record.display_name,
            "trash_path": _relative(self.paths.data_root, destination),
            "recoverable": True,
        }

    def _validate_trash_target(self, record: SiteRecord) -> None:
        current = self.sites.active_site_id()
        if current in {record.site_id, record.root_path.name}:
            raise SiteStorageError(
                "SITE_TRASH_CURRENT", "当前局点不可删除，请先切换到其他局点。"
            )
        if record.site_id == DEFAULT_SITE:
            raise SiteStorageError(
                "SITE_TRASH_DEMO", "内置 Demo 局点请使用“重建 Demo”"
            )
        audit = self.auditor.latest(record.site_id)
        if audit and str(audit.get("classification") or "") == "empty_shell":
            raise SiteStorageError(
                "SITE_TRASH_EMPTY_SHELL", "空壳局点请使用“清理空壳局点”"
            )
        source = record.root_path
        sites_root = self.paths.sites_dir.resolve()
        if (
            not source.is_dir()
            or source.is_symlink()
            or source.parent != sites_root
            or source == sites_root
        ):
            raise SiteStorageError(
                "SITE_TRASH_PATH_INVALID", "局点目录不在当前数据根的受控 sites 目录内"
            )
        registered_root = self.registry.registered_root_path(record.site_id)
        if (
            registered_root.is_symlink()
            or registered_root.parent.resolve() != sites_root
            or registered_root.resolve() != source.resolve()
        ):
            raise SiteStorageError(
                "SITE_TRASH_PATH_INVALID", "Registry 局点路径不是受控普通目录"
            )

    def prepare_cleanup(self, site_id: str) -> dict[str, Any]:
        payload, audit_path = self._latest_audit(site_id)
        site = next((item for item in payload["sites"] if item.get("site_id") == site_id), None)
        if site is None:
            raise SiteStorageError("SITE_AUDIT_REQUIRED", "请先完成该局点的只读审计")
        token = uuid.uuid4().hex
        plan = {
            "schema_version": 1,
            "cleanup_token": token,
            "created_at": _now(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(timespec="seconds"),
            "status": "prepared",
            "site_id": site["site_id"],
            "display_name": site["display_name"],
            "classification": site["classification"],
            "unique_files": site["file_manifest"] if site["unique_business_data"] else [],
            "referenced_records": site["referenced_records"],
            "blocking_reasons": self._blocking_reasons(site),
            "recoverable": True,
            "can_delete": bool(site["can_delete"]),
            "audit_manifest": _relative(self.paths.data_root, audit_path),
            "audit_manifest_sha256": _sha256(audit_path),
            "audit_generated_at": str(payload.get("generated_at") or ""),
            "source_relative_path": _relative(self.paths.data_root, Path(str(site["physical_path"]))),
            "file_manifest": site["file_manifest"],
            "file_manifest_sha256": _manifest_digest(site["file_manifest"]),
        }
        path = self.paths.migrations_dir / "site-cleanup" / f"{token}.json"
        _atomic_json(path, plan)
        return {**plan, "manifest_path": _relative(self.paths.data_root, path)}

    def apply_cleanup(self, cleanup_token: str) -> dict[str, Any]:
        plan = self.load_plan(cleanup_token)
        if str(plan.get("status") or "") != "prepared" or _is_expired(str(plan.get("expires_at") or "")):
            raise SiteStorageError("SITE_CLEANUP_TOKEN_INVALID", "清理确认已失效，请重新准备")
        if not bool(plan.get("can_delete")):
            raise SiteStorageError("SITE_CLEANUP_BLOCKED", "局点存在不可清理的数据或引用")
        site_id = str(plan.get("site_id") or "")
        record = next((item for item in _registry_records(self.paths) if item.site_id == site_id), None)
        if record is None:
            raise SiteStorageError("SITE_NOT_FOUND", "局点不存在")
        current = SiteApplicationCurrent(self.paths).site_id()
        if current == site_id or record.root_path.name.casefold() == current.casefold():
            raise SiteStorageError("SITE_CLEANUP_ACTIVE", "当前局点不能清理")
        expected_manifest = plan.get("file_manifest")
        if not isinstance(expected_manifest, list) or not _verify_file_manifest(record.root_path, expected_manifest):
            raise SiteStorageError("SITE_CLEANUP_CHANGED", "局点在确认后发生变化，请重新审计")
        audit_path = (self.paths.data_root / str(plan.get("audit_manifest") or "")).resolve()
        audit_root = (self.paths.migrations_dir / "site-audits").resolve()
        if not audit_path.is_relative_to(audit_root) or not audit_path.is_file():
            raise SiteStorageError("SITE_CLEANUP_TOKEN_INVALID", "审计清单已失效")
        if _sha256(audit_path) != str(plan.get("audit_manifest_sha256") or ""):
            raise SiteStorageError("SITE_CLEANUP_CHANGED", "审计清单已变化，请重新准备")
        if self._has_blocking_runtime_reference(record):
            raise SiteStorageError("SITE_CLEANUP_REFERENCED", "局点当前存在活动引用，不能清理")
        with storage_lock(self.paths, "site-mutation"):
            current_record = next((item for item in _registry_records(self.paths) if item.site_id == site_id), None)
            if current_record is None or current_record.root_path.resolve() != record.root_path.resolve():
                raise SiteStorageError("SITE_CLEANUP_CHANGED", "局点 Registry 已变化，请重新审计")
            if not _verify_file_manifest(record.root_path, expected_manifest):
                raise SiteStorageError("SITE_CLEANUP_CHANGED", "局点在确认后发生变化，请重新审计")
            if self._has_blocking_runtime_reference(record):
                raise SiteStorageError("SITE_CLEANUP_REFERENCED", "局点当前存在活动引用，不能清理")
            plan["status"] = "applying"
            _atomic_json(self.load_plan_path(cleanup_token), plan)
            recycle = self.paths.archive_dir / "site-recycle" / f"{site_id}-{cleanup_token}"
            recycle.mkdir(parents=True, exist_ok=False)
            transaction_path = recycle / "transaction.json"
            _atomic_json(transaction_path, {"schema_version": 1, "cleanup_token": cleanup_token, "stage": "prepared", "created_at": _now()})
            registry_backup = recycle / "registry.json"
            app_backup = recycle / "app.json"
            registry_existed = self.registry.path.is_file()
            app_existed = self.paths.app_config_path.is_file()
            if self.registry.path.is_file():
                shutil.copy2(self.registry.path, registry_backup)
            if self.paths.app_config_path.is_file():
                shutil.copy2(self.paths.app_config_path, app_backup)
            moved = recycle / "site"
            try:
                shutil.move(str(record.root_path), str(moved))
                _atomic_json(transaction_path, {"schema_version": 1, "cleanup_token": cleanup_token, "stage": "site_moved", "updated_at": _now()})
                self.registry.unregister(site_id, record.root_path)
                _atomic_json(transaction_path, {"schema_version": 1, "cleanup_token": cleanup_token, "stage": "registry_updated", "updated_at": _now()})
                self._remove_from_recent_sites(record.root_path.name)
                shutil.copy2(self.load_plan_path(cleanup_token), recycle / "cleanup-manifest.json")
                shutil.copy2(audit_path, recycle / "audit-manifest.json")
                tombstone = {
                    "schema_version": 1,
                    "cleanup_token": cleanup_token,
                    "site_id": site_id,
                    "display_name": record.display_name,
                    "created_at_source": record.created_at,
                    "updated_at_source": record.updated_at,
                    "remark_source": record.remark,
                    "line_name_source": record.line_name,
                    "project_type_source": record.project_type,
                    "source_relative_path": str(plan.get("source_relative_path") or ""),
                    "recycle_path": _relative(self.paths.data_root, moved),
                    "file_count": len(expected_manifest),
                    "file_manifest_sha256": str(plan.get("file_manifest_sha256") or ""),
                    "audit_manifest_sha256": str(plan.get("audit_manifest_sha256") or ""),
                    "registry_backup_sha256": _sha256(registry_backup) if registry_backup.is_file() else "",
                    "app_backup_sha256": _sha256(app_backup) if app_backup.is_file() else "",
                    "created_at": _now(),
                    "restore_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec="seconds"),
                    "recoverable": True,
                }
                _atomic_json(recycle / "tombstone.json", tombstone)
                plan["status"] = "applied"
                plan["applied_at"] = _now()
                _atomic_json(self.load_plan_path(cleanup_token), plan)
                _atomic_json(transaction_path, {"schema_version": 1, "cleanup_token": cleanup_token, "stage": "committed", "updated_at": _now()})
            except Exception as exc:
                if moved.exists() and not record.root_path.exists():
                    shutil.move(str(moved), str(record.root_path))
                if registry_backup.exists():
                    shutil.copy2(registry_backup, self.registry.path)
                elif not registry_existed:
                    self.registry.path.unlink(missing_ok=True)
                if app_backup.exists():
                    shutil.copy2(app_backup, self.paths.app_config_path)
                elif not app_existed:
                    self.paths.app_config_path.unlink(missing_ok=True)
                plan["status"] = "rollback_required"
                _atomic_json(self.load_plan_path(cleanup_token), plan)
                raise SiteStorageError("SITE_CLEANUP_FAILED", "局点回收失败，已恢复原目录") from exc
        return {"cleanup_token": cleanup_token, "site_id": site_id, "recycle_path": _relative(self.paths.data_root, moved), "recoverable": True}

    def restore_cleanup(self, cleanup_token: str) -> dict[str, Any]:
        plan = self.load_plan(cleanup_token)
        if str(plan.get("status") or "") != "applied":
            raise SiteStorageError("SITE_CLEANUP_RESTORE_INVALID", "该回收记录当前不可恢复")
        recycle = (self.paths.archive_dir / "site-recycle" / f"{plan.get('site_id')}-{cleanup_token}").resolve()
        recycle_root = (self.paths.archive_dir / "site-recycle").resolve()
        if not recycle.is_relative_to(recycle_root):
            raise SiteStorageError("SITE_CLEANUP_PATH_INVALID", "回收路径越界")
        tombstone_path = recycle / "tombstone.json"
        tombstone = _read_json(tombstone_path)
        if not tombstone.get("recoverable") or _is_expired(str(tombstone.get("restore_expires_at") or "")):
            raise SiteStorageError("SITE_CLEANUP_RESTORE_EXPIRED", "回收记录已超过恢复期限")
        moved = recycle / "site"
        if not moved.is_dir():
            raise SiteStorageError("SITE_CLEANUP_RESTORE_MISSING", "回收目录不存在")
        source = (self.paths.data_root / str(plan.get("source_relative_path") or "")).resolve()
        sites_root = self.paths.sites_dir.resolve()
        if not source.is_relative_to(sites_root) or source.exists():
            raise SiteStorageError("SITE_CLEANUP_RESTORE_CONFLICT", "恢复目标已存在或路径无效")
        with storage_lock(self.paths, "site-mutation"):
            registry_backup = recycle / "restore-registry.json"
            if self.registry.path.is_file():
                shutil.copy2(self.registry.path, registry_backup)
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(moved), str(source))
                restored = SiteRecord(
                    str(plan["site_id"]),
                    str(plan.get("display_name") or plan["site_id"]),
                    source,
                    str(tombstone.get("created_at_source") or ""),
                    str(tombstone.get("updated_at_source") or ""),
                    str(tombstone.get("remark_source") or ""),
                    str(tombstone.get("line_name_source") or "").strip() or None,
                    str(tombstone.get("project_type_source") or "").strip()
                    or None,
                )
                self.registry.register(restored)
                tombstone.update({"recoverable": False, "restored_at": _now()})
                _atomic_json(tombstone_path, tombstone)
                plan["status"] = "restored"
                plan["restored_at"] = tombstone["restored_at"]
                _atomic_json(self.load_plan_path(cleanup_token), plan)
            except Exception as exc:
                if source.exists() and not moved.exists():
                    shutil.move(str(source), str(moved))
                if registry_backup.is_file():
                    shutil.copy2(registry_backup, self.registry.path)
                raise SiteStorageError("SITE_CLEANUP_RESTORE_FAILED", "局点恢复失败，原回收记录保持不变") from exc
        return {"cleanup_token": cleanup_token, "site_id": str(plan["site_id"]), "restored": True}

    def load_plan(self, cleanup_token: str) -> dict[str, Any]:
        if not cleanup_token or len(cleanup_token) > 128 or not cleanup_token.isalnum():
            raise SiteStorageError("SITE_CLEANUP_TOKEN_INVALID", "清理确认已失效")
        plan = _read_json(self.load_plan_path(cleanup_token))
        if plan.get("cleanup_token") != cleanup_token:
            raise SiteStorageError("SITE_CLEANUP_TOKEN_INVALID", "清理确认已失效")
        return plan

    def load_plan_path(self, cleanup_token: str) -> Path:
        return self.paths.migrations_dir / "site-cleanup" / f"{cleanup_token}.json"

    def _latest_audit(self, site_id: str) -> tuple[dict[str, Any], Path]:
        latest = _read_json(self.paths.migrations_dir / "site-audits" / "latest.json")
        manifest_relative = str(latest.get("manifest_path") or "")
        manifest = (self.paths.data_root / manifest_relative).resolve()
        audit_root = (self.paths.migrations_dir / "site-audits").resolve()
        if not manifest_relative or not manifest.is_relative_to(audit_root) or not manifest.is_file():
            raise SiteStorageError("SITE_AUDIT_REQUIRED", "请先完成该局点的只读审计")
        payload = _read_json(manifest)
        if not any(isinstance(item, dict) and item.get("site_id") == site_id for item in payload.get("sites", [])):
            raise SiteStorageError("SITE_AUDIT_REQUIRED", "请先完成该局点的只读审计")
        return payload, manifest

    def _has_blocking_runtime_reference(self, record: SiteRecord) -> bool:
        current = SiteApplicationCurrent(self.paths).site_id()
        if current in {record.site_id, record.root_path.name}:
            return True
        bootstrap = _read_json(_bootstrap_path(self.paths))
        if str(bootstrap.get("active_site_id") or "") in {record.site_id, record.root_path.name}:
            return True
        registry = _registry_records(self.paths)
        return bool(self.auditor._external_references(record.root_path, record.site_id, registry))

    def _recover_incomplete_transactions(self) -> None:
        root = self.paths.archive_dir / "site-recycle"
        if not root.is_dir():
            return
        with storage_lock(self.paths, "site-mutation"):
            for transaction_path in root.glob("*/transaction.json"):
                transaction = _read_json(transaction_path)
                if transaction.get("stage") in {"committed", "rolled_back"}:
                    continue
                recycle = transaction_path.parent
                tombstone = _read_json(recycle / "tombstone.json")
                token = str(transaction.get("cleanup_token") or "")
                try:
                    plan = self.load_plan(token)
                    source = (self.paths.data_root / str(plan.get("source_relative_path") or "")).resolve()
                    sites_root = self.paths.sites_dir.resolve()
                    moved = recycle / "site"
                    if tombstone.get("recoverable") and moved.is_dir() and not source.exists():
                        plan["status"] = "applied"
                        _atomic_json(self.load_plan_path(token), plan)
                        _atomic_json(transaction_path, {"schema_version": 1, "cleanup_token": token, "stage": "committed", "updated_at": _now()})
                        continue
                    if source.is_relative_to(sites_root) and moved.is_dir() and not source.exists():
                        source.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(moved), str(source))
                    registry_backup = recycle / "registry.json"
                    app_backup = recycle / "app.json"
                    if registry_backup.is_file():
                        shutil.copy2(registry_backup, self.registry.path)
                    if app_backup.is_file():
                        shutil.copy2(app_backup, self.paths.app_config_path)
                    _atomic_json(transaction_path, {"schema_version": 1, "cleanup_token": token, "stage": "rolled_back", "updated_at": _now()})
                except Exception:
                    continue

    def _blocking_reasons(self, site: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if site["is_current"]:
            reasons.append("当前局点")
        if site["is_referenced_by_bootstrap"]:
            reasons.append("bootstrap 当前局点引用")
        if site["unique_business_data"]:
            reasons.append("存在业务数据或原始文件")
        if any(
            str(item) not in {"registry", "app_config.recent_sites"}
            for item in site.get("referenced_records", [])
        ):
            reasons.append("其他局点数据库仍有引用")
        return reasons

    def _remove_from_recent_sites(self, directory_name: str) -> None:
        config = _read_json(self.paths.app_config_path)
        recent = [item for item in config.get("recent_sites", []) if isinstance(item, str) and item.casefold() != directory_name.casefold()]
        config["recent_sites"] = recent
        _atomic_json(self.paths.app_config_path, config)


class SiteApplicationCurrent:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def site_id(self) -> str:
        config = _read_json(self.paths.app_config_path)
        return str(config.get("current_site") or "")


class DemoSiteSeedService:
    """通过现有 SiteManager/Repository/schema 在 staging 中生成可重建 Demo。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def seed(self, *, replace: bool = False, allow_user_data: bool = False, check_cancel: Callable[[], None] | None = None) -> dict[str, Any]:
        self._recover_incomplete_rebuilds()
        existing = self._existing_demo()
        if existing and not replace:
            metadata = _read_json(existing / "site_meta.json")
            if metadata.get("managed_demo") and metadata.get("seed_version") == DEMO_SEED_VERSION:
                return {"site_id": DEFAULT_SITE, "status": "already_current", "seed_version": DEMO_SEED_VERSION, "size_bytes": _directory_size(existing)}
            raise SiteStorageError("DEMO_LEGACY_EXISTS", "旧 Demo 需要先审计或明确重建")
        if existing and SiteApplicationCurrent(self.paths).site_id() == DEFAULT_SITE:
            raise SiteStorageError("DEMO_ACTIVE", "当前局点是 Demo，请先切换到其他局点")
        audit: dict[str, Any] | None = None
        if existing:
            audit = SiteAuditService(self.paths).audit_all(site_id=DEFAULT_SITE)
            site = audit["sites"][0]
            if not site.get("safe_to_replace"):
                raise SiteStorageError("DEMO_USER_DATA", "旧 Demo 可能包含用户数据，必须先完成审计并备份")
        if check_cancel:
            check_cancel()
        staging_root = self.paths.temp_dir / "demo-seed" / uuid.uuid4().hex
        staging_paths = PathResolver(app_root=self.paths.app_root, data_root=staging_root)
        try:
            manager = SiteManager(staging_paths)
            manager.init_site_database(DEFAULT_SITE, with_demo_data=False)
            manager.save_site_metadata(
                DEFAULT_SITE,
                {
                    "display_name": "演示局点",
                    "site_kind": "demo",
                    "managed_demo": True,
                    "seed_version": DEMO_SEED_VERSION,
                    "generated_at": _now(),
                    "user_modified": False,
                    "line_name": "演示线路",
                    "system_type": "PIS",
                    "network_domain": "default",
                    "migration_status": "managed",
                },
            )
            self._seed_devices(staging_paths)
            self._seed_base_data(staging_paths)
            self._seed_mesh_sample(staging_paths)
            staged_demo = staging_paths.site_dir(DEFAULT_SITE)
            _finalize_sqlite_files(staged_demo)
            self._write_seed_manifest(staged_demo)
            if _directory_size(staged_demo) > DEMO_MAX_BYTES:
                raise SiteStorageError("DEMO_SIZE_LIMIT", "演示数据超过 50 MB 限制")
            final = self.paths.site_dir(DEFAULT_SITE)
            backup_root: Path | None = None
            backup_site: Path | None = None
            published = False
            registry = SiteRegistryRepository(self.paths)
            registry_existed = registry.path.is_file()
            app_existed = self.paths.app_config_path.is_file()
            transaction_backup = staging_root / "transaction-backup"
            transaction_backup.mkdir(parents=True, exist_ok=True)
            if registry_existed:
                shutil.copy2(registry.path, transaction_backup / "registry.json")
            if app_existed:
                shutil.copy2(self.paths.app_config_path, transaction_backup / "app.json")
            with storage_lock(self.paths, "site-mutation"):
                try:
                    if existing:
                        backup_root = self.paths.archive_dir / "demo-recycle" / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:8]}"
                        backup_root.mkdir(parents=True, exist_ok=False)
                        backup_site = backup_root / "site"
                        transaction_path = backup_root / "transaction.json"
                        _atomic_json(transaction_path, {"schema_version": 1, "stage": "prepared", "created_at": _now()})
                        if registry_existed:
                            shutil.copy2(transaction_backup / "registry.json", backup_root / "registry.json")
                        if app_existed:
                            shutil.copy2(transaction_backup / "app.json", backup_root / "app.json")
                        if audit:
                            audit_path = self.paths.data_root / str(audit["manifest_path"])
                            if audit_path.is_file():
                                shutil.copy2(audit_path, backup_root / "audit-manifest.json")
                        shutil.move(str(existing), str(backup_site))
                        _atomic_json(transaction_path, {"schema_version": 1, "stage": "old_moved", "updated_at": _now()})
                    final.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(staged_demo), str(final))
                    published = True
                    if backup_root:
                        _atomic_json(backup_root / "transaction.json", {"schema_version": 1, "stage": "new_published", "updated_at": _now()})
                    registry.register(SiteRecord(DEFAULT_SITE, "演示局点", final, remark="受控可重建演示数据"))
                    if backup_root:
                        _atomic_json(backup_root / "transaction.json", {"schema_version": 1, "stage": "registry_updated", "updated_at": _now()})
                        self._write_rebuild_tombstone(backup_root, backup_site, final)
                        _atomic_json(backup_root / "transaction.json", {"schema_version": 1, "stage": "committed", "updated_at": _now()})
                    return {
                        "site_id": DEFAULT_SITE,
                        "status": "rebuilt" if existing else "created",
                        "seed_version": DEMO_SEED_VERSION,
                        "size_bytes": _directory_size(final),
                        "backup_path": _relative(self.paths.data_root, backup_root) if backup_root else "",
                    }
                except Exception as exc:
                    if published and final.exists():
                        failed_target = (backup_root / "failed-new-site") if backup_root else staging_paths.site_dir("failed-demo")
                        failed_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(final), str(failed_target))
                    if backup_site and backup_site.exists() and not final.exists():
                        shutil.move(str(backup_site), str(final))
                    if registry_existed and (transaction_backup / "registry.json").is_file():
                        registry.path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(transaction_backup / "registry.json", registry.path)
                    elif not registry_existed:
                        registry.path.unlink(missing_ok=True)
                    if app_existed and (transaction_backup / "app.json").is_file():
                        self.paths.app_config_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(transaction_backup / "app.json", self.paths.app_config_path)
                    elif not app_existed:
                        self.paths.app_config_path.unlink(missing_ok=True)
                    if backup_root:
                        _atomic_json(
                            backup_root / "rollback.json",
                            {"schema_version": 1, "failed_at": _now(), "reason": type(exc).__name__, "restored": final.exists()},
                        )
                        _atomic_json(backup_root / "transaction.json", {"schema_version": 1, "stage": "rolled_back", "updated_at": _now()})
                    raise SiteStorageError("DEMO_REBUILD_FAILED", "演示局点重建失败，已恢复旧 Demo") from exc
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)

    def _existing_demo(self) -> Path | None:
        path = self.paths.site_dir(DEFAULT_SITE)
        return path if path.is_dir() else None

    def _recover_incomplete_rebuilds(self) -> None:
        root = self.paths.archive_dir / "demo-recycle"
        if not root.is_dir():
            return
        with storage_lock(self.paths, "site-mutation"):
            for transaction_path in root.glob("*/transaction.json"):
                transaction = _read_json(transaction_path)
                if transaction.get("stage") in {"committed", "rolled_back"}:
                    continue
                backup_root = transaction_path.parent
                backup_site = backup_root / "site"
                final = self.paths.site_dir(DEFAULT_SITE)
                try:
                    if _read_json(backup_root / "tombstone.json").get("recoverable"):
                        _atomic_json(transaction_path, {"schema_version": 1, "stage": "committed", "updated_at": _now()})
                        continue
                    if final.exists() and backup_site.is_dir():
                        failed_target = backup_root / "failed-new-site"
                        if not failed_target.exists():
                            shutil.move(str(final), str(failed_target))
                    if backup_site.is_dir() and not final.exists():
                        shutil.move(str(backup_site), str(final))
                    registry_backup = backup_root / "registry.json"
                    app_backup = backup_root / "app.json"
                    registry = SiteRegistryRepository(self.paths)
                    if registry_backup.is_file():
                        shutil.copy2(registry_backup, registry.path)
                    if app_backup.is_file():
                        shutil.copy2(app_backup, self.paths.app_config_path)
                    _atomic_json(transaction_path, {"schema_version": 1, "stage": "rolled_back", "updated_at": _now()})
                except Exception:
                    continue

    @staticmethod
    def _write_seed_manifest(root: Path) -> None:
        files = _file_manifest(root)
        _atomic_json(
            root / _DEMO_MANIFEST_NAME,
            {
                "schema_version": 1,
                "seed_version": DEMO_SEED_VERSION,
                "generated_at": _now(),
                "manifest_sha256": _manifest_digest(files),
                "files": files,
            },
        )

    @staticmethod
    def _write_rebuild_tombstone(backup_root: Path, backup_site: Path | None, final: Path) -> None:
        if backup_site is None or not backup_site.is_dir():
            return
        files = _file_manifest(backup_site)
        _atomic_json(
            backup_root / "tombstone.json",
            {
                "schema_version": 1,
                "site_id": DEFAULT_SITE,
                "display_name": "演示局点",
                "created_at": _now(),
                "recoverable": True,
                "replaced_by_seed_version": DEMO_SEED_VERSION,
                "old_file_count": len(files),
                "old_file_manifest_sha256": _manifest_digest(files),
                "replacement_relative_path": "sites/demo",
            },
        )

    @staticmethod
    def _seed_devices(paths: PathResolver) -> None:
        from netconsole.core.database import Database
        from netconsole.models.device import Device
        from netconsole.repositories.device_group_repository import DeviceGroupRepository
        from netconsole.repositories.device_repository import DeviceRepository
        from netconsole.services.demo_data import insert_demo_collected_data

        database = Database(paths.site_db_path(DEFAULT_SITE))
        groups = DeviceGroupRepository(database, DEFAULT_SITE)
        station_group = groups.find_by_name("车站")
        mr_group = groups.find_by_name("车载-MR")
        repository = DeviceRepository(database)
        devices = [
            Device(name="AC", system_name="DEMO-AC01", station="演示站A", device_vendor="H3C", device_type="AC", primary_address="192.0.2.10", group_id=station_group.id if station_group else None, protocol="none", port=None, snmp_enabled=0, ssh_enabled=0, telnet_enabled=0, snmp_v1_enabled=0, snmp_v2c_enabled=0, remark="受控演示数据，不可连接"),
            Device(name="SW01", system_name="DEMO-SW01", station="演示站A", device_vendor="H3C", device_type="SW", primary_address="192.0.2.11", group_id=station_group.id if station_group else None, protocol="none", port=None, snmp_enabled=0, ssh_enabled=0, telnet_enabled=0, snmp_v1_enabled=0, snmp_v2c_enabled=0, remark="受控演示数据，不可连接"),
            Device(name="SW02", system_name="DEMO-SW02", station="演示站C", device_vendor="H3C", device_type="SW", primary_address="192.0.2.12", group_id=station_group.id if station_group else None, protocol="none", port=None, snmp_enabled=0, ssh_enabled=0, telnet_enabled=0, snmp_v1_enabled=0, snmp_v2c_enabled=0, remark="受控演示数据，不可连接"),
            Device(name="列车01-MR-CT", system_name="DEMO-MR01-CT", station="演示区间A-B", device_vendor="H3C", device_type="MR", primary_address="192.0.2.21", group_id=mr_group.id if mr_group else None, protocol="none", port=None, snmp_enabled=0, ssh_enabled=0, telnet_enabled=0, snmp_v1_enabled=0, snmp_v2c_enabled=0, remark="受控演示车载 MR，不可连接"),
            Device(name="列车01-MR-CW", system_name="DEMO-MR01-CW", station="演示区间A-B", device_vendor="H3C", device_type="MR", primary_address="192.0.2.22", group_id=mr_group.id if mr_group else None, protocol="none", port=None, snmp_enabled=0, ssh_enabled=0, telnet_enabled=0, snmp_v1_enabled=0, snmp_v2c_enabled=0, remark="受控演示车载 MR，不可连接"),
        ]
        created = [repository.create(device) for device in devices]
        insert_demo_collected_data(repository, created)

    @staticmethod
    def _seed_base_data(paths: PathResolver) -> None:
        from netconsole.repositories.rail_transit_base_data_repository import RailTransitBaseDataRepository

        repository = RailTransitBaseDataRepository(paths)
        changes: list[dict[str, Any]] = [
            {"entity_type": "site_metadata", "action": "update", "values": {"line_name": "演示线路", "system_type": "PIS", "display_name": "演示局点"}},
            {"entity_type": "station", "action": "create", "values": {"name": "演示站A", "line_name": "演示线路", "code": "D01", "sort_order": 1}},
            {"entity_type": "station", "action": "create", "values": {"name": "演示站B", "line_name": "演示线路", "code": "D02", "sort_order": 2}},
            {"entity_type": "station", "action": "create", "values": {"name": "演示站C", "line_name": "演示线路", "code": "D03", "sort_order": 3}},
            {"entity_type": "section", "action": "create", "values": {"name": "演示区间A-B", "line_name": "演示线路", "start_station": "演示站A", "end_station": "演示站B", "line_side": "左线"}},
            {"entity_type": "section", "action": "create", "values": {"name": "演示区间B-C", "line_name": "演示线路", "start_station": "演示站B", "end_station": "演示站C", "line_side": "右线"}},
        ]
        for index in range(8):
            station = ("演示站A", "演示站B", "演示站C")[index % 3]
            changes.append(
                {
                    "entity_type": "trackside_ap",
                    "action": "create",
                    "values": {
                        "line_name": "演示线路",
                        "system_type": "PIS",
                        "network_domain": "default",
                        "belong_type": "station",
                        "station_name": station,
                        "section_name": "演示区间A-B" if index < 4 else "演示区间B-C",
                        "section_start_station": "演示站A" if index < 4 else "演示站B",
                        "section_end_station": "演示站B" if index < 4 else "演示站C",
                        "line_side": "左线" if index % 2 == 0 else "右线",
                        "direction": "上行" if index % 2 == 0 else "下行",
                        "mileage_text": f"K{index + 1}+100",
                        "ap_point_code": f"DEMO-AP-{index + 1:02d}",
                        "ap_name": f"演示轨旁AP-{index + 1:02d}",
                        "ap_mac_norm": f"02:00:00:00:00:{index + 1:02x}",
                        "ap_mac_display": f"0200-0000-00{index + 1:02x}",
                        "uplink_switch": "SW01" if index < 4 else "SW02",
                        "uplink_port": f"GigabitEthernet1/0/{index + 1}",
                        "source_file": "managed-demo-seed",
                        "source_sheet": "AP",
                        "source_row": index + 2,
                        "remark": "演示数据",
                    },
                }
            )
        repository.apply_base_data_changes(DEFAULT_SITE, repository.base_data_revision(DEFAULT_SITE), changes)

    @staticmethod
    def _seed_mesh_sample(paths: PathResolver) -> None:
        from netconsole.services.mesh_log_analysis_service import MeshLogAnalysisService

        root = paths.site_dir(DEFAULT_SITE) / "files" / "rail_transit" / "mr_raw_mesh" / "managed-demo"
        raw = root / "raw" / "meshlog.log"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("[1] 2025/12/03 10:12:33.000\\n[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0 0/0\\n", encoding="utf-8")
        result = MeshLogAnalysisService(DEFAULT_SITE, root).analyze([raw], analysis_name="演示 MESH 会话")
        if result.analysis_dir is None:
            raise SiteStorageError("DEMO_MESH_SEED_FAILED", "演示 MESH 样本生成失败")


def _directory_size(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


__all__ = ["AUDIT_SCHEMA_VERSION", "DEMO_MAX_BYTES", "DEMO_SEED_VERSION", "DemoSiteSeedService", "SiteAuditService", "SiteCleanupApplicationService"]
