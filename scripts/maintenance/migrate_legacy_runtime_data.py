from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from netconsole.core.runtime_environment import data_root as default_data_root


SQLITE_HEADER = b"SQLite format 3\x00"
SQLITE_SIDECAR_SUFFIXES = ("-journal", "-shm", "-wal")


@dataclass(frozen=True)
class MigrationEntry:
    source_label: str
    relative_path: str
    destination_path: str
    size: int
    kind: str
    action: str
    sha256: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class SourceMapping:
    label: str
    source: Path
    destination_prefix: Path


def build_plan(repo_root: Path, destination_root: Path) -> list[MigrationEntry]:
    repo = repo_root.resolve()
    destination = destination_root.resolve()
    _require_outside(destination, repo, "destination")
    mappings = (
        SourceMapping("legacy-local-data", repo / ".local" / "data", Path("data")),
        SourceMapping("legacy-local-runtime", repo / ".local" / "runtime", Path("runtime")),
        SourceMapping("legacy-root-data", repo / "data", Path("data")),
    )
    entries: list[MigrationEntry] = []
    claimed: dict[str, tuple[str, str]] = {}
    for mapping in mappings:
        if not mapping.source.exists():
            continue
        _require_inside(mapping.source.resolve(), repo, mapping.label)
        if _is_reparse_point(mapping.source):
            entries.append(_unsafe_entry(mapping, Path("."), "source root is a link or reparse point"))
            continue
        for source in _walk_files(mapping.source):
            relative = source.relative_to(mapping.source)
            destination_relative = mapping.destination_prefix / relative
            if _is_reparse_point(source):
                entries.append(_unsafe_entry(mapping, relative, "link or reparse point"))
                continue
            if source.name.endswith(SQLITE_SIDECAR_SUFFIXES):
                entries.append(_entry(mapping, relative, destination_relative, source, "sidecar", "skip", detail="SQLite transient sidecar"))
                continue
            kind = "sqlite" if _is_sqlite(source) else "file"
            digest = _sha256(source)
            destination_path = destination / destination_relative
            key = destination_relative.as_posix().casefold()
            action = "copy"
            detail = None
            previous = claimed.get(key)
            if previous is not None:
                previous_label, previous_digest = previous
                if previous_digest == digest:
                    action = "duplicate"
                    detail = f"same content already supplied by {previous_label}"
                else:
                    action = "conflict"
                    detail = f"different content already supplied by {previous_label}"
            elif destination_path.exists():
                if not destination_path.is_file() or _is_reparse_point(destination_path):
                    action = "unsafe"
                    detail = "destination is not a regular file"
                elif _sha256(destination_path) == digest:
                    action = "present"
                    detail = "same content already exists"
                else:
                    action = "conflict"
                    detail = "destination exists with different content"
            else:
                claimed[key] = (mapping.label, digest)
            entries.append(
                MigrationEntry(
                    source_label=mapping.label,
                    relative_path=relative.as_posix(),
                    destination_path=destination_relative.as_posix(),
                    size=source.stat().st_size,
                    kind=kind,
                    action=action,
                    sha256=digest,
                    detail=detail,
                )
            )
    return entries


def apply_plan(
    repo_root: Path,
    destination_root: Path,
    entries: Iterable[MigrationEntry],
    *,
    skip_conflicts: bool = False,
) -> list[MigrationEntry]:
    repo = repo_root.resolve()
    destination = destination_root.resolve()
    _require_outside(destination, repo, "destination")
    plan = list(entries)
    blocking_actions = {"unsafe"} if skip_conflicts else {"conflict", "unsafe"}
    blocking = [entry for entry in plan if entry.action in blocking_actions]
    if blocking:
        raise RuntimeError(f"migration has {len(blocking)} conflict or unsafe entries")
    sources = {
        "legacy-local-data": repo / ".local" / "data",
        "legacy-local-runtime": repo / ".local" / "runtime",
        "legacy-root-data": repo / "data",
    }
    applied: list[MigrationEntry] = []
    for entry in plan:
        if entry.action != "copy":
            applied.append(entry)
            continue
        source_root = sources[entry.source_label].resolve()
        source = (source_root / Path(entry.relative_path)).resolve()
        target = (destination / Path(entry.destination_path)).resolve()
        _require_inside(source, source_root, "source file")
        _require_inside(target, destination, "destination file")
        if _is_reparse_point(source) or not source.is_file():
            raise RuntimeError(f"source changed after planning: {entry.relative_path}")
        if _sha256(source) != entry.sha256:
            raise RuntimeError(f"source changed after planning: {entry.relative_path}")
        if target.exists():
            raise RuntimeError(f"destination appeared after planning: {entry.destination_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.kind == "sqlite":
            copied_digest = _backup_sqlite(source, target)
        else:
            copied_digest = _copy_regular(source, target)
        applied.append(
            MigrationEntry(
                **{
                    **asdict(entry),
                    "action": "copied",
                    "sha256": copied_digest,
                    "detail": "verified after copy",
                }
            )
        )
    return applied


def manifest(entries: Iterable[MigrationEntry], *, applied: bool, destination_root: Path) -> dict[str, object]:
    items = list(entries)
    counts = Counter(item.action for item in items)
    return {
        "schema_version": 1,
        "mode": "applied" if applied else "dry-run",
        "destination": str(destination_root.resolve()),
        "summary": {
            "files": len(items),
            "bytes": sum(item.size for item in items if item.action not in {"skip", "unsafe"}),
            "actions": dict(sorted(counts.items())),
        },
        "entries": [asdict(item) for item in items],
    }


def _walk_files(root: Path) -> Iterable[Path]:
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(directories):
            child = current_path / name
            if _is_reparse_point(child):
                directories.remove(name)
                yield child
        for name in files:
            yield current_path / name


def _entry(
    mapping: SourceMapping,
    relative: Path,
    destination: Path,
    source: Path,
    kind: str,
    action: str,
    *,
    detail: str,
) -> MigrationEntry:
    return MigrationEntry(
        source_label=mapping.label,
        relative_path=relative.as_posix(),
        destination_path=destination.as_posix(),
        size=source.stat().st_size if source.is_file() else 0,
        kind=kind,
        action=action,
        detail=detail,
    )


def _unsafe_entry(mapping: SourceMapping, relative: Path, detail: str) -> MigrationEntry:
    return MigrationEntry(mapping.label, relative.as_posix(), "", 0, "link", "unsafe", detail=detail)


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.lstat().st_file_attributes & 0x400)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_regular(source: Path, target: Path) -> str:
    temporary = _temporary_path(target)
    try:
        shutil.copy2(source, temporary)
        digest = _sha256(temporary)
        if digest != _sha256(source):
            raise RuntimeError(f"copy verification failed: {source.name}")
        os.replace(temporary, target)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def _backup_sqlite(source: Path, target: Path) -> str:
    temporary = _temporary_path(target)
    try:
        source_uri = f"{source.as_uri()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_db:
            _check_sqlite(source_db, source.name)
            with closing(sqlite3.connect(temporary)) as destination_db:
                source_db.backup(destination_db)
                _check_sqlite(destination_db, source.name)
        digest = _sha256(temporary)
        os.replace(temporary, target)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def _check_sqlite(connection: sqlite3.Connection, name: str) -> None:
    result = connection.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite quick_check failed: {name}")


def _temporary_path(target: Path) -> Path:
    handle, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".migrating", dir=target.parent)
    os.close(handle)
    temporary = Path(name)
    temporary.unlink()
    return temporary


def _require_inside(candidate: Path, root: Path, label: str) -> None:
    if candidate != root and not candidate.is_relative_to(root):
        raise RuntimeError(f"{label} escapes the allowed root")


def _require_outside(candidate: Path, root: Path, label: str) -> None:
    if candidate == root or candidate.is_relative_to(root):
        raise RuntimeError(f"{label} must be outside the source repository")


def _write_manifest(payload: dict[str, object], path: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path is None:
        print(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="盘点或迁移仓库内历史 NetConsole 运行数据")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--destination", type=Path, default=None)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--apply", action="store_true", help="执行无覆盖复制；默认仅生成计划")
    parser.add_argument("--skip-conflicts", action="store_true", help="保留并跳过冲突目标，不覆盖任何文件")
    args = parser.parse_args()
    destination = (args.destination or default_data_root()).resolve()
    planned = build_plan(args.repo_root, destination)
    blocking = [entry for entry in planned if entry.action in {"conflict", "unsafe"}]
    if args.apply and (not blocking or (args.skip_conflicts and all(entry.action != "unsafe" for entry in blocking))):
        result = apply_plan(args.repo_root, destination, planned, skip_conflicts=args.skip_conflicts)
        _write_manifest(manifest(result, applied=True, destination_root=destination), args.manifest)
        return 0
    _write_manifest(manifest(planned, applied=False, destination_root=destination), args.manifest)
    return 2 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
