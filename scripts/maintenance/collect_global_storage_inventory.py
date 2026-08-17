from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


INVENTORY_SCOPE = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
SITE_INVENTORY_SCOPE = "SITE_ROOT"
SQLITE_HEADER = b"SQLite format 3\x00"
UNKNOWN_CLASS = "UNKNOWN"
UNKNOWN_POLICY = "PROTECT"
LARGE_VALUE_THRESHOLD_BYTES = 4096
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CONTENT_COLUMN_MARKERS = (
    "blob",
    "body",
    "config",
    "content",
    "details",
    "json",
    "message",
    "payload",
    "raw",
    "result",
    "snapshot",
    "text",
)
_IDENTITY_COLUMN_NAMES = {
    "artifact_id",
    "artifact_ref",
    "event_id",
    "hash",
    "result_id",
    "run_id",
    "session_id",
    "sha256",
    "source_hash",
    "source_id",
    "task_id",
}


class GlobalStorageInventoryError(RuntimeError):
    pass


class InventoryChangedError(GlobalStorageInventoryError):
    pass


@dataclass(frozen=True)
class _FileSnapshot:
    relative_path: str
    path: Path
    bytes: int
    mtime_ns: int

    @classmethod
    def from_stat(
        cls, *, relative_path: str, path: Path, value: os.stat_result
    ) -> _FileSnapshot:
        return cls(
            relative_path=relative_path,
            path=path,
            bytes=int(value.st_size),
            mtime_ns=int(value.st_mtime_ns),
        )

    def identity(self) -> tuple[int, int]:
        return self.bytes, self.mtime_ns


def collect_data_root_global_inventory(data_root: str | Path) -> dict[str, Any]:
    """Collect a read-only data-root inventory while excluding ``sites/**``."""

    return _collect_storage_inventory(
        data_root,
        inventory_scope=INVENTORY_SCOPE,
        exclude_sites=True,
    )


def collect_site_storage_inventory(site_root: str | Path) -> dict[str, Any]:
    """Collect a read-only inventory of one exact registered site root."""

    return _collect_storage_inventory(
        site_root,
        inventory_scope=SITE_INVENTORY_SCOPE,
        exclude_sites=False,
    )


def _collect_storage_inventory(
    source_root: str | Path,
    *,
    inventory_scope: str,
    exclude_sites: bool,
) -> dict[str, Any]:
    """Profile one filesystem tree without following links or writing beside it."""

    root = _validated_data_root(source_root)
    started = time.monotonic()
    before, skipped_before = _snapshot_files(root, exclude_sites=exclude_sites)
    files: list[dict[str, Any]] = []
    databases: list[dict[str, Any]] = []
    zip_archives: list[dict[str, Any]] = []
    for snapshot in before:
        record = _profile_file(snapshot)
        files.append(record)
        if record["sqlite_header"]:
            databases.append(_profile_sqlite(snapshot, record))
        if record["zip_header"]:
            zip_archives.append(_profile_zip(snapshot))

    after, skipped_after = _snapshot_files(root, exclude_sites=exclude_sites)
    verification = _compare_snapshots(before, after)
    if not verification["unchanged"]:
        raise InventoryChangedError(
            "data root changed during inventory; refusing to publish mixed evidence"
        )
    if skipped_before != skipped_after:
        raise InventoryChangedError(
            "excluded or unsafe entries changed during inventory"
        )

    duplicate_groups = _duplicate_file_groups(files)
    total_bytes = sum(int(item["bytes"]) for item in files)
    sqlite_bytes = sum(int(item["bytes"]) for item in databases)
    return {
        "schema_version": 1,
        "inventory_scope": inventory_scope,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "site_root": str(root),
        "safety_contract": {
            "production_access": "READ_ONLY",
            "writes_to_data_root": 0,
            "sqlite_open_contract": "mode=ro&immutable=1",
            "sites_excluded": exclude_sites,
            "symlinks_and_reparse_points_followed": False,
            "unknown_policy": UNKNOWN_POLICY,
        },
        "totals": {
            "files": len(files),
            "bytes": total_bytes,
            "sqlite_files_by_header": len(databases),
            "sqlite_bytes": sqlite_bytes,
            "exact_duplicate_groups": len(duplicate_groups),
            "exact_duplicate_bytes": sum(
                int(item["duplicate_bytes"]) for item in duplicate_groups
            ),
        },
        "by_top_level": _group_files(files, key="top_level"),
        "by_extension": _group_files(files, key="extension"),
        "by_classification": [
            {
                "classification": UNKNOWN_CLASS,
                "files": len(files),
                "bytes": total_bytes,
            }
        ],
        "duplicate_groups": duplicate_groups,
        "zip_archives": zip_archives,
        "sqlite_databases": databases,
        "files": files,
        "skipped_entries": skipped_before,
        "production_metadata_verification": verification,
        "elapsed_seconds": round(time.monotonic() - started, 6),
    }


def _validated_data_root(value: str | Path) -> Path:
    root = Path(value).expanduser()
    root = Path(os.path.abspath(os.fspath(root)))
    if not root.is_dir():
        raise GlobalStorageInventoryError(f"data root is not a directory: {root}")
    for component in [*reversed(root.parents), root]:
        if component == Path(component.anchor):
            continue
        try:
            metadata = component.lstat()
        except OSError as exc:
            raise GlobalStorageInventoryError(
                f"cannot inspect data-root boundary: {component}"
            ) from exc
        if _is_reparse_stat(metadata):
            raise GlobalStorageInventoryError(
                f"data root may not traverse a symlink or reparse point: {component}"
            )
    return root.resolve(strict=True)


def _snapshot_files(
    root: Path,
    *,
    exclude_sites: bool = True,
) -> tuple[list[_FileSnapshot], list[dict[str, str]]]:
    files: list[_FileSnapshot] = []
    skipped: list[dict[str, str]] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            raise GlobalStorageInventoryError(
                f"cannot enumerate data-root directory: {directory}"
            ) from exc
        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if exclude_sites and directory == root and entry.name.casefold() == "sites":
                skipped.append({"path": relative, "reason": "SITES_EXCLUDED"})
                continue
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise GlobalStorageInventoryError(
                    f"cannot inspect data-root entry: {relative}"
                ) from exc
            if _is_reparse_entry(entry, metadata):
                skipped.append(
                    {"path": relative, "reason": "SYMLINK_OR_REPARSE_POINT"}
                )
                continue
            if stat.S_ISDIR(metadata.st_mode):
                child_directories.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(
                    _FileSnapshot.from_stat(
                        relative_path=relative,
                        path=path,
                        value=metadata,
                    )
                )
            else:
                skipped.append({"path": relative, "reason": "SPECIAL_FILE"})
        pending.extend(reversed(child_directories))
    return (
        sorted(files, key=lambda item: item.relative_path.casefold()),
        sorted(skipped, key=lambda item: item["path"].casefold()),
    )


def _is_reparse_entry(entry: os.DirEntry[str], metadata: os.stat_result) -> bool:
    return entry.is_symlink() or _is_reparse_stat(metadata)


def _is_reparse_stat(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & _REPARSE_POINT)


def _profile_file(snapshot: _FileSnapshot) -> dict[str, Any]:
    digest = hashlib.sha256()
    header = b""
    try:
        with snapshot.path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if not header:
                    header = chunk[:16]
                digest.update(chunk)
    except OSError as exc:
        raise InventoryChangedError(
            f"cannot read inventoried file: {snapshot.relative_path}"
        ) from exc
    _assert_snapshot_unchanged(snapshot)
    suffix = snapshot.path.suffix.casefold()
    return {
        "path": snapshot.relative_path,
        "bytes": snapshot.bytes,
        "mtime_ns": snapshot.mtime_ns,
        "mtime_utc": datetime.fromtimestamp(
            snapshot.mtime_ns / 1_000_000_000, UTC
        ).isoformat(timespec="microseconds"),
        "classification": UNKNOWN_CLASS,
        "classification_basis": "raw global inventory; owner registry resolves authority",
        "protection": UNKNOWN_POLICY,
        "top_level": snapshot.relative_path.split("/", 1)[0],
        "extension": suffix,
        "sqlite_header": header.startswith(SQLITE_HEADER),
        "zip_header": header.startswith(
            (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
        ),
        "sha256": digest.hexdigest(),
        "sha256_source": "COMPUTED",
    }


def _assert_snapshot_unchanged(snapshot: _FileSnapshot) -> None:
    try:
        metadata = snapshot.path.stat(follow_symlinks=False)
    except OSError as exc:
        raise InventoryChangedError(
            f"inventoried file disappeared: {snapshot.relative_path}"
        ) from exc
    if _is_reparse_stat(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise InventoryChangedError(
            f"inventoried file changed type: {snapshot.relative_path}"
        )
    current = _FileSnapshot.from_stat(
        relative_path=snapshot.relative_path,
        path=snapshot.path,
        value=metadata,
    )
    if current.identity() != snapshot.identity():
        raise InventoryChangedError(
            f"inventoried file changed while reading: {snapshot.relative_path}"
        )


def _profile_sqlite(
    snapshot: _FileSnapshot, file_record: Mapping[str, Any]
) -> dict[str, Any]:
    started = time.monotonic()
    profile: dict[str, Any] = {
        "path": snapshot.relative_path,
        "bytes": snapshot.bytes,
        "sha256": file_record["sha256"],
        "open_contract": "mode=ro&immutable=1",
        "profile_status": "PASS",
        "database_pragmas": {
            "page_size": 0,
            "page_count": 0,
            "freelist_count": 0,
        },
        "dbstat_available": False,
        "dbstat_error": "",
        "schema_objects": [],
        "tables": [],
        "summary": {"rows": 0},
    }
    wal_path = snapshot.path.with_name(f"{snapshot.path.name}-wal")
    try:
        wal_bytes = wal_path.stat(follow_symlinks=False).st_size if wal_path.exists() else 0
    except OSError as exc:
        profile["profile_status"] = "ERROR_PROTECT"
        profile["profile_error"] = f"cannot inspect WAL sidecar: {exc.__class__.__name__}: {exc}"
        return profile
    profile["wal_sidecar_bytes"] = int(wal_bytes)
    if wal_bytes:
        profile["profile_status"] = "ERROR_PROTECT"
        profile["profile_error"] = (
            "non-empty WAL sidecar is excluded by immutable read contract; "
            "current database view is protected"
        )
        return profile
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{snapshot.path.as_uri()}?mode=ro&immutable=1",
            uri=True,
            timeout=2,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA temp_store=MEMORY")
        profile["database_pragmas"] = {
            "page_size": int(connection.execute("PRAGMA page_size").fetchone()[0]),
            "page_count": int(connection.execute("PRAGMA page_count").fetchone()[0]),
            "freelist_count": int(
                connection.execute("PRAGMA freelist_count").fetchone()[0]
            ),
        }
        schema_rows = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        profile["schema_objects"] = [dict(row) for row in schema_rows]
        dbstat_error = ""
        try:
            connection.execute("SELECT name FROM dbstat LIMIT 1").fetchone()
            profile["dbstat_available"] = True
        except sqlite3.Error as exc:
            dbstat_error = f"{exc.__class__.__name__}: {exc}"
        profile["dbstat_error"] = dbstat_error
        tables = []
        for row in schema_rows:
            if str(row["type"]) != "table":
                continue
            tables.append(
                _profile_table(
                    connection,
                    table_name=str(row["name"]),
                    create_sql=str(row["sql"] or ""),
                    dbstat_available=bool(profile["dbstat_available"]),
                )
            )
        profile["tables"] = tables
        profile["summary"] = {
            "rows": sum(int(table["rows"]) for table in tables),
            "tables": len(tables),
        }
    except sqlite3.Error as exc:
        profile["profile_status"] = "ERROR_PROTECT"
        profile["profile_error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        if connection is not None:
            connection.close()
    _assert_snapshot_unchanged(snapshot)
    profile["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return profile


def _profile_table(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    create_sql: str,
    dbstat_available: bool,
) -> dict[str, Any]:
    quoted_table = _quote_identifier(table_name)
    columns = _table_columns(connection, table_name)
    indexes = _table_indexes(connection, table_name, dbstat_available)
    row_count = int(
        connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0]
    )
    content_indexes = {
        index
        for index, column in enumerate(columns)
        if _is_content_column(str(column["name"]), str(column["type"] or ""))
    }
    identity_indexes = {
        index
        for index, column in enumerate(columns)
        if _is_identity_column(str(column["name"]))
    }
    content_values: dict[int, int] = defaultdict(int)
    content_bytes: dict[int, int] = defaultdict(int)
    content_hashes: dict[int, set[bytes]] = defaultdict(set)
    identity_hashes: dict[int, set[bytes]] = defaultdict(set)
    row_hashes: Counter[bytes] = Counter()
    text_bytes = 0
    blob_bytes = 0
    max_text_or_blob = 0
    large_text_values = 0
    large_text_bytes = 0
    large_blob_values = 0
    large_blob_bytes = 0
    observed_rows = 0
    selected = ",".join(
        _quote_identifier(str(column["name"])) for column in columns
    )
    for row in connection.execute(f"SELECT {selected} FROM {quoted_table}"):
        observed_rows += 1
        row_digest = hashlib.sha256()
        for index, value in enumerate(row):
            marker, payload = _encoded_value(value)
            row_digest.update(marker)
            row_digest.update(len(payload).to_bytes(8, "big"))
            row_digest.update(payload)
            if isinstance(value, str):
                text_bytes += len(payload)
                max_text_or_blob = max(max_text_or_blob, len(payload))
                if len(payload) >= LARGE_VALUE_THRESHOLD_BYTES:
                    large_text_values += 1
                    large_text_bytes += len(payload)
            elif isinstance(value, bytes):
                blob_bytes += len(payload)
                max_text_or_blob = max(max_text_or_blob, len(payload))
                if len(payload) >= LARGE_VALUE_THRESHOLD_BYTES:
                    large_blob_values += 1
                    large_blob_bytes += len(payload)
            if index in content_indexes and value is not None:
                content_values[index] += 1
                content_bytes[index] += len(payload)
                content_hashes[index].add(hashlib.sha256(marker + payload).digest())
            if index in identity_indexes and value is not None:
                identity_hashes[index].add(hashlib.sha256(marker + payload).digest())
        row_hashes[row_digest.digest()] += 1
    if observed_rows != row_count:
        raise InventoryChangedError(
            f"SQLite row count changed while profiling table {table_name}"
        )
    aggregate = hashlib.sha256()
    for digest, count in sorted(row_hashes.items()):
        aggregate.update(digest)
        aggregate.update(count.to_bytes(8, "big"))

    time_ranges: dict[str, dict[str, Any]] = {}
    for column in columns:
        name = str(column["name"])
        if not _is_time_column(name):
            continue
        quoted_column = _quote_identifier(name)
        minimum, maximum = connection.execute(
            f"SELECT MIN({quoted_column}),MAX({quoted_column}) FROM {quoted_table}"
        ).fetchone()
        time_ranges[name] = {
            "min": _json_scalar(minimum),
            "max": _json_scalar(maximum),
        }

    content_columns = {}
    identity_columns = {}
    for index, column in enumerate(columns):
        name = str(column["name"])
        if index in content_indexes:
            distinct = len(content_hashes[index])
            content_columns[name] = {
                "bytes": content_bytes[index],
                "duplicate_values": max(0, content_values[index] - distinct),
                "distinct_hashes": distinct,
            }
        if index in identity_indexes:
            identity_columns[name] = {"distinct": len(identity_hashes[index])}

    table_dbstat = None
    if dbstat_available:
        pages, size = connection.execute(
            "SELECT COUNT(*),COALESCE(SUM(pgsize),0) FROM dbstat WHERE name=?",
            (table_name,),
        ).fetchone()
        table_dbstat = {"pages": int(pages), "bytes": int(size)}
    return {
        "name": table_name,
        "sql": create_sql,
        "columns": columns,
        "indexes": indexes,
        "dbstat": table_dbstat,
        "classification": UNKNOWN_CLASS,
        "classification_reason": "raw audit requires storage owner map",
        "rows": row_count,
        "logical_payload": {
            "text_bytes": text_bytes,
            "blob_bytes": blob_bytes,
            "max_text_or_blob_bytes": max_text_or_blob,
            "large_value_threshold_bytes": LARGE_VALUE_THRESHOLD_BYTES,
            "large_text_values": large_text_values,
            "large_text_bytes": large_text_bytes,
            "large_blob_values": large_blob_values,
            "large_blob_bytes": large_blob_bytes,
        },
        "content_columns": content_columns,
        "time_ranges": time_ranges,
        "identity_columns": identity_columns,
        "duplicate_content": {
            "row_content_sha256": aggregate.hexdigest(),
            "duplicate_rows": sum(count - 1 for count in row_hashes.values()),
            "duplicate_rows_method": "EXACT_ROW_SHA256",
        },
    }


def _table_columns(
    connection: sqlite3.Connection, table_name: str
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"PRAGMA table_xinfo({_quote_identifier(table_name)})"
    ).fetchall()
    return [
        {
            "cid": int(row["cid"]),
            "name": str(row["name"]),
            "type": str(row["type"] or ""),
            "not_null": bool(row["notnull"]),
            "default": _json_scalar(row["dflt_value"]),
            "primary_key_position": int(row["pk"]),
            "hidden": int(row["hidden"]),
        }
        for row in rows
    ]


def _table_indexes(
    connection: sqlite3.Connection,
    table_name: str,
    dbstat_available: bool,
) -> list[dict[str, Any]]:
    result = []
    for row in connection.execute(
        f"PRAGMA index_list({_quote_identifier(table_name)})"
    ):
        name = str(row["name"])
        columns = [
            _json_scalar(item["name"])
            for item in connection.execute(
                f"PRAGMA index_info({_quote_identifier(name)})"
            )
        ]
        dbstat = None
        if dbstat_available:
            pages, size = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(pgsize),0) FROM dbstat WHERE name=?",
                (name,),
            ).fetchone()
            dbstat = {"pages": int(pages), "bytes": int(size)}
        result.append(
            {
                "name": name,
                "columns": columns,
                "unique": bool(row["unique"]),
                "origin": str(row["origin"]),
                "partial": bool(row["partial"]),
                "dbstat": dbstat,
            }
        )
    return result


def _is_content_column(name: str, declared_type: str) -> bool:
    lowered = name.casefold()
    normalized_type = declared_type.casefold()
    return "blob" in normalized_type or any(
        marker in lowered for marker in _CONTENT_COLUMN_MARKERS
    )


def _is_identity_column(name: str) -> bool:
    lowered = name.casefold()
    return lowered in _IDENTITY_COLUMN_NAMES or lowered.endswith("_sha256")


def _is_time_column(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered in {"date", "day", "month", "time", "timestamp"}
        or lowered.endswith(("_at", "_date", "_day", "_time", "_timestamp"))
    )


def _encoded_value(value: Any) -> tuple[bytes, bytes]:
    if value is None:
        return b"n", b""
    if isinstance(value, bytes):
        return b"b", value
    if isinstance(value, str):
        return b"s", value.encode("utf-8", errors="strict")
    if isinstance(value, bool):
        return b"i", b"1" if value else b"0"
    if isinstance(value, int):
        return b"i", str(value).encode("ascii")
    if isinstance(value, float):
        return b"f", repr(value).encode("ascii")
    return b"r", str(value).encode("utf-8", errors="strict")


def _json_scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"blob_sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _quote_identifier(value: str) -> str:
    if "\x00" in value:
        raise GlobalStorageInventoryError("SQLite identifier contains NUL")
    return '"' + value.replace('"', '""') + '"'


def _profile_zip(snapshot: _FileSnapshot) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": snapshot.relative_path,
        "bytes": snapshot.bytes,
        "status": "PASS",
        "members": 0,
        "compressed_bytes": 0,
        "uncompressed_bytes": 0,
    }
    try:
        with zipfile.ZipFile(snapshot.path, "r") as archive:
            members = archive.infolist()
            result.update(
                {
                    "members": len(members),
                    "compressed_bytes": sum(item.compress_size for item in members),
                    "uncompressed_bytes": sum(item.file_size for item in members),
                }
            )
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        result["status"] = "ERROR_PROTECT"
        result["error"] = f"{exc.__class__.__name__}: {exc}"
    _assert_snapshot_unchanged(snapshot)
    return result


def _compare_snapshots(
    before: Sequence[_FileSnapshot], after: Sequence[_FileSnapshot]
) -> dict[str, Any]:
    before_map = {item.relative_path: item.identity() for item in before}
    after_map = {item.relative_path: item.identity() for item in after}
    added = sorted(set(after_map) - set(before_map), key=str.casefold)
    removed = sorted(set(before_map) - set(after_map), key=str.casefold)
    changed = sorted(
        (
            path
            for path in set(before_map) & set(after_map)
            if before_map[path] != after_map[path]
        ),
        key=str.casefold,
    )
    return {
        "before_files": len(before_map),
        "after_files": len(after_map),
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": not added and not removed and not changed,
    }


def _duplicate_file_groups(files: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[str]] = defaultdict(list)
    for item in files:
        grouped[(str(item["sha256"]), int(item["bytes"]))].append(str(item["path"]))
    result = []
    for (digest, size), paths in sorted(grouped.items()):
        if len(paths) < 2:
            continue
        result.append(
            {
                "bytes_each": size,
                "sha256": digest,
                "count": len(paths),
                "duplicate_bytes": size * (len(paths) - 1),
                "paths": sorted(paths, key=str.casefold),
            }
        )
    return result


def _group_files(
    files: Sequence[Mapping[str, Any]], *, key: str
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"files": 0, "bytes": 0})
    for item in files:
        name = str(item.get(key) or "")
        grouped[name]["files"] += 1
        grouped[name]["bytes"] += int(item["bytes"])
    return [
        {key: name, **grouped[name]} for name in sorted(grouped, key=str.casefold)
    ]


def _write_output(path: Path, value: Mapping[str, Any], *, data_root: Path) -> None:
    target = Path(os.path.abspath(os.fspath(path.expanduser())))
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(data_root)
    except ValueError:
        pass
    else:
        raise GlobalStorageInventoryError("inventory output must be outside data root")
    if target.exists():
        raise FileExistsError(f"inventory output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            raise FileExistsError(f"inventory output already exists: {target}")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--scope",
        choices=("global", "site-root"),
        default="global",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = _validated_data_root(args.data_root)
    inventory = (
        collect_site_storage_inventory(root)
        if args.scope == "site-root"
        else collect_data_root_global_inventory(root)
    )
    _write_output(args.output, inventory, data_root=root)
    print(
        json.dumps(
            {
                "status": "PASS",
                "scope": inventory["inventory_scope"],
                "output": str(Path(args.output).resolve()),
                "files": inventory["totals"]["files"],
                "bytes": inventory["totals"]["bytes"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
