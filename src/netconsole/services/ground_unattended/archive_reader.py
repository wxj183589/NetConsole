from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)


MAX_ARCHIVE_ENTRIES = 20_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 8 * 1024**3
MAX_MEMBER_UNCOMPRESSED_BYTES = 512 * 1024**2
MAX_COMPRESSION_RATIO = 300
MANIFEST_NAME = "manifest.json"


class GroundArchiveReadError(ValueError):
    pass


@dataclass(frozen=True)
class GroundArchiveInspection:
    path: Path
    row: dict[str, Any]
    manifest: dict[str, Any]
    files: tuple[dict[str, Any], ...]
    archive_sha256: str
    manifest_sha256: str
    legacy_manifest: bool
    checked_at: str


class GroundArchiveReader:
    """只读校验并流式读取受管 READY ZIP，不提取归档成员到磁盘。"""

    def __init__(self, repository: GroundUnattendedRepository) -> None:
        self.repository = repository
        self.root = repository.db_path.parent.resolve()
        self.archives_root = (self.root / "archives").resolve()
        self._inspection_cache: dict[
            tuple[str, int, int, str, bool], GroundArchiveInspection
        ] = {}

    def inspect_archive(
        self,
        archive_id: str,
        *,
        force: bool = False,
        full_integrity: bool = True,
    ) -> GroundArchiveInspection:
        row = self.repository.get_archive(archive_id)
        if row is None:
            raise GroundArchiveReadError("无人值守归档不存在")
        if str(row.get("archive_status") or "") != "READY":
            raise GroundArchiveReadError("仅 READY 归档可读取或下载")
        path = self._archive_path(row)
        file_stat = path.stat()
        expected_size = int(row.get("archive_size_bytes") or 0)
        if expected_size and file_stat.st_size != expected_size:
            raise GroundArchiveReadError("归档文件大小与登记值不一致")
        expected_sha = str(row.get("sha256") or "").casefold()
        cache_key = (
            str(path),
            file_stat.st_size,
            file_stat.st_mtime_ns,
            expected_sha,
            full_integrity,
        )
        if not force and cache_key in self._inspection_cache:
            return self._inspection_cache[cache_key]

        actual_sha = expected_sha
        if full_integrity:
            actual_sha = _sha256(path)
            if expected_sha and actual_sha.casefold() != expected_sha:
                raise GroundArchiveReadError("归档文件 SHA-256 与登记值不一致")
        try:
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
                self._validate_infos(infos)
                if full_integrity:
                    bad_member = archive.testzip()
                    if bad_member is not None:
                        raise GroundArchiveReadError(
                            f"归档成员 CRC 校验失败：{bad_member}"
                        )
                names = {info.filename for info in infos if not info.is_dir()}
                legacy = MANIFEST_NAME not in names
                manifest: dict[str, Any] = {}
                manifest_sha = ""
                manifest_files: dict[str, dict[str, Any]] = {}
                if not legacy:
                    manifest_bytes = archive.read(MANIFEST_NAME)
                    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
                    expected_manifest_sha = str(
                        row.get("manifest_sha256") or ""
                    ).casefold()
                    if (
                        expected_manifest_sha
                        and manifest_sha.casefold() != expected_manifest_sha
                    ):
                        raise GroundArchiveReadError(
                            "归档 manifest SHA-256 与登记值不一致"
                        )
                    try:
                        value = json.loads(manifest_bytes.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise GroundArchiveReadError(
                            "归档 manifest 不是有效 UTF-8 JSON"
                        ) from exc
                    if not isinstance(value, dict):
                        raise GroundArchiveReadError("归档 manifest 顶层结构无效")
                    manifest = value
                    if str(manifest.get("run_id") or "") != str(
                        row.get("run_id") or ""
                    ):
                        raise GroundArchiveReadError(
                            "归档 manifest 的运行标识与登记值不一致"
                        )
                    for item in manifest.get("files") or []:
                        if not isinstance(item, dict):
                            raise GroundArchiveReadError(
                                "归档 manifest 文件清单结构无效"
                            )
                        name = _safe_member_name(str(item.get("path") or ""))
                        if name not in names:
                            raise GroundArchiveReadError(
                                f"归档 manifest 成员不存在：{name}"
                            )
                        manifest_files[name] = item
                    if full_integrity:
                        for name, item in manifest_files.items():
                            expected_member_sha = str(item.get("sha256") or "")
                            if expected_member_sha and _zip_member_sha256(
                                archive, name
                            ) != expected_member_sha:
                                raise GroundArchiveReadError(
                                    f"归档成员 SHA-256 校验失败：{name}"
                                )
                registered_by_entry: dict[str, dict[str, Any]] = {}
                for registered in self.repository.list_raw_files_for_run(
                    str(row.get("run_id") or "")
                ):
                    try:
                        entry = self.entry_for_registered_file(registered)
                    except GroundArchiveReadError:
                        continue
                    registered_by_entry[entry] = registered
                files = []
                for info in infos:
                    if info.is_dir():
                        continue
                    registered = registered_by_entry.get(info.filename) or {}
                    started_at = str(registered.get("start_time") or "")
                    files.append(
                        {
                            "path": info.filename,
                            "data_type": str(
                                registered.get("data_type") or ""
                            ),
                            "train_id": str(
                                registered.get("train_id") or ""
                            ),
                            "mr_id": str(
                                registered.get("device_uuid") or ""
                            ),
                            "mr_role": str(
                                registered.get("mr_role") or ""
                            ),
                            "hour": (
                                started_at[11:13]
                                if len(started_at) >= 13
                                else ""
                            ),
                            "record_count": int(
                                registered.get("record_count") or 0
                            ),
                            "size_bytes": int(info.file_size),
                            "compressed_size_bytes": int(info.compress_size),
                            "sha256": str(
                                (
                                    manifest_files.get(info.filename) or {}
                                ).get("sha256")
                                or ""
                            ),
                            "parse_status": str(
                                registered.get("parse_status") or ""
                            ),
                        }
                    )
                files = tuple(files)
        except zipfile.BadZipFile as exc:
            raise GroundArchiveReadError("归档 ZIP 结构损坏") from exc

        inspection = GroundArchiveInspection(
            path=path,
            row=row,
            manifest=manifest,
            files=files,
            archive_sha256=actual_sha,
            manifest_sha256=manifest_sha,
            legacy_manifest=legacy,
            checked_at=datetime.now().astimezone().isoformat(
                timespec="milliseconds"
            ),
        )
        self._inspection_cache[cache_key] = inspection
        while len(self._inspection_cache) > 16:
            self._inspection_cache.pop(next(iter(self._inspection_cache)))
        return inspection

    def inspect_run(
        self, run_id: str, *, full_integrity: bool = True
    ) -> GroundArchiveInspection | None:
        row = self.repository.get_archive_by_run(run_id)
        if row is None or str(row.get("archive_status") or "") != "READY":
            return None
        return self.inspect_archive(
            str(row["archive_id"]), full_integrity=full_integrity
        )

    def iter_registered_lines(
        self,
        inspection: GroundArchiveInspection,
        registered: dict[str, Any],
    ) -> Iterator[tuple[bytes, str]]:
        entry = self.entry_for_registered_file(registered)
        allowed_prefixes = (
            ("fleet_ping/",)
            if str(registered.get("data_type") or "") == "ping"
            else ("realtime/syslog/", "syslog/")
        )
        if not entry.startswith(allowed_prefixes):
            raise GroundArchiveReadError("登记文件不属于允许的原始数据目录")
        file_by_name = {str(item["path"]): item for item in inspection.files}
        if entry not in file_by_name:
            raise GroundArchiveReadError(f"归档中缺少登记文件：{entry}")
        if not inspection.legacy_manifest:
            manifest_names = {
                str(item.get("path") or "")
                for item in inspection.manifest.get("files") or []
                if isinstance(item, dict)
            }
            if entry not in manifest_names:
                raise GroundArchiveReadError(
                    f"归档 manifest 未登记原始文件：{entry}"
                )
        try:
            with zipfile.ZipFile(inspection.path, "r") as archive:
                with archive.open(entry, "r") as handle:
                    for line in handle:
                        yield line, entry
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise GroundArchiveReadError(f"无法读取归档成员：{entry}") from exc

    @staticmethod
    def entry_for_registered_file(registered: dict[str, Any]) -> str:
        raw = str(registered.get("relative_path") or "").replace("\\", "/")
        path = PurePosixPath(raw)
        parts = path.parts
        if path.is_absolute() or ".." in parts:
            raise GroundArchiveReadError("原始文件登记路径不安全")
        try:
            active_index = parts.index("active")
        except ValueError as exc:
            raise GroundArchiveReadError("原始文件登记路径缺少 active 运行目录") from exc
        if len(parts) <= active_index + 2:
            raise GroundArchiveReadError("原始文件登记路径不完整")
        return _safe_member_name(
            PurePosixPath(*parts[active_index + 2 :]).as_posix()
        )

    def _archive_path(self, row: dict[str, Any]) -> Path:
        relative_text = str(row.get("relative_path") or "")
        relative = Path(relative_text)
        if (
            not relative_text
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.name != relative_text.replace("\\", "/").split("/")[-1]
        ):
            raise GroundArchiveReadError("归档登记路径无效")
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or _is_junction(current):
                raise GroundArchiveReadError("拒绝读取链接或联接指向的归档")
        path = (self.root / relative).resolve()
        if path.parent != self.archives_root or path.suffix.casefold() != ".zip":
            raise GroundArchiveReadError("归档路径不在受管 archives 目录")
        if not path.is_file() or path.is_symlink() or _is_junction(path):
            raise GroundArchiveReadError("归档不是普通 ZIP 文件")
        return path

    @staticmethod
    def _validate_infos(infos: list[zipfile.ZipInfo]) -> None:
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise GroundArchiveReadError("归档成员数量超过安全上限")
        total = 0
        names: set[str] = set()
        for info in infos:
            name = _safe_member_name(info.filename.rstrip("/"))
            if name in names:
                raise GroundArchiveReadError(f"归档包含重复成员：{name}")
            names.add(name)
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise GroundArchiveReadError("归档包含符号链接成员")
            if info.is_dir():
                continue
            if info.file_size > MAX_MEMBER_UNCOMPRESSED_BYTES:
                raise GroundArchiveReadError(
                    f"归档成员超过解压上限：{info.filename}"
                )
            total += int(info.file_size)
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise GroundArchiveReadError("归档解压总量超过安全上限")
            if (
                (
                    info.file_size > 1024 * 1024
                    and info.compress_size == 0
                )
                or (
                    info.compress_size > 0
                    and info.file_size / info.compress_size
                    > MAX_COMPRESSION_RATIO
                )
            ):
                raise GroundArchiveReadError(
                    f"归档成员压缩比异常：{info.filename}"
                )


def _safe_member_name(value: str) -> str:
    if not value or "\\" in value or "\x00" in value or ":" in value:
        raise GroundArchiveReadError("归档成员名称无效")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise GroundArchiveReadError("归档成员路径不安全")
    normalized = path.as_posix()
    if normalized != value:
        raise GroundArchiveReadError("归档成员路径未规范化")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_member_sha256(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    try:
        return bool(checker()) if callable(checker) else False
    except OSError:
        return True


__all__ = [
    "GroundArchiveInspection",
    "GroundArchiveReadError",
    "GroundArchiveReader",
]
