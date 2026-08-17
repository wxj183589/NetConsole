from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Iterator

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.history_store import TaskHistoryStore
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.job_center.artifact_reconciliation import (
    ArtifactReconciliationService,
    ArtifactTaskBinding,
)
from netconsole.services.database_footprint_maintenance import (
    DEVELOPMENT_ROOT,
    assert_development_path,
)
from netconsole.services.site_storage import (
    FULL_MIGRATION,
    SiteApplicationService,
    SitePackageService,
    SiteStorageError,
)


_SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_SKIPPED_SUFFIXES = (".tmp", ".lock", ".part", "-wal", "-shm")
_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\\\/]")
_REGISTRY_SITE_PREFIX = "sites/{site_id}/"
_REGISTRY_CORE_STORE_IDS = frozenset(
    {
        "site.devices.current",
        "site.history.catalog",
        "site.history.shard",
        "site.tasks.current",
        "site.metadata",
        "site.web_artifact.manifests",
        "site.artifacts.managed",
    }
)
_FULL_MIGRATION_SYNC_STORE_IDS = frozenset(
    {
        "site.wps.sync",
        "site.sync.baseline",
        "site.sync.import_audit",
    }
)
_REFERENCE_FIELD = re.compile(
    r"(?:artifact|reference|(?:^|_)ref$|(?:^|_)path$|sha256|source_id)",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_binding(script: Path) -> dict[str, str]:
    repository = script.parents[2]
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {
        "git_head": completed.stdout.strip().casefold(),
        "script_path": script.relative_to(repository).as_posix(),
        "script_sha256": _sha256(script),
    }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _require_inside(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    if resolved == root.resolve() or not _inside(resolved, root):
        raise ValueError(f"{label} must be a child of {root}")
    return resolved


def _require_development_path(path: Path, *, label: str) -> Path:
    if os.name != "nt":
        return path.resolve()
    try:
        return assert_development_path(path, development_root=DEVELOPMENT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must remain below D:/study") from exc


def _readonly_connection(path: Path) -> sqlite3.Connection:
    wal_path = path.with_name(f"{path.name}-wal")
    for attempt in range(5):
        if not wal_path.is_file() or wal_path.stat().st_size == 0:
            break
        if attempt < 4:
            time.sleep(0.05 * (attempt + 1))
    if wal_path.is_file() and wal_path.stat().st_size:
        raise sqlite3.DatabaseError(
            f"non-empty WAL cannot be ignored by immutable read: {wal_path}"
        )
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
        timeout=60,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _quote_sqlite_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _sqlite_backup(source: Path, destination: Path) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = _sha256(source)
    source_connection = _readonly_connection(source)
    target_connection = sqlite3.connect(destination, timeout=60)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
        # A backup of a WAL-mode source inherits the journal mode in the
        # copied database header.  Staging/package copies must be standalone
        # snapshots, so switch the target to rollback journaling before the
        # connection closes; otherwise a later read can recreate ``-wal`` and
        # ``-shm`` sidecars after the initial cleanup below.
        journal_mode = target_connection.execute(
            "PRAGMA journal_mode=DELETE"
        ).fetchone()
        if not journal_mode or str(journal_mode[0]).casefold() != "delete":
            raise sqlite3.DatabaseError(
                f"SQLite backup journal mode reset failed: {destination}"
            )
        target_connection.commit()
        quick_check = target_connection.execute("PRAGMA quick_check").fetchone()
    finally:
        target_connection.close()
        source_connection.close()
    for suffix in ("-wal", "-shm"):
        destination.with_name(f"{destination.name}{suffix}").unlink(missing_ok=True)
    after = _sha256(source)
    if before != after:
        raise RuntimeError(f"read-only SQLite source changed during backup: {source}")
    if not quick_check or str(quick_check[0]).casefold() != "ok":
        raise sqlite3.DatabaseError(f"SQLite backup quick_check failed: {destination}")
    return {
        "source_sha256_before": before,
        "source_sha256_after": after,
        "destination_sha256": _sha256(destination),
        "destination_bytes": destination.stat().st_size,
        "quick_check": "ok",
    }


def _copy_verified_file(source: Path, destination: Path) -> int:
    before = _sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    after = _sha256(source)
    if before != after or _sha256(destination) != before:
        raise RuntimeError(f"file copy verification failed: {source}")
    return destination.stat().st_size


def _copy_tree_readonly(source: Path, destination: Path) -> dict[str, int]:
    totals = {"files": 0, "bytes": 0, "sqlite_files": 0}
    if source.is_file():
        files = [source]
        source_root = source.parent
    elif source.is_dir() and not source.is_symlink():
        files = sorted(item for item in source.rglob("*") if item.is_file())
        source_root = source
    else:
        return totals
    for item in files:
        if item.is_symlink() or item.name.casefold().endswith(_SKIPPED_SUFFIXES):
            continue
        relative = item.name if source.is_file() else item.relative_to(source_root)
        target = destination / relative if source.is_dir() else destination
        if item.suffix.casefold() in _SQLITE_SUFFIXES:
            copied = _sqlite_backup(item, target)
            totals["bytes"] += int(copied["destination_bytes"])
            totals["sqlite_files"] += 1
        else:
            totals["bytes"] += _copy_verified_file(item, target)
        totals["files"] += 1
    return totals


def _package_policy_class(value: object) -> str:
    policy = str(value or "").strip().casefold()
    if (
        policy.startswith("exclude")
        or policy.startswith("never include")
        or "not part of controller site package" in policy
    ):
        return "EXCLUDED"
    if "metadata-only inclusion" in policy or "package metadata only" in policy:
        return "METADATA_ONLY"
    required_markers = (
        "full_migration include",
        "full_migration snapshot",
        "include with every",
        "include operational",
        "include catalog",
        "include all referenced",
        "include and validate in every",
    )
    if any(marker in policy for marker in required_markers):
        return "REQUIRED"
    return "CONDITIONAL"


def _load_site_storage_registry(path: Path) -> list[dict[str, object]]:
    registry_path = Path(path).resolve()
    value = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("unknown_policy") != "PROTECT":
        raise ValueError("storage registry must declare UNKNOWN=PROTECT")
    raw_stores = value.get("stores")
    if not isinstance(raw_stores, list):
        raise ValueError("storage registry stores must be a list")
    stores: list[dict[str, object]] = []
    identifiers: set[str] = set()
    for raw in raw_stores:
        if not isinstance(raw, dict):
            raise ValueError("storage registry store must be an object")
        store_id = str(raw.get("id") or "").strip()
        relative_path = str(raw.get("relative_path") or "").replace("\\", "/")
        if not store_id or store_id in identifiers:
            raise ValueError("storage registry store ids must be unique and non-empty")
        identifiers.add(store_id)
        if not relative_path.startswith(_REGISTRY_SITE_PREFIX):
            continue
        stores.append(
            {
                "id": store_id,
                "relative_path": relative_path,
                "site_pattern": relative_path.removeprefix(_REGISTRY_SITE_PREFIX),
                "owner": str(raw.get("owner") or ""),
                "authority": str(raw.get("authority") or ""),
                "data_type": str(raw.get("data_type") or "UNKNOWN"),
                "site_package_policy": str(raw.get("site_package_policy") or ""),
                "policy_class": _package_policy_class(raw.get("site_package_policy")),
                "source_locations": sorted(
                    str(item) for item in raw.get("source_locations", []) if str(item)
                ),
            }
        )
    registered = {str(store["id"]): store for store in stores}
    missing_sync = sorted(_FULL_MIGRATION_SYNC_STORE_IDS - registered.keys())
    if missing_sync:
        raise ValueError(
            "storage registry omits FULL_MIGRATION sync authority: "
            + ", ".join(missing_sync)
        )
    non_required_sync = sorted(
        store_id
        for store_id in _FULL_MIGRATION_SYNC_STORE_IDS
        if registered[store_id]["policy_class"] != "REQUIRED"
    )
    if non_required_sync:
        raise ValueError(
            "FULL_MIGRATION sync authority must be REQUIRED: "
            + ", ".join(non_required_sync)
        )
    return stores


def _registry_pattern_regex(value: str) -> re.Pattern[str]:
    pattern = str(value).strip().replace("\\", "/")
    if not pattern or pattern.startswith("/") or ".." in pattern.split("/"):
        raise ValueError(f"unsafe storage registry site pattern: {value}")
    output: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            output.append(".*")
            index += 2
            continue
        if pattern[index] == "*":
            output.append("[^/]*")
            index += 1
            continue
        if pattern[index] == "{":
            end = pattern.find("}", index + 1)
            if end < 0:
                raise ValueError(f"invalid storage registry placeholder: {value}")
            output.append("[^/]+")
            index = end + 1
            continue
        if pattern.startswith("YYYY-MM-DD", index):
            output.append(r"\d{4}-\d{2}-\d{2}")
            index += len("YYYY-MM-DD")
            continue
        if pattern.startswith("YYYY-MM", index):
            output.append(r"\d{4}-\d{2}")
            index += len("YYYY-MM")
            continue
        if pattern.startswith("[-NNNN]", index):
            output.append(r"(?:-\d{4})?")
            index += len("[-NNNN]")
            continue
        output.append(re.escape(pattern[index]))
        index += 1
    if pattern.endswith("/"):
        output.append(".*")
    output.append("$")
    return re.compile("".join(output))


def _registered_store_files(
    site_root: Path,
    stores: list[dict[str, object]],
) -> dict[str, list[Path]]:
    root = Path(site_root).resolve()
    files = sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and not item.is_symlink()
    )
    relative_files = [(item, item.relative_to(root).as_posix()) for item in files]
    result: dict[str, list[Path]] = {}
    for store in stores:
        patterns = [
            _registry_pattern_regex(value)
            for value in str(store["site_pattern"]).split("|")
        ]
        result[str(store["id"])] = [
            item
            for item, relative in relative_files
            if any(pattern.fullmatch(relative) for pattern in patterns)
        ]
    return result


def _registered_store_coverage(
    site_root: Path,
    discovered: dict[str, list[Path]],
) -> dict[str, object]:
    root = Path(site_root).resolve()
    owners: dict[str, list[str]] = defaultdict(list)
    for store_id, paths in discovered.items():
        for path in paths:
            relative = path.resolve().relative_to(root).as_posix()
            owners[relative].append(str(store_id))
    all_files = sorted(
        item.resolve().relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() and not item.is_symlink()
    )
    unregistered = [path for path in all_files if path not in owners]
    ambiguous = {
        path: sorted(store_ids)
        for path, store_ids in sorted(owners.items())
        if len(store_ids) != 1
    }
    return {
        "status": "PASS" if not unregistered and not ambiguous else "FAIL",
        "files": len(all_files),
        "unregistered_files": unregistered,
        "ambiguous_files": ambiguous,
    }


def _copy_registered_package_authorities(
    source_site_root: Path,
    target_site_root: Path,
    stores: list[dict[str, object]],
) -> dict[str, object]:
    discovered = _registered_store_files(source_site_root, stores)
    coverage = _registered_store_coverage(source_site_root, discovered)
    if coverage["status"] != "PASS":
        raise ValueError(
            "artifact source contains unregistered or ambiguous storage; UNKNOWN=PROTECT"
        )
    copied: dict[str, dict[str, int]] = {}
    copied_paths: set[str] = set()
    skipped_existing = 0
    for store in stores:
        store_id = str(store["id"])
        if store_id in _REGISTRY_CORE_STORE_IDS or store["policy_class"] in {
            "EXCLUDED",
            "METADATA_ONLY",
        }:
            continue
        summary = copied.setdefault(store_id, {"files": 0, "bytes": 0, "sqlite_files": 0})
        for source in discovered[store_id]:
            relative = source.resolve().relative_to(source_site_root.resolve())
            relative_name = relative.as_posix()
            if relative_name in copied_paths:
                continue
            destination = target_site_root / relative
            if destination.exists():
                skipped_existing += 1
                copied_paths.add(relative_name)
                continue
            if source.name.casefold().endswith(_SKIPPED_SUFFIXES):
                continue
            if source.suffix.casefold() in _SQLITE_SUFFIXES:
                details = _sqlite_backup(source, destination)
                summary["bytes"] += int(details["destination_bytes"])
                summary["sqlite_files"] += 1
            else:
                summary["bytes"] += _copy_verified_file(source, destination)
            summary["files"] += 1
            copied_paths.add(relative_name)
    active = {key: value for key, value in copied.items() if value["files"]}
    return {
        "stores_discovered": sum(bool(value) for value in discovered.values()),
        "stores_copied": len(active),
        "files_copied": sum(value["files"] for value in active.values()),
        "bytes_copied": sum(value["bytes"] for value in active.values()),
        "sqlite_files_copied": sum(
            value["sqlite_files"] for value in active.values()
        ),
        "skipped_existing": skipped_existing,
        "stores": active,
        "registry_coverage": coverage,
    }


def _semantic_scalar(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, float):
        return {"float": value.hex()}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


def _reference_digest(values: Iterable[tuple[str, object]]) -> dict[str, object]:
    references = sorted(
        (str(owner), _stable_digest(_semantic_scalar(value)))
        for owner, value in values
        if value not in {None, ""}
    )
    return {"count": len(references), "digest": _stable_digest(references)}


def _sqlite_authority_profile(path: Path) -> dict[str, object]:
    tables: dict[str, object] = {}
    references: list[tuple[str, object]] = []
    with _readonly_connection(path) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        schema_objects = [
            {
                "type": str(row[0]),
                "name": str(row[1]),
                "table": str(row[2]),
                "sql": str(row[3] or ""),
            }
            for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name,tbl_name"
            )
        ]
        schemas = {
            str(row[0]): str(row[1] or "")
            for row in connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        }
        for table, schema in schemas.items():
            quoted_table = _quote_sqlite_identifier(table)
            columns = [
                dict(row)
                for row in connection.execute(f"PRAGMA table_info({quoted_table})")
            ]
            names = [str(column["name"]) for column in columns]
            quoted = ",".join(_quote_sqlite_identifier(name) for name in names)
            primary = [
                str(column["name"])
                for column in sorted(columns, key=lambda item: int(item["pk"]))
                if int(column["pk"])
            ]
            if primary:
                order = ",".join(_quote_sqlite_identifier(name) for name in primary)
            elif "WITHOUT ROWID" not in schema.upper():
                order = "rowid"
            else:
                order = quoted
            digest = hashlib.sha256()
            row_count = 0
            reference_indexes = [
                index for index, name in enumerate(names) if _REFERENCE_FIELD.search(name)
            ]
            rows = connection.execute(
                f"SELECT {quoted} FROM {quoted_table} ORDER BY {order}"
            )
            for row in rows:
                values = [_semantic_scalar(value) for value in tuple(row)]
                digest.update(
                    json.dumps(
                        values,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                digest.update(b"\n")
                row_count += 1
                references.extend(
                    (f"{table}.{names[index]}", row[index])
                    for index in reference_indexes
                )
                for index, value in enumerate(tuple(row)):
                    if not isinstance(value, str) or not value.lstrip().startswith(
                        ("{", "[")
                    ):
                        continue
                    try:
                        nested = json.loads(value)
                    except json.JSONDecodeError:
                        continue
                    references.extend(
                        (f"{table}.{names[index]}.{owner}", reference)
                        for owner, reference in _json_references(nested)
                    )
            tables[table] = {
                "rows": row_count,
                "columns": names,
                "schema_digest": _stable_digest(schema),
                "row_digest": digest.hexdigest(),
            }
    semantic = {
        "schema_objects": schema_objects,
        "tables": tables,
        "references": _reference_digest(references),
    }
    return {
        "kind": "sqlite",
        "quick_check": str(quick_check[0]) if quick_check else "missing",
        **semantic,
        "semantic_digest": _stable_digest(semantic),
    }


def _json_references(
    value: object,
    prefix: tuple[str, ...] = (),
) -> Iterator[tuple[str, object]]:
    if isinstance(value, dict):
        for key, item in value.items():
            current = (*prefix, str(key))
            if _REFERENCE_FIELD.search(str(key)) and not isinstance(item, (dict, list)):
                yield ".".join(current), item
            yield from _json_references(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _json_references(item, (*prefix, str(index)))


def _authority_file_profile(path: Path) -> dict[str, object]:
    if path.suffix.casefold() in _SQLITE_SUFFIXES:
        return _sqlite_authority_profile(path)
    if path.suffix.casefold() == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            digest = _sha256(path)
            return {
                "kind": "json",
                "parse_status": "INVALID_PROTECTED",
                "json_digest": digest,
                "references": _reference_digest(()),
                "semantic_digest": digest,
            }
        semantic = {
            "json_digest": _stable_digest(value),
            "references": _reference_digest(_json_references(value)),
        }
        return {
            "kind": "json",
            "parse_status": "VALID",
            **semantic,
            "semantic_digest": _stable_digest(semantic),
        }
    return {
        "kind": "file",
        "semantic_digest": _sha256(path),
        "references": _reference_digest(()),
    }


def _registered_authority_profile(
    site_root: Path,
    stores: list[dict[str, object]],
) -> dict[str, object]:
    discovered = _registered_store_files(site_root, stores)
    coverage = _registered_store_coverage(site_root, discovered)
    result: dict[str, object] = {}
    for store in stores:
        store_id = str(store["id"])
        if store_id in _REGISTRY_CORE_STORE_IDS:
            continue
        files: dict[str, object] = {}
        reference_count = 0
        reference_values: list[tuple[str, str]] = []
        for path in discovered[store_id]:
            # SQLite WAL/SHM sidecars may disappear between the recursive
            # inventory and profiling when the writer connection checkpoints
            # or closes. They are runtime-only and excluded from package
            # authority; do not turn that benign race into a failed rehearsal.
            if not path.exists():
                continue
            relative = path.resolve().relative_to(site_root.resolve()).as_posix()
            profile = _authority_file_profile(path)
            files[relative] = profile
            refs = profile.get("references", {})
            if isinstance(refs, dict):
                reference_count += int(refs.get("count") or 0)
                reference_values.append((relative, str(refs.get("digest") or "")))
        semantic = {
            relative: str(details.get("semantic_digest") or "")
            for relative, details in files.items()
            if isinstance(details, dict)
        }
        result[store_id] = {
            "policy_class": store["policy_class"],
            "site_package_policy": store["site_package_policy"],
            "owner": store["owner"],
            "authority": store["authority"],
            "data_type": store["data_type"],
            "source_locations": store["source_locations"],
            "file_count": len(files),
            "files": files,
            "artifact_reference_count": reference_count,
            "artifact_reference_digest": _stable_digest(reference_values),
            "semantic_digest": _stable_digest(semantic),
        }
    aggregate = {
        store_id: {
            "file_count": details["file_count"],
            "artifact_reference_count": details["artifact_reference_count"],
            "artifact_reference_digest": details["artifact_reference_digest"],
            "semantic_digest": details["semantic_digest"],
        }
        for store_id, details in result.items()
        if isinstance(details, dict) and int(details["file_count"])
    }
    return {
        "stores": result,
        "present_store_count": len(aggregate),
        "file_count": sum(int(value["file_count"]) for value in aggregate.values()),
        "artifact_reference_count": sum(
            int(value["artifact_reference_count"]) for value in aggregate.values()
        ),
        "aggregate_digest": _stable_digest(aggregate),
        "registry_coverage": coverage,
    }


def _package_manifest_members(package: Path) -> set[str]:
    import zipfile

    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    checksums = manifest.get("checksums") if isinstance(manifest, dict) else None
    if not isinstance(checksums, dict):
        raise ValueError("Site Package manifest checksums are missing")
    return {str(value) for value in checksums}


def _registered_export_contract(
    profile: dict[str, object],
    package_members: set[str],
) -> dict[str, object]:
    stores: dict[str, object] = {}
    required_missing = 0
    excluded_included = 0
    coverage = dict(profile.get("registry_coverage", {}))
    for store_id, raw in dict(profile["stores"]).items():
        details = dict(raw)
        files = sorted(str(value) for value in dict(details["files"]))
        included = [value for value in files if f"site/{value}" in package_members]
        missing = sorted(set(files) - set(included))
        policy_class = str(details["policy_class"])
        status = "PASS"
        if policy_class == "REQUIRED" and missing:
            status = "FAIL"
            required_missing += len(missing)
        if policy_class in {"EXCLUDED", "METADATA_ONLY"} and included:
            status = "FAIL"
            excluded_included += len(included)
        stores[str(store_id)] = {
            "policy_class": policy_class,
            "status": status,
            "source_files": len(files),
            "included_files": len(included),
            "missing_files": missing,
        }
    return {
        "status": (
            "PASS"
            if not required_missing
            and not excluded_included
            and coverage.get("status") == "PASS"
            else "FAIL"
        ),
        "required_missing_files": required_missing,
        "excluded_included_files": excluded_included,
        "registry_coverage": coverage,
        "stores": stores,
    }


def _registered_authority_parity(
    source: dict[str, object],
    target: dict[str, object],
) -> dict[str, object]:
    differences: list[dict[str, object]] = []
    for side, profile in (("source", source), ("imported", target)):
        coverage = dict(profile.get("registry_coverage", {}))
        if coverage.get("status") != "PASS":
            differences.append(
                {
                    "store_id": "REGISTRY_COVERAGE",
                    "field": side,
                    "source": coverage if side == "source" else "PASS",
                    "imported": coverage if side == "imported" else "PASS",
                }
            )
    target_stores = dict(target["stores"])
    for store_id, raw in dict(source["stores"]).items():
        before = dict(raw)
        if before["policy_class"] in {"EXCLUDED", "METADATA_ONLY"} or not int(
            before["file_count"]
        ):
            continue
        after = dict(target_stores.get(store_id, {}))
        for field in (
            "file_count",
            "semantic_digest",
            "artifact_reference_count",
            "artifact_reference_digest",
        ):
            if before.get(field) != after.get(field):
                differences.append(
                    {
                        "store_id": str(store_id),
                        "field": field,
                        "source": before.get(field),
                        "imported": after.get(field),
                    }
                )
    return {
        "status": "PASS" if not differences else "FAIL",
        "differences": differences,
        "source_present_stores": int(source["present_store_count"]),
        "imported_present_stores": int(target["present_store_count"]),
    }


def _registered_store_subset_parity(
    source: dict[str, object],
    target: dict[str, object],
    store_ids: Iterable[str],
) -> dict[str, object]:
    differences: list[dict[str, object]] = []
    source_stores = dict(source["stores"])
    target_stores = dict(target["stores"])
    for store_id in sorted(store_ids):
        before = dict(source_stores.get(store_id, {}))
        after = dict(target_stores.get(store_id, {}))
        for field in (
            "file_count",
            "semantic_digest",
            "artifact_reference_count",
            "artifact_reference_digest",
        ):
            if before.get(field) != after.get(field):
                differences.append(
                    {
                        "store_id": store_id,
                        "field": field,
                        "source": before.get(field),
                        "imported": after.get(field),
                    }
                )
    return {
        "status": "PASS" if not differences else "FAIL",
        "differences": differences,
    }


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {
        name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
        for name in names
    }


def _sqlite_profile(path: Path) -> dict[str, object]:
    with _readonly_connection(path) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        schema = [
            tuple(row)
            for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE sql IS NOT NULL ORDER BY type,name"
            )
        ]
        counts = _table_counts(connection)
    return {
        "size_bytes": path.stat().st_size,
        "quick_check": str(quick_check[0]) if quick_check else "missing",
        "schema_digest": _stable_digest(schema),
        "table_counts": counts,
    }


def _ap_identity_contract(path: Path, *, reason: str) -> dict[str, object]:
    database = Database(path)
    with database.connect_readonly() as connection:
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        schema_version_before = (
            str(
                connection.execute(
                    "SELECT value FROM schema_metadata WHERE key='schema_version'"
                ).fetchone()[0]
            )
            if "schema_metadata" in table_names
            else ""
        )
        source_revision_before = (
            int(
                connection.execute(
                    "SELECT revision FROM ap_identity_source_state "
                    "WHERE site_id='current'"
                ).fetchone()[0]
            )
            if "ap_identity_source_state" in table_names
            else None
        )
        evidence_existed_before = "ap_identity_radio_evidence" in table_names
        evidence_count_before = (
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM ap_identity_radio_evidence"
                ).fetchone()[0]
            )
            if evidence_existed_before
            else 0
        )
    database.initialize()
    service = ApIdentityQueryService(database)
    rebuilt = service.ensure_index(reason)
    state = service.revision_state()
    with database.connect_readonly() as connection:
        aliases = [
            tuple(row)
            for row in connection.execute(
                """
                SELECT entity_id, mac_key, alias_type, source,
                       match_priority, confidence, radio_id,
                       derivation_rule, is_exact, is_active
                FROM ap_identity_mac_aliases
                WHERE site_id='current'
                ORDER BY entity_id, mac_key, alias_type, source
                """
            ).fetchall()
        ]
        query_keys = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT mac_key
                FROM ap_identity_mac_aliases
                WHERE site_id='current' AND is_active=1
                ORDER BY mac_key
                """
            ).fetchall()
        ]
        evidence_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM ap_identity_radio_evidence"
            ).fetchone()[0]
        )

    def query_rows(batch: object) -> list[tuple[str, dict[str, object]]]:
        matches = getattr(batch, "matches")
        rows: list[tuple[str, dict[str, object]]] = []
        for mac_key, match in sorted(matches.items()):
            payload = asdict(match)
            payload.pop("identity_revision", None)
            rows.append((str(mac_key), payload))
        return rows

    exact_rows = query_rows(service.resolve_ap_macs(query_keys))
    peer_rows = query_rows(service.resolve_peer_macs(query_keys))
    semantic = {
        "aliases": aliases,
        "exact_queries": exact_rows,
        "peer_queries": peer_rows,
    }
    return {
        "status": state.status,
        "index_rebuilt": rebuilt is not None,
        "schema_version_before_initialize": schema_version_before,
        "schema_version_after_initialize": _database_schema_version(database),
        "source_revision_before_initialize": source_revision_before,
        "source_revision_after_initialize": state.current_source_revision,
        "source_revision_preserved_by_initialize": (
            source_revision_before is None
            or source_revision_before == state.current_source_revision
        ),
        "radio_evidence_existed_before_initialize": evidence_existed_before,
        "radio_evidence_count_before_initialize": evidence_count_before,
        "alias_count": len(aliases),
        "radio_evidence_count": evidence_count,
        "query_key_count": len(query_keys),
        "exact_query_digest": _stable_digest(exact_rows),
        "peer_query_digest": _stable_digest(peer_rows),
        "semantic_digest": _stable_digest(semantic),
    }


def _database_schema_version(database: Database) -> str:
    with database.connect_readonly() as connection:
        row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
    return str(row[0]) if row is not None else ""


def _history_summary(root: Path) -> dict[str, object]:
    files: dict[str, object] = {}
    total_kinds: Counter[str] = Counter()
    total_payload_bytes: Counter[str] = Counter()
    total_events = 0
    for database in sorted(root.glob("*.db"), key=lambda value: value.name):
        with _readonly_connection(database) as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            kinds: dict[str, dict[str, object]] = {}
            identity = hashlib.sha256()
            if "history_events_v2" in tables:
                grouped = connection.execute(
                    "SELECT k.name, COUNT(*), MIN(e.collected_at), MAX(e.collected_at), "
                    "COALESCE(SUM(LENGTH(e.payload)), 0) "
                    "FROM history_events_v2 e "
                    "JOIN history_kinds_v2 k ON k.kind_id=e.kind_id GROUP BY k.name "
                    "ORDER BY k.name"
                ).fetchall()
                for row in grouped:
                    kinds[str(row[0])] = {
                        "rows": int(row[1]),
                        "first": str(row[2] or ""),
                        "last": str(row[3] or ""),
                        "payload_bytes": int(row[4]),
                    }
                rows = connection.execute(
                    "SELECT HEX(e.event_id),k.name,en.entity_key,t.name,e.collected_at,"
                    "LENGTH(e.payload) FROM history_events_v2 e "
                    "JOIN history_kinds_v2 k ON k.kind_id=e.kind_id "
                    "JOIN history_entities_v2 en ON en.entity_id=e.entity_id "
                    "JOIN history_event_types_v2 t ON t.event_type_id=e.event_type_id "
                    "ORDER BY e.collected_at,e.event_id"
                )
                for row in rows:
                    identity.update(json.dumps(tuple(row), ensure_ascii=False).encode("utf-8"))
                    identity.update(b"\n")
            if "history_events" in tables:
                grouped = connection.execute(
                    "SELECT kind,COUNT(*),MIN(collected_at),MAX(collected_at),"
                    "COALESCE(SUM(LENGTH(payload_json)),0) FROM history_events "
                    "GROUP BY kind ORDER BY kind"
                ).fetchall()
                for row in grouped:
                    current = kinds.setdefault(
                        str(row[0]),
                        {"rows": 0, "first": "", "last": "", "payload_bytes": 0},
                    )
                    current["rows"] = int(current["rows"]) + int(row[1])
                    current["payload_bytes"] = int(current["payload_bytes"]) + int(row[4])
                    values = [value for value in (str(current["first"]), str(row[2] or "")) if value]
                    current["first"] = min(values) if values else ""
                    values = [value for value in (str(current["last"]), str(row[3] or "")) if value]
                    current["last"] = max(values) if values else ""
                rows = connection.execute(
                    "SELECT event_id,kind,entity_key,event_type,collected_at,"
                    "LENGTH(payload_json) FROM history_events ORDER BY collected_at,event_id"
                )
                for row in rows:
                    identity.update(json.dumps(tuple(row), ensure_ascii=False).encode("utf-8"))
                    identity.update(b"\n")
            table_counts = _table_counts(connection)
        for kind, values in kinds.items():
            total_kinds[kind] += int(values["rows"])
            total_payload_bytes[kind] += int(values["payload_bytes"])
            total_events += int(values["rows"])
        files[database.name] = {
            "size_bytes": database.stat().st_size,
            "quick_check": str(quick_check[0]) if quick_check else "missing",
            "table_counts": table_counts,
            "kinds": kinds,
            "event_identity_digest": identity.hexdigest(),
        }
    semantic = {
        name: {
            key: value
            for key, value in details.items()
            if key != "size_bytes"
        }
        for name, details in files.items()
    }
    return {
        "files": files,
        "semantic_digest": _stable_digest(semantic),
        "total_events": total_events,
        "kind_counts": dict(sorted(total_kinds.items())),
        "kind_payload_bytes": dict(sorted(total_payload_bytes.items())),
        "total_bytes": sum(path.stat().st_size for path in root.glob("*.db")),
    }


def _expand_integer_ranges(values: Iterable[object]) -> list[int]:
    result: list[int] = []
    previous = 0
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("task history range must be an object")
        start = int(item.get("start") or 0)
        end = int(item.get("end") or 0)
        if start <= previous or end < start:
            raise ValueError("task history ranges must be ordered and non-overlapping")
        result.extend(range(start, end + 1))
        previous = end
    return result


def _rows_by_sequence(database: Path, sequences: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _readonly_connection(database) as connection:
        for offset in range(0, len(sequences), 500):
            chunk = sequences[offset : offset + 500]
            selected = connection.execute(
                "SELECT sequence,event_id,task_id,event_type,event_time,source,payload_json "
                f"FROM task_events WHERE sequence IN ({','.join('?' for _ in chunk)}) "
                "ORDER BY sequence",
                chunk,
            ).fetchall()
            rows.extend(dict(row) for row in selected)
    if [int(row["sequence"]) for row in rows] != sequences:
        raise ValueError("task history source sequence set changed")
    return rows


def _canonical_task_rows(database: Path) -> list[dict[str, Any]]:
    with _readonly_connection(database) as connection:
        results = {
            str(row["result_id"]): json.loads(str(row["canonical_json"]))
            for row in connection.execute(
                "SELECT result_id,canonical_json FROM task_results ORDER BY result_id"
            )
        }
        rows = connection.execute(
            "SELECT task_id,task_type,owner,status,site_name,result_json,result_id "
            "FROM task_snapshots ORDER BY task_id"
        ).fetchall()
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        result_id = str(row.get("result_id") or "")
        result = results.get(result_id)
        if result is None:
            try:
                result = json.loads(str(row.get("result_json") or "{}"))
            except json.JSONDecodeError:
                result = {}
        row["result"] = result if isinstance(result, dict) else {}
        output.append(row)
    return output


def _walk_values(value: object, prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_values(item, (*prefix, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_values(item, (*prefix, str(index)))
    elif isinstance(value, str):
        yield prefix, value


def _copy_artifact_authorities(
    task_rows: list[dict[str, Any]],
    *,
    source_site_root: Path,
    target_site_root: Path,
) -> dict[str, object]:
    manifest_source = source_site_root / "files" / "rail_transit" / "web_artifacts" / "manifests"
    manifest_target = target_site_root / "files" / "rail_transit" / "web_artifacts" / "manifests"
    copied_manifest_ids: set[str] = set()
    copied_relative_paths: set[str] = set()
    copied_bytes = 0
    referenced_ids: set[str] = set()
    legacy_paths: list[dict[str, object]] = []
    for row in task_rows:
        result = row["result"]
        artifact_id = str(result.get("artifact_id") or "")
        try:
            parsed_id = str(uuid.UUID(artifact_id))
        except ValueError:
            parsed_id = ""
        if parsed_id:
            referenced_ids.add(parsed_id)
            source_manifest = manifest_source / f"{parsed_id}.json"
            if source_manifest.is_file() and not source_manifest.is_symlink():
                manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError(f"Artifact manifest is not an object: {parsed_id}")
                relative = Path(str(manifest.get("relative_path") or ""))
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"Artifact manifest path is unsafe: {parsed_id}")
                source_output = (source_site_root / relative).resolve()
                if not _inside(source_output, source_site_root):
                    raise ValueError(f"Artifact output escapes source site: {parsed_id}")
                copied_bytes += _copy_verified_file(
                    source_manifest,
                    manifest_target / source_manifest.name,
                )
                copied_manifest_ids.add(parsed_id)
                if source_output.is_file() and not source_output.is_symlink():
                    copied_bytes += _copy_verified_file(
                        source_output,
                        target_site_root / relative,
                    )
                    copied_relative_paths.add(relative.as_posix())
        for keys, raw_path in _walk_values(result):
            if not keys or keys[-1] not in {"package_path", "session_dir", "result_path"}:
                continue
            if not _ABSOLUTE_WINDOWS_PATH.match(raw_path):
                continue
            value = Path(raw_path)
            managed = _inside(value, source_site_root)
            exists = value.exists()
            legacy_paths.append(
                {
                    "task_id_digest": hashlib.sha256(str(row["task_id"]).encode()).hexdigest(),
                    "field": ".".join(keys),
                    "inside_site_authority": managed,
                    "source_exists": exists,
                }
            )
            if not managed or not exists:
                continue
            relative = value.resolve().relative_to(source_site_root.resolve())
            if relative.as_posix() in copied_relative_paths:
                continue
            copied = _copy_tree_readonly(value, target_site_root / relative)
            copied_bytes += copied["bytes"]
            copied_relative_paths.add(relative.as_posix())
    return {
        "referenced_manifest_ids": len(referenced_ids),
        "copied_manifests": len(copied_manifest_ids),
        "copied_authority_paths": len(copied_relative_paths),
        "copied_bytes": copied_bytes,
        "legacy_absolute_references": len(legacy_paths),
        "legacy_reference_fields": dict(sorted(Counter(str(item["field"]) for item in legacy_paths).items())),
        "legacy_inside_site_and_available": sum(
            bool(item["inside_site_authority"] and item["source_exists"])
            for item in legacy_paths
        ),
        "legacy_outside_or_missing": sum(
            not bool(item["inside_site_authority"] and item["source_exists"])
            for item in legacy_paths
        ),
        "legacy_reference_digest": _stable_digest(legacy_paths),
    }


def _artifact_reconciliation(
    paths: PathResolver,
    site_name: str,
    task_rows: list[dict[str, Any]],
) -> dict[str, object]:
    service = ArtifactReconciliationService(paths)
    states: Counter[str] = Counter()
    eligible = 0
    legacy = 0
    for row in task_rows:
        result = row["result"]
        required = {
            "artifact_id",
            "artifact_source",
            "artifact_type",
            "artifact_name",
            "sha256",
            "size_bytes",
        }
        try:
            uuid.UUID(str(result.get("artifact_id") or ""))
        except ValueError:
            if result.get("artifact_id"):
                legacy += 1
            continue
        if not required.issubset(result):
            legacy += 1
            continue
        eligible += 1
        outcome = service.reconcile_task(
            site_name,
            ArtifactTaskBinding(
                task_id=str(row["task_id"]),
                task_type=str(row["task_type"]),
                owner=str(row["owner"]),
                status=str(row["status"]),
                result=result,
                downloadable=True,
            ),
            verify_digest=True,
        )
        states[outcome.artifact_availability.value] += 1
    return {
        "eligible_managed_manifest_refs": eligible,
        "legacy_or_incomplete_artifact_refs": legacy,
        "states": dict(sorted(states.items())),
    }


def _task_contract(database: Path, archived_rows: list[dict[str, Any]]) -> dict[str, object]:
    profile = _sqlite_profile(database)
    with _readonly_connection(database) as connection:
        invalid_results = 0
        for row in connection.execute(
            "SELECT canonical_json,sha256,byte_size FROM task_results"
        ):
            encoded = str(row[0]).encode("utf-8")
            if hashlib.sha256(encoded).hexdigest() != str(row[1]) or len(encoded) != int(row[2]):
                invalid_results += 1
        missing_result_refs = int(
            connection.execute(
                "SELECT COUNT(*) FROM task_snapshots s LEFT JOIN task_results r "
                "ON r.result_id=s.result_id WHERE s.result_id<>'' AND r.result_id IS NULL"
            ).fetchone()[0]
        )
        mappings = [
            tuple(row)
            for row in connection.execute(
                "SELECT controller_task_id,session_id,site_id,mr_id,phase,mapping_state,"
                "executor_kind,agent_task_id,remote_session_id,remote_package_id "
                "FROM online_mr_task_sessions ORDER BY controller_task_id"
            )
        ]
    repository = TaskRepository(database)
    archived_by_task: dict[str, set[str]] = defaultdict(set)
    for row in archived_rows:
        archived_by_task[str(row["task_id"])].add(str(row["event_id"]))
    task_ids = sorted(archived_by_task)
    samples = (
        task_ids[:4]
        + task_ids[max(0, len(task_ids) // 2 - 2) : len(task_ids) // 2 + 2]
        + task_ids[-4:]
    )
    api_rows = repository.list_events_for_tasks(samples)
    missing_sample_events = 0
    for task_id in samples:
        actual = {str(row["id"]) for row in api_rows.get(task_id, [])}
        missing_sample_events += len(archived_by_task[task_id] - actual)
    missing_mapping_tasks = sum(repository.get(str(row[0])) is None for row in mappings)
    result_rows = []
    with _readonly_connection(database) as connection:
        result_rows = [
            str(row[0])
            for row in connection.execute(
                "SELECT result_id FROM task_results ORDER BY result_id LIMIT 50"
            )
        ]
    missing_api_results = sum(repository.get_result(result_id) is None for result_id in result_rows)
    history_counts = repository.task_history.counts()
    return {
        "profile": profile,
        "invalid_canonical_results": invalid_results,
        "missing_result_refs": missing_result_refs,
        "online_mr_mapping_count": len(mappings),
        "online_mr_mapping_digest": _stable_digest(mappings),
        "online_mr_missing_tasks": missing_mapping_tasks,
        "task_history_counts": history_counts,
        "task_history_sample_tasks": len(samples),
        "task_history_sample_missing_events": missing_sample_events,
        "task_result_api_samples": len(result_rows),
        "task_result_api_missing": missing_api_results,
    }


def _new_legacy_site_root(paths: PathResolver, site_name: str) -> Path:
    site_root = paths.site_dir(site_name)
    database = paths.site_db_path(site_name)
    database.parent.mkdir(parents=True, exist_ok=True)
    Database(database).initialize()
    _atomic_json(
        site_root / "site_meta.json",
        {
            "display_name": site_name,
            "line_name": site_name,
            "system_type": "integrated-site-package-rehearsal",
            "schema_version": 1,
            "sync_schema_version": 1,
            "revision": 1,
        },
    )
    return site_root


def _staging_entries(paths: PathResolver) -> list[str]:
    if not paths.temp_dir.exists():
        return []
    result: list[str] = []
    for item in paths.temp_dir.rglob("*"):
        relative = item.relative_to(paths.temp_dir)
        if item.name.startswith("netconsole-"):
            result.append(relative.as_posix())
            continue
        try:
            staging_index = relative.parts.index("site-import-staging")
        except ValueError:
            continue
        if len(relative.parts) > staging_index + 1:
            result.append(relative.as_posix())
    return sorted(result)


def run(args: argparse.Namespace) -> dict[str, object]:
    run_root = _require_development_path(Path(args.run_root), label="run root")
    diagnostic_root = _require_development_path(
        Path(args.diagnostic_root), label="diagnostic root"
    )
    registry_path = Path(args.storage_registry).resolve()
    stores = _load_site_storage_registry(registry_path)
    workspace = _require_inside(Path(args.workspace), run_root, label="workspace")
    output = _require_inside(Path(args.output), diagnostic_root, label="output")
    package = _require_inside(Path(args.package), workspace, label="package")
    for label, mutable_path in (
        ("workspace", workspace),
        ("output", output),
        ("package", package),
    ):
        _require_development_path(mutable_path, label=label)
    if workspace.exists():
        raise FileExistsError(f"workspace already exists: {workspace}")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    sources = {
        "devices": _require_inside(Path(args.devices_database), run_root, label="devices database"),
        "tasks": _require_inside(Path(args.tasks_database), run_root, label="tasks database"),
        "task_events": _require_inside(Path(args.task_event_source), run_root, label="task event source"),
        "device_history": _require_inside(Path(args.device_history_root), run_root, label="device history root"),
        "task_plan": Path(args.task_plan).resolve(),
    }
    artifact_source = Path(args.artifact_source_site_root).resolve()
    if any(_inside(workspace, source) or _inside(source, workspace) for source in sources.values()):
        raise ValueError("workspace must not overlap source rehearsal data")
    if _inside(workspace, artifact_source) or _inside(output, artifact_source):
        raise ValueError("outputs must not be inside the read-only artifact source")
    if not all(path.exists() for path in sources.values()) or not artifact_source.is_dir():
        raise FileNotFoundError("one or more required sources are missing")

    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_STORAGE_MODE"] = "persistent"
    site_name = str(args.site_name)
    source_root = workspace / "source-data-root"
    target_root = workspace / "imported-data-root"
    failure_root = workspace / "failed-import-data-root"
    interruption_root = workspace / "interrupted-import-data-root"
    source_paths = PathResolver(data_root=source_root)
    source_site = source_paths.site_dir(site_name)
    source_site.mkdir(parents=True)
    source_db_dir = source_site / "db"
    source_db_dir.mkdir(parents=True)

    source_hashes_before = {
        name: _sha256(path)
        for name, path in sources.items()
        if path.is_file() and name != "task_plan"
    }
    copies = {
        "devices": _sqlite_backup(sources["devices"], source_db_dir / "devices.db"),
        "tasks": _sqlite_backup(sources["tasks"], source_db_dir / "tasks.db"),
        "history": {},
    }
    history_target = source_db_dir / "history"
    history_target.mkdir(parents=True)
    for history_database in sorted(sources["device_history"].glob("*.db")):
        copies["history"][history_database.name] = _sqlite_backup(
            history_database,
            history_target / history_database.name,
        )
    registry_copy = _copy_registered_package_authorities(
        artifact_source,
        source_site,
        stores,
    )
    _atomic_json(
        source_site / "site_meta.json",
        {
            "display_name": site_name,
            "line_name": site_name,
            "system_type": "integrated-site-package-rehearsal",
            "schema_version": 1,
            "sync_schema_version": 1,
            "revision": 1,
        },
    )
    source_task_rows = _canonical_task_rows(source_db_dir / "tasks.db")
    artifact_copy = _copy_artifact_authorities(
        source_task_rows,
        source_site_root=artifact_source,
        target_site_root=source_site,
    )
    source_sites = SiteApplicationService(source_paths)
    source_record = source_sites.registry.get_by_directory_name(site_name)

    plan = json.loads(sources["task_plan"].read_text(encoding="utf-8"))
    sequences = _expand_integer_ranges(plan["archive_event_sequence_ranges"])
    if _stable_digest(sequences) != str(plan["archive_event_sequence_digest"]):
        raise ValueError("task archive sequence digest mismatch")
    archived_rows = _rows_by_sequence(sources["task_events"], sequences)
    if TaskHistoryStore.source_row_digest(archived_rows) != str(
        plan["archive_event_content_digest"]
    ):
        raise ValueError("task archive content digest mismatch")
    history = TaskHistoryStore(
        source_db_dir / "tasks.db",
        site_id=source_record.site_id,
        history_root=history_target,
    )
    inserted, verified = history.archive_event_rows(archived_rows)
    if verified != len(archived_rows):
        raise sqlite3.DatabaseError("task archive verification count mismatch")
    sealed = history.store.seal_open_shards()
    repeated_inserted, repeated_verified = history.archive_event_rows(archived_rows)
    if repeated_inserted or repeated_verified != len(archived_rows):
        raise sqlite3.DatabaseError("task archive idempotency verification failed")

    source_identity = _ap_identity_contract(
        source_db_dir / "devices.db",
        reason="integrated_site_package_source_restart",
    )
    source_devices = _sqlite_profile(source_db_dir / "devices.db")
    source_tasks = _task_contract(source_db_dir / "tasks.db", archived_rows)
    source_history = _history_summary(history_target)
    source_artifacts = _artifact_reconciliation(source_paths, site_name, source_task_rows)
    source_registered = _registered_authority_profile(source_site, stores)

    package.parent.mkdir(parents=True, exist_ok=True)
    export_result = SitePackageService(source_paths, source_sites).export_site(
        source_record.site_id,
        package,
        package_type=FULL_MIGRATION,
    )
    package_info = SitePackageService(source_paths, source_sites).inspect_package(package)
    registered_export = _registered_export_contract(
        source_registered,
        _package_manifest_members(package),
    )
    source_staging = _staging_entries(source_paths)

    target_paths = PathResolver(data_root=target_root)
    _new_legacy_site_root(target_paths, site_name)
    target_sites = SiteApplicationService(target_paths)
    target_record = target_sites.registry.get_by_directory_name(site_name)
    import_result = SitePackageService(target_paths, target_sites).import_site(
        package,
        replace_site_id=target_record.site_id,
        display_name=site_name,
    )
    target_staging = _staging_entries(target_paths)

    del target_sites
    gc.collect()
    restarted_paths = PathResolver(data_root=target_root)
    restarted_sites = SiteApplicationService(restarted_paths)
    restarted_record = restarted_sites.registry.get(target_record.site_id)
    imported_site = restarted_record.root_path
    imported_tasks_path = imported_site / "db" / "tasks.db"
    imported_history_root = imported_site / "db" / "history"
    imported_task_rows = _canonical_task_rows(imported_tasks_path)
    target_identity = _ap_identity_contract(
        imported_site / "db" / "devices.db",
        reason="integrated_site_package_import_restart",
    )
    target_devices = _sqlite_profile(imported_site / "db" / "devices.db")
    target_tasks = _task_contract(imported_tasks_path, archived_rows)
    target_history = _history_summary(imported_history_root)
    target_artifacts = _artifact_reconciliation(
        restarted_paths,
        restarted_record.root_path.name,
        imported_task_rows,
    )
    target_registered = _registered_authority_profile(imported_site, stores)
    registered_parity = _registered_authority_parity(
        source_registered,
        target_registered,
    )

    failure_paths = PathResolver(data_root=failure_root)
    failure_site = _new_legacy_site_root(failure_paths, site_name)
    failure_registry_copy = _copy_registered_package_authorities(
        source_site,
        failure_site,
        stores,
    )
    failure_registered_before = _registered_authority_profile(failure_site, stores)
    marker = failure_site / "preexisting-marker.txt"
    marker.write_text("must-survive-failed-import", encoding="ascii")
    failure_sites = SiteApplicationService(failure_paths)
    failure_record = failure_sites.registry.get_by_directory_name(site_name)

    def fail_registry_publish(_record: object) -> None:
        raise RuntimeError("forced registry publish failure")

    failure_sites.registry.register = fail_registry_publish  # type: ignore[method-assign]
    failure_code = ""
    try:
        SitePackageService(failure_paths, failure_sites).import_site(
            package,
            replace_site_id=failure_record.site_id,
            display_name=site_name,
        )
    except SiteStorageError as exc:
        failure_code = exc.code
    if failure_code != "SITE_IMPORT_FAILED":
        raise RuntimeError("forced Site Package import failure did not fail closed")
    failure_staging = _staging_entries(failure_paths)
    failure_recovered = marker.read_text(encoding="ascii") == "must-survive-failed-import"
    failure_registered_after = _registered_authority_profile(failure_site, stores)
    failure_sync_parity = _registered_store_subset_parity(
        failure_registered_before,
        failure_registered_after,
        _FULL_MIGRATION_SYNC_STORE_IDS,
    )

    interruption_paths = PathResolver(data_root=interruption_root)
    interruption_site = _new_legacy_site_root(interruption_paths, site_name)
    interruption_marker = interruption_site / "preexisting-marker.txt"
    interruption_marker.write_text(
        "must-survive-interrupted-import", encoding="ascii"
    )
    interruption_sites = SiteApplicationService(interruption_paths)
    interruption_packages = SitePackageService(
        interruption_paths, interruption_sites
    )
    internal_staging = (
        interruption_paths.temp_dir / "netconsole-site-export-interrupted"
    )
    internal_staging.mkdir(parents=True)
    (internal_staging / "devices.db").write_bytes(b"interrupted")
    import_staging = (
        interruption_paths.temp_dir
        / "site-import-staging"
        / "interrupted"
    )
    import_staging.mkdir(parents=True)
    (import_staging / "tasks.db").write_bytes(b"interrupted")
    interrupted_destination = workspace / "interrupted-publish.ncsite"
    interrupted_publish, _publish_journal = (
        interruption_packages.staging_lifecycle.begin_publish_path(
            interrupted_destination
        )
    )
    interrupted_publish.write_bytes(b"partial-package")
    interruption_backup = (
        interruption_paths.archive_dir
        / f"site-import-{interruption_site.name}-{uuid.uuid4().hex}"
    )
    interruption_backup.parent.mkdir(parents=True)
    replacement_journal = (
        interruption_packages.staging_lifecycle.begin_site_replacement(
            interruption_site, interruption_backup
        )
    )
    os.replace(interruption_site, interruption_backup)
    interruption_packages.staging_lifecycle.mark_site_replacement(
        replacement_journal, "BACKUP_PUBLISHED"
    )
    interruption_recovery = interruption_packages.recover_orphaned_staging()
    interruption_staging = _staging_entries(interruption_paths)
    interruption_recovered = (
        interruption_recovery.status == "PASS"
        and interruption_marker.read_text(encoding="ascii")
        == "must-survive-interrupted-import"
        and interruption_recovery.restored_site_imports == 1
        and interruption_recovery.removed_publish_files == 1
        and interruption_recovery.removed_internal_entries >= 2
        and not interruption_staging
        and not interrupted_publish.exists()
    )

    source_hashes_after = {
        name: _sha256(path)
        for name, path in sources.items()
        if path.is_file() and name != "task_plan"
    }
    operational_parity = {
        "devices_schema": source_devices["schema_digest"] == target_devices["schema_digest"],
        "devices_rows": source_devices["table_counts"] == target_devices["table_counts"],
        "tasks_schema": source_tasks["profile"]["schema_digest"]
        == target_tasks["profile"]["schema_digest"],
        "tasks_rows": source_tasks["profile"]["table_counts"]
        == target_tasks["profile"]["table_counts"],
        "online_mr": source_tasks["online_mr_mapping_digest"]
        == target_tasks["online_mr_mapping_digest"],
        "ap_identity_ready": source_identity["status"] == "ready"
        and target_identity["status"] == "ready",
        "ap_identity_initialize_revision": source_identity[
            "source_revision_preserved_by_initialize"
        ]
        and target_identity["source_revision_preserved_by_initialize"],
        "ap_identity_queries": source_identity["semantic_digest"]
        == target_identity["semantic_digest"],
    }
    authority_parity = {
        "history_semantic": source_history["semantic_digest"]
        == target_history["semantic_digest"],
        "task_history_counts": source_tasks["task_history_counts"]
        == target_tasks["task_history_counts"],
        "task_results": target_tasks["invalid_canonical_results"] == 0
        and target_tasks["missing_result_refs"] == 0,
        "artifact_manifest_refs": source_artifacts == target_artifacts,
        "registered_package_contract": registered_export["status"] == "PASS",
        "registered_storage": registered_parity["status"] == "PASS",
        "failure_sync_rollback": failure_sync_parity["status"] == "PASS",
        "registered_artifact_refs": source_registered["artifact_reference_count"]
        == target_registered["artifact_reference_count"],
        "source_snapshots_unchanged": source_hashes_before == source_hashes_after,
    }
    cleanup = {
        "export_success": not source_staging,
        "import_success": not target_staging,
        "import_failure": not failure_staging,
        "failure_rollback": failure_recovered,
        "interruption_recovery": interruption_recovered,
    }
    api = {
        "task_history": target_tasks["task_history_sample_missing_events"] == 0,
        "task_results": target_tasks["task_result_api_missing"] == 0,
        "online_mr": target_tasks["online_mr_missing_tasks"] == 0,
    }
    passed = (
        all(operational_parity.values())
        and all(authority_parity.values())
        and all(cleanup.values())
        and all(api.values())
        and int(target_tasks["task_history_counts"]["task_events"])
        == len(archived_rows)
    )
    generator = _evidence_binding(Path(__file__).resolve())
    result = {
        "format": "netconsole-integrated-site-package-validation-v1",
        "status": "PASS" if passed else "FAIL",
        "git_head": generator["git_head"],
        "generator": generator,
        "scope": {
            "site_id": source_record.site_id,
            "physical_directory": site_name,
            "package_type": FULL_MIGRATION,
            "source_originals_read_only": True,
            "production_mutations": 0,
            "restore_mode": "replace_same_stable_site_and_physical_directory",
            "import_as_new_identity_remapping": "EXISTING_BOUNDARY_NOT_EXERCISED",
        },
        "package": {
            "path": str(package),
            "size_bytes": package.stat().st_size,
            "sha256": _sha256(package),
            "export": export_result,
            "inspect": package_info,
            "import": import_result,
        },
        "shared_history_merge": {
            "requested_events": len(archived_rows),
            "inserted_events": inserted,
            "verified_events": verified,
            "idempotent_inserted_events": repeated_inserted,
            "idempotent_verified_events": repeated_verified,
            "sealed_shards": sealed,
        },
        "source": {
            "data_root": str(source_root),
            "devices": source_devices,
            "ap_identity": source_identity,
            "tasks": source_tasks,
            "history": source_history,
            "artifacts": source_artifacts,
            "artifact_copy": artifact_copy,
            "registered_storage": source_registered,
            "registry_copy": registry_copy,
        },
        "imported": {
            "data_root": str(target_root),
            "devices": target_devices,
            "ap_identity": target_identity,
            "tasks": target_tasks,
            "history": target_history,
            "artifacts": target_artifacts,
            "registered_storage": target_registered,
            "restart": "PASS",
        },
        "parity": {
            "operational": operational_parity,
            "authorities": authority_parity,
            "registered_storage": registered_parity,
            "repository_api": api,
        },
        "storage_registry": {
            "path": str(registry_path),
            "sha256": _sha256(registry_path),
            "site_store_count": len(stores),
            "package_contract": registered_export,
        },
        "staging_cleanup": {
            **cleanup,
            "source_remaining": source_staging,
            "target_remaining": target_staging,
            "failure_remaining": failure_staging,
            "forced_failure_code": failure_code,
            "failure_registered_copy": failure_registry_copy,
            "failure_sync_parity": failure_sync_parity,
            "interruption_recovery": interruption_recovery.to_dict(),
            "interruption_remaining": interruption_staging,
        },
        "source_hashes": {
            "before": source_hashes_before,
            "after": source_hashes_after,
        },
        "limitations": [
            "Full migration restore was exercised against the same stable site identity and physical directory; import-as-new identity remapping is an existing product boundary outside this rehearsal.",
            "Legacy absolute result paths are evidence only, not package authority; managed Artifact manifests and relative files are reconciled separately.",
        ],
    }
    _atomic_json(output, result)
    if not passed:
        raise RuntimeError(f"integrated Site Package validation failed; see {output}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a shared devices/task History authority through a FULL Site Package round trip."
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--diagnostic-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--devices-database", type=Path, required=True)
    parser.add_argument("--tasks-database", type=Path, required=True)
    parser.add_argument("--device-history-root", type=Path, required=True)
    parser.add_argument("--task-event-source", type=Path, required=True)
    parser.add_argument("--task-plan", type=Path, required=True)
    parser.add_argument("--artifact-source-site-root", type=Path, required=True)
    parser.add_argument(
        "--storage-registry",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config" / "storage_registry.yaml",
    )
    parser.add_argument("--site-name", required=True)
    return parser


def main() -> int:
    result = run(build_parser().parse_args())
    print(json.dumps({"status": result["status"], "package": result["package"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
