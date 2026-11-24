"""Conservative, current-directory synchronization for the SFTP workspace."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


Direction = Literal["upload", "download", "both"]
Comparison = Literal["size", "modified", "sha256"]
MAX_ENTRIES = 500
MAX_SYNC_FILES = 25
MAX_SYNC_BYTES = 1024**3
MAX_HASH_BYTES = 64 * 1024**2


@dataclass(frozen=True, slots=True)
class SyncEntry:
    name: str
    size: int | None
    modified: str | None
    regular: bool


@dataclass(frozen=True, slots=True)
class SyncRow:
    name: str
    action: str
    local: SyncEntry | None
    remote: SyncEntry | None


def local_directory(root_path: Path, relative: str) -> Path:
    root = root_path.resolve(strict=True)
    path = root / relative
    resolved = path.resolve(strict=True)
    if resolved != path or not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ValueError("目标目录超出当前局点的受管下载目录")
    return resolved


def read_local_entries(directory: Path) -> list[SyncEntry]:
    entries = []
    with os.scandir(directory) as children:
        for child in children:
            if child.name.endswith(".part"):
                continue
            if len(entries) >= MAX_ENTRIES:
                raise ValueError("当前目录超过同步预览的 500 项限制")
            attrs = child.stat(follow_symlinks=False)
            regular = stat.S_ISREG(attrs.st_mode) and not (
                getattr(attrs, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
            modified = datetime.fromtimestamp(attrs.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            entries.append(SyncEntry(child.name, attrs.st_size, modified, regular))
    return entries


def read_remote_entries(service, directory: str) -> list[SyncEntry]:
    if not stat.S_ISDIR(service.lstat(directory).st_mode):
        raise ValueError("远程同步目录不可用")
    items = service.list_directory(directory)
    if len(items) > MAX_ENTRIES:
        raise ValueError("当前远程目录超过同步预览的 500 项限制")
    return [
        SyncEntry(item.name, item.size, item.modified_time, item.permissions.startswith("-"))
        for item in items
    ]


def plan_sync(
    local: list[SyncEntry],
    remote: list[SyncEntry],
    direction: Direction,
    comparison: Comparison,
    valid_name: Callable[[str], bool],
    hash_pair: Callable[[str], tuple[str, str]],
) -> list[SyncRow]:
    local_names = _group_entries(local)
    remote_names = _group_entries(remote)
    rows: list[SyncRow] = []
    hashed_bytes = 0
    for key in sorted(local_names.keys() | remote_names.keys()):
        left = local_names.get(key, [])
        right = remote_names.get(key, [])
        lfile = left[0] if left else None
        rfile = right[0] if right else None
        name = (lfile or rfile).name
        if len(left) > 1 or len(right) > 1 or (lfile and rfile and lfile.name != rfile.name):
            action = "conflict"
        elif not valid_name(name) or any(item and not item.regular for item in (lfile, rfile)):
            action = "excluded"
        elif lfile is None:
            action = "download" if direction in {"download", "both"} else "ignored"
        elif rfile is None:
            action = "upload" if direction in {"upload", "both"} else "ignored"
        elif lfile.size != rfile.size:
            action = "conflict"
        elif comparison == "size":
            action = "same"
        elif comparison == "modified":
            action = "same" if lfile.modified and lfile.modified == rfile.modified else "conflict"
        else:
            hashed_bytes += 2 * (lfile.size or 0)
            if hashed_bytes > MAX_HASH_BYTES:
                raise ValueError("SHA-256 比较累计大小超过 64 MiB")
            left_sha, right_sha = hash_pair(name)
            action = "same" if left_sha == right_sha else "conflict"
        rows.append(SyncRow(name, action, lfile, rfile))
    return rows


def _group_entries(entries: list[SyncEntry]) -> dict[str, list[SyncEntry]]:
    groups: dict[str, list[SyncEntry]] = {}
    for item in entries:
        groups.setdefault(item.name.casefold(), []).append(item)
    return groups


def sync_revision(context: list[str], local: list[SyncEntry], remote: list[SyncEntry], rows: list[SyncRow]) -> str:
    encoded = json.dumps(
        [context, [asdict(item) for item in sorted(local, key=lambda item: item.name)],
         [asdict(item) for item in sorted(remote, key=lambda item: item.name)],
         [asdict(item) for item in rows]],
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
