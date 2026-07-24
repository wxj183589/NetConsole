from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from netconsole.core.storage_manifest import CURRENT_STORAGE_SCHEMA_VERSION
from netconsole.core.version import APP_VERSION


ALLOWED_TARGET_ROOTS = frozenset({"config", "sites", "runtime", "agents", "migrations", "staging"})
DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
SKIPPED_RUNTIME_NAMES = frozenset({"locks"})


class UnifiedStorageMigrationError(RuntimeError):
    pass


class _MigrationRootLock:
    def __init__(self, target: Path) -> None:
        self.path = target / "staging" / ".unified-storage-migration.lock"

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._create()
        except FileExistsError:
            owner = _read_json(self.path)
            pid = int(owner.get("pid") or 0)
            if pid > 0 and _pid_exists(pid):
                raise UnifiedStorageMigrationError("当前数据根已有运行中的统一迁移")
            self.path.unlink(missing_ok=True)
            self._create()

    def release(self) -> None:
        self.path.unlink(missing_ok=True)

    def _create(self) -> None:
        with self.path.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": _now()}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())


@dataclass(frozen=True)
class SourceSummary:
    source_id: str
    path: str
    exists: bool
    files: int
    bytes: int
    databases: int
    latest_modified_at: str


@dataclass(frozen=True)
class FileDecision:
    source_id: str
    source_relative_path: str
    target_relative_path: str
    size: int
    sha256: str
    action: str
    conflict_relative_path: str = ""


@dataclass(frozen=True)
class DatabaseCheck:
    relative_path: str
    quick_check: str
    integrity_check: str


@dataclass
class MigrationReport:
    migration_id: str
    status: str
    target: str
    primary_source: str
    created_at: str
    completed_at: str = ""
    sources: list[SourceSummary] = field(default_factory=list)
    files: list[FileDecision] = field(default_factory=list)
    databases: list[DatabaseCheck] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        actions: dict[str, int] = {}
        bytes_by_action: dict[str, int] = {}
        for item in self.files:
            actions[item.action] = actions.get(item.action, 0) + 1
            bytes_by_action[item.action] = bytes_by_action.get(item.action, 0) + item.size
        return {
            "migration_id": self.migration_id,
            "status": self.status,
            "target": self.target,
            "primary_source": self.primary_source,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "source_count": len(self.sources),
            "database_count": len(self.databases),
            "actions": actions,
            "bytes_by_action": bytes_by_action,
        }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计并迁移 NetConsole 历史数据根")
    parser.add_argument("--target", type=Path, default=Path(r"D:\NetConsoleData"))
    parser.add_argument("--primary", type=Path)
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--desktop-bootstrap", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--recover-abandoned-staging")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def audit_sources(primary: Path, sources: Iterable[Path]) -> list[SourceSummary]:
    values: list[SourceSummary] = []
    for index, source in enumerate([primary, *sources]):
        source_id = "primary" if index == 0 else f"source-{index}"
        root = Path(source).expanduser().resolve()
        if not root.is_dir():
            values.append(SourceSummary(source_id, str(root), False, 0, 0, 0, ""))
            continue
        files = list(_iter_files(root))
        latest = max((item.stat().st_mtime for item in files), default=0.0)
        values.append(
            SourceSummary(
                source_id=source_id,
                path=str(root),
                exists=True,
                files=len(files),
                bytes=sum(item.stat().st_size for item in files),
                databases=sum(item.suffix.casefold() in DATABASE_SUFFIXES for item in files),
                latest_modified_at=(
                    datetime.fromtimestamp(latest, timezone.utc).isoformat(timespec="seconds")
                    if latest
                    else ""
                ),
            )
        )
    return values


def migrate(
    target: Path,
    primary: Path,
    sources: Iterable[Path],
    *,
    desktop_bootstrap: Path | None = None,
) -> MigrationReport:
    destination = Path(target).expanduser().resolve()
    primary_root = Path(primary).expanduser().resolve()
    secondary_roots = [Path(item).expanduser().resolve() for item in sources]
    _validate_migration_roots(destination, primary_root, secondary_roots)
    root_lock = _MigrationRootLock(destination)
    root_lock.acquire()
    migration_id = uuid.uuid4().hex
    staging = destination / "staging" / migration_id
    payload = staging / "payload"
    report = MigrationReport(
        migration_id=migration_id,
        status="created",
        target=str(destination),
        primary_source=str(primary_root),
        created_at=_now(),
        sources=audit_sources(primary_root, secondary_roots),
    )
    known: dict[str, FileDecision] = {}
    try:
        _write_operation(staging, report, "created")
        _ensure_payload_roots(payload)
        roots = [primary_root, *secondary_roots]
        for index, root in enumerate(roots):
            source_id = "primary" if index == 0 else f"source-{index}"
            _write_operation(staging, report, "copying")
            for source_file in _iter_files(root):
                source_relative = source_file.relative_to(root)
                target_relative = _map_legacy_relative_path(source_relative, source_id)
                if target_relative is None:
                    continue
                target_key = target_relative.as_posix().casefold()
                size = source_file.stat().st_size
                digest = _sha256(source_file)
                existing = known.get(target_key)
                if existing is None:
                    target_file = payload / target_relative
                    _copy_verified(source_file, target_file, digest)
                    decision = FileDecision(
                        source_id,
                        source_relative.as_posix(),
                        target_relative.as_posix(),
                        size,
                        digest,
                        "copied",
                    )
                    known[target_key] = decision
                    report.files.append(decision)
                    continue
                if existing.sha256 == digest:
                    report.files.append(
                        FileDecision(
                            source_id,
                            source_relative.as_posix(),
                            target_relative.as_posix(),
                            size,
                            digest,
                            "duplicate",
                        )
                    )
                    continue
                conflict_relative = Path("migrations") / "conflicts" / source_id / target_relative
                conflict_file = _unique_conflict_path(payload, conflict_relative, digest)
                _copy_verified(source_file, conflict_file, digest)
                report.files.append(
                    FileDecision(
                        source_id,
                        source_relative.as_posix(),
                        target_relative.as_posix(),
                        size,
                        digest,
                        "conflict_preserved",
                        conflict_file.relative_to(payload).as_posix(),
                    )
                )
        _migrate_desktop_bootstrap(payload, destination, desktop_bootstrap)
        _normalize_target_configuration(payload)
        _write_storage_manifest(payload, migration_id)
        _write_operation(staging, report, "verifying")
        report.databases = _verify_databases(payload)
        _verify_allowed_top_level(payload)
        report.status = "verified"
        _write_report(payload, report)
        _write_operation(staging, report, "committing")
        occupied = [item for item in destination.iterdir() if item.name != "staging"]
        if occupied:
            raise UnifiedStorageMigrationError("目标数据根必须为空或只包含本次 staging")
        for source in payload.iterdir():
            _publish_path(source, destination / source.name)
        report.status = "completed"
        report.completed_at = _now()
        _write_report(destination, report)
        _write_operation(staging, report, "completed")
        shutil.rmtree(staging)
        (destination / "staging").mkdir(exist_ok=True)
        return report
    except Exception:
        report.status = "failed"
        _write_operation(staging, report, "failed")
        raise
    finally:
        root_lock.release()


def recover_abandoned_staging(target: Path, operation_id: str) -> dict[str, object]:
    destination = Path(target).expanduser().resolve()
    safe_id = str(operation_id or "").strip()
    if not safe_id or Path(safe_id).name != safe_id:
        raise UnifiedStorageMigrationError("staging operation id 无效")
    staging = (destination / "staging" / safe_id).resolve()
    staging_root = (destination / "staging").resolve()
    if staging == staging_root or not staging.is_relative_to(staging_root) or not staging.is_dir():
        raise UnifiedStorageMigrationError("staging 操作不存在")
    owner = _read_json(staging / "operation.lock")
    pid = int(str(owner.get("pid") or "0"))
    if pid > 0 and _pid_exists(pid):
        raise UnifiedStorageMigrationError("staging 操作仍在运行，禁止清理")
    migrations = destination / "migrations"
    if not migrations.is_dir():
        raise UnifiedStorageMigrationError("尚未完成有效迁移，必须保留中断 staging")
    files = list(_iter_files(staging))
    record = {
        "operation_id": safe_id,
        "recovered_at": _now(),
        "reason": "abandoned_staging_without_live_owner",
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "last_status": _read_json(staging / "status.json"),
    }
    _atomic_json(migrations / "staging-recovery" / f"{safe_id}.json", record)
    shutil.rmtree(staging)
    return record


def _validate_migration_roots(target: Path, primary: Path, sources: list[Path]) -> None:
    if not primary.is_dir():
        raise UnifiedStorageMigrationError(f"权威来源不存在：{primary}")
    for source in sources:
        if not source.is_dir():
            raise UnifiedStorageMigrationError(f"迁移来源不存在：{source}")
    for source in [primary, *sources]:
        if source == target or source.is_relative_to(target) or target.is_relative_to(source):
            raise UnifiedStorageMigrationError("目标数据根不能与任何来源目录嵌套")
    target.mkdir(parents=True, exist_ok=True)
    occupied = [item for item in target.iterdir() if item.name != "staging"]
    if occupied:
        raise UnifiedStorageMigrationError("目标数据根必须为空")


def _iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise UnifiedStorageMigrationError(f"迁移来源包含符号链接或 junction：{path}")
        if path.is_file():
            yield path


def _map_legacy_relative_path(relative: Path, source_id: str) -> Path | None:
    parts = relative.parts
    if not parts:
        return None
    lowered = tuple(part.casefold() for part in parts)
    if len(parts) >= 2 and lowered[0] == "runtime" and lowered[1] in SKIPPED_RUNTIME_NAMES:
        return None
    if lowered[0] == "data" and len(parts) >= 2:
        category = lowered[1]
        rest = parts[2:]
        if category == "sites":
            return Path("sites", *rest)
        if category == "config":
            if rest and rest[-1].casefold() == "app.json":
                rest = (*rest[:-1], "application.json")
            return Path("config", *rest)
        if category == "global":
            return Path("config", "global", *rest)
        if category == "runtime":
            return Path("config", "runtime", *rest)
        return Path("migrations", "unclassified", source_id, *parts)
    if lowered[0] == "runtime":
        return Path("runtime", *parts[1:])
    if lowered[0] == "cache":
        return Path("runtime", "cache", *parts[1:])
    if lowered[0] == "agent":
        return Path("agents", "legacy-localappdata-agent", *parts[1:])
    if lowered[0] == "migrations":
        return Path("migrations", "source-history", source_id, *parts[1:])
    if lowered[0] == "migrationreports":
        return Path("migrations", "reports", source_id, *parts[1:])
    if lowered[0] in {"archive", "bootstrap"}:
        category = "archive" if lowered[0] == "archive" else "bootstrap"
        root = "migrations" if category == "archive" else "config"
        return Path(root, category, source_id, *parts[1:])
    if lowered[0] == "temp":
        return Path("runtime", "temp", "legacy", source_id, *parts[1:])
    if relative.name.casefold() == "development.zip":
        return Path("migrations", "source-archives", source_id, relative.name)
    return Path("migrations", "unclassified", source_id, *parts)


def _copy_verified(source: Path, destination: Path, expected_hash: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
    try:
        with source.open("rb") as input_handle, temporary.open("xb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=8 * 1024 * 1024)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        shutil.copystat(source, temporary)
        if _sha256(temporary) != expected_hash:
            raise UnifiedStorageMigrationError(f"文件复制哈希校验失败：{source}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_path(source: Path, destination: Path) -> None:
    try:
        os.replace(source, destination)
        return
    except (OSError, PermissionError):
        pass
    try:
        os.rename(source, destination)
        return
    except (OSError, PermissionError):
        pass
    if destination.exists():
        raise UnifiedStorageMigrationError(f"目标目录无法发布：{destination}")
    shutil.move(str(source), str(destination))


def _unique_conflict_path(payload: Path, relative: Path, digest: str) -> Path:
    candidate = payload / relative
    if not candidate.exists():
        return candidate
    return candidate.with_name(f"{candidate.stem}.{digest[:12]}{candidate.suffix}")


def _migrate_desktop_bootstrap(payload: Path, target: Path, configured: Path | None) -> None:
    bootstrap = configured
    if bootstrap is None and os.name == "nt" and os.environ.get("APPDATA"):
        bootstrap = Path(os.environ["APPDATA"]) / "netconsole-desktop-electron" / "bootstrap.json"
    if bootstrap is None or not bootstrap.is_file():
        return
    try:
        value = json.loads(bootstrap.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(value, dict):
        return
    active_site_id = str(value.get("active_site_id") or "").strip()
    if not active_site_id:
        return
    _atomic_json(
        payload / "runtime" / "electron" / "user-data" / "bootstrap.json",
        {"schema_version": 1, "data_root": str(target), "active_site_id": active_site_id},
    )


def _normalize_target_configuration(payload: Path) -> None:
    registry_path = payload / "config" / "site_registry.json"
    if registry_path.is_file():
        try:
            value = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict) and isinstance(value.get("sites"), list):
            for site in value["sites"]:
                if not isinstance(site, dict):
                    continue
                relative = str(site.get("relative_path") or "")
                if relative.replace("\\", "/").casefold().startswith("data/sites/"):
                    site["relative_path"] = relative.replace("\\", "/")[len("data/") :]
            _atomic_json(registry_path, value)


def _write_storage_manifest(payload: Path, migration_id: str) -> None:
    _atomic_json(
        payload / "config" / "storage-manifest.json",
        {
            "schema_version": CURRENT_STORAGE_SCHEMA_VERSION,
            "minimum_app_version": APP_VERSION,
            "last_opened_app_version": APP_VERSION,
            "last_migration_time": _now(),
            "migration_id": migration_id,
        },
    )


def _verify_databases(payload: Path) -> list[DatabaseCheck]:
    checks: list[DatabaseCheck] = []
    for database in sorted(
        (item for item in payload.rglob("*") if item.is_file() and item.suffix.casefold() in DATABASE_SUFFIXES),
        key=lambda item: item.as_posix().casefold(),
    ):
        try:
            uri = database.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
                quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        except (sqlite3.DatabaseError, OSError) as exc:
            raise UnifiedStorageMigrationError(f"SQLite 校验失败：{database}") from exc
        checks.append(DatabaseCheck(database.relative_to(payload).as_posix(), quick, integrity))
        if quick.casefold() != "ok" or integrity.casefold() != "ok":
            raise UnifiedStorageMigrationError(f"SQLite 完整性检查失败：{database}")
    return checks


def _ensure_payload_roots(payload: Path) -> None:
    for name in ALLOWED_TARGET_ROOTS - {"staging"}:
        (payload / name).mkdir(parents=True, exist_ok=True)


def _verify_allowed_top_level(payload: Path) -> None:
    unexpected = sorted(item.name for item in payload.iterdir() if item.name not in ALLOWED_TARGET_ROOTS)
    if unexpected:
        raise UnifiedStorageMigrationError(f"目标包含未授权顶层目录：{', '.join(unexpected)}")


def _write_operation(staging: Path, report: MigrationReport, status: str) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    report.status = status
    common = {"schema_version": 1, "updated_at": _now()}
    _atomic_json(staging / "manifest.json", {**common, "migration_id": report.migration_id})
    _atomic_json(staging / "source.json", {**common, "primary": report.primary_source})
    _atomic_json(staging / "target.json", {**common, "data_root": report.target})
    _atomic_json(staging / "status.json", {**common, "status": status})
    lock = staging / "operation.lock"
    if not lock.exists():
        _atomic_json(lock, {"pid": os.getpid(), "started_at": _now()})


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if getattr(exc, "winerror", None) in {87, 1168}:
            return False
        raise
    return True


def _write_report(root: Path, report: MigrationReport) -> None:
    payload = {
        **report.summary(),
        "sources": [asdict(item) for item in report.sources],
        "files": [asdict(item) for item in report.files],
        "databases": [asdict(item) for item in report.databases],
    }
    _atomic_json(root / "migrations" / f"unified-storage-migration-{report.migration_id}.json", payload)


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.recover_abandoned_staging:
        result = recover_abandoned_staging(args.target, args.recover_abandoned_staging)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.primary is None:
        raise SystemExit("--primary is required unless --recover-abandoned-staging is used")
    summaries = audit_sources(args.primary, args.source)
    if not args.execute:
        payload = {"target": str(args.target.expanduser().resolve()), "sources": [asdict(item) for item in summaries]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.output:
            _atomic_json(args.output.expanduser().resolve(), payload)
        return 0
    report = migrate(
        args.target,
        args.primary,
        args.source,
        desktop_bootstrap=args.desktop_bootstrap,
    )
    print(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    if args.output:
        _atomic_json(args.output.expanduser().resolve(), report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
