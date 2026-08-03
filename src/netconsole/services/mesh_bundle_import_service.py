from __future__ import annotations

import gzip
import gc
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import zipfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.parsers.mesh_log_parser import (
    MeshLogContentMetadata,
    MeshLogSizeLimitError,
    inspect_mesh_log_path,
    inspect_mesh_log_stream,
)
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_mr_repository import SCHEMA_VERSION, MeshMrRepository, MeshSchemaRebuildRequired
from netconsole.repositories.mesh_source_index_repository import MeshSourceIndexRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_import_limits import (
    MESH_SINGLE_FILE_MAX_BYTES,
    MESH_SINGLE_FILE_MAX_LABEL,
)
from netconsole.services.mesh_parsed_rebuild_service import MeshParsedRebuildService
from netconsole.services.mesh_log_analysis_service import PARSER_VERSION
from netconsole.services.mesh_storage_service import suggest_mesh_archive_filename


_MESH_MEMBER_RE = re.compile(
    r"^(?P<train>\d{1,2})[-_ ]?(?P<role>CT|CW)meshlog\.log(?:\.gz)?$",
    re.IGNORECASE,
)
_ARCHIVE_SEQUENCE_RE = re.compile(
    r"_(?P<sequence>[1-9]\d*)(?P<tail>meshlog\.(?:log|txt)(?:\.gz)?)$",
    re.IGNORECASE,
)
_PREVIEW_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED_SUFFIXES = (".log", ".txt", ".log.gz", ".txt.gz")
_MAX_ARCHIVE_SIZE = 50 * 1024 * 1024
_MAX_MEMBER_COUNT = 64
_MAX_FILE_SIZE = MESH_SINGLE_FILE_MAX_BYTES
_MAX_BUNDLE_SIZE = 100 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200.0
_PREVIEW_TTL_SECONDS = 15 * 60
_SUBMITTED_PREVIEW_TTL_SECONDS = 60 * 60
_MAX_PREVIEW_COUNT = 16
_MAX_PREVIEW_BYTES = 256 * 1024 * 1024
_MANIFEST_SCHEMA_VERSION = 3
_CATALOG_SUMMARY_FIELDS = (
    "earliest_sample_time",
    "latest_sample_time",
    "source_file_count",
    "sample_count",
    "link_record_count",
    "session_count",
    "event_count",
    "last_import_at",
    "updated_at",
)


@dataclass(frozen=True)
class MeshBundleMember:
    member_id: str
    internal_member_name: str
    original_name: str
    safe_name: str
    size_bytes: int
    expanded_size_bytes: int
    compressed_size_bytes: int
    sha256: str
    raw_sha256: str
    content_sha256: str
    first_log_timestamp: datetime | None
    last_log_timestamp: datetime | None
    file_order: int
    train_number: str | None
    role: str | None
    train_aliases: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "internal_member_name": self.internal_member_name,
            "original_name": Path(self.original_name).name,
            "original_relative_path": (
                self.original_name if "/" in self.original_name else ""
            ),
            "safe_name": self.safe_name,
            "size_bytes": self.size_bytes,
            "expanded_size_bytes": self.expanded_size_bytes,
            "compressed_size_bytes": self.compressed_size_bytes,
            "sha256": self.sha256,
            "raw_sha256": self.raw_sha256,
            "content_sha256": self.content_sha256,
            "first_log_timestamp": (
                self.first_log_timestamp.isoformat(timespec="microseconds")
                if self.first_log_timestamp
                else None
            ),
            "last_log_timestamp": (
                self.last_log_timestamp.isoformat(timespec="microseconds")
                if self.last_log_timestamp
                else None
            ),
            "log_date": self.first_log_timestamp.date().isoformat() if self.first_log_timestamp else None,
            "rename_status": (
                "renamed_by_log_date_sequence"
                if Path(self.safe_name).name.casefold() in {"meshlog.log", "meshlog.txt", "meshlog.log.gz", "meshlog.txt.gz"}
                and self.first_log_timestamp
                else "timestamp_not_found"
                if Path(self.safe_name).name.casefold() in {"meshlog.log", "meshlog.txt", "meshlog.log.gz", "meshlog.txt.gz"}
                else "already_normalized"
                if re.fullmatch(
                    r"\d{4}_\d{2}_\d{2}_[1-9]\d*meshlog\.(?:log|txt)(?:\.gz)?",
                    Path(self.safe_name).name,
                    re.IGNORECASE,
                )
                else "original_name_retained"
            ),
            "rename_warning": (
                "未识别到首个有效日志时间，无法生成日期归档名称。"
                if Path(self.safe_name).name.casefold() in {"meshlog.log", "meshlog.txt", "meshlog.log.gz", "meshlog.txt.gz"}
                and self.first_log_timestamp is None
                else ""
            ),
            "file_order": self.file_order,
            "train_number": self.train_number,
            "role": self.role,
            "train_aliases": list(self.train_aliases),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MeshBundleMember:
        original_name = str(
            value.get("original_relative_path")
            or value.get("original_name")
            or ""
        )
        internal_member_name = str(value.get("internal_member_name") or original_name)
        return cls(
            member_id=str(value.get("member_id") or original_name),
            internal_member_name=internal_member_name,
            original_name=original_name,
            safe_name=str(value.get("safe_name") or ""),
            size_bytes=int(value.get("size_bytes") or 0),
            expanded_size_bytes=int(value.get("expanded_size_bytes") or value.get("size_bytes") or 0),
            compressed_size_bytes=int(value.get("compressed_size_bytes") or 0),
            sha256=str(value.get("sha256") or ""),
            raw_sha256=str(value.get("raw_sha256") or value.get("sha256") or ""),
            content_sha256=str(value.get("content_sha256") or value.get("sha256") or ""),
            first_log_timestamp=_parse_manifest_datetime(value.get("first_log_timestamp")),
            last_log_timestamp=_parse_manifest_datetime(value.get("last_log_timestamp")),
            file_order=int(value.get("file_order") or 0),
            train_number=str(value.get("train_number") or "") or None,
            role=str(value.get("role") or "") or None,
            train_aliases=tuple(str(item) for item in value.get("train_aliases") or ()),
        )


@dataclass(frozen=True)
class MeshBundleManifest:
    archive_sha256: str
    archive_size_bytes: int
    expanded_size_bytes: int
    members: tuple[MeshBundleMember, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "archive_sha256": self.archive_sha256,
            "archive_size_bytes": self.archive_size_bytes,
            "expanded_size_bytes": self.expanded_size_bytes,
            "member_count": len(self.members),
            "members": [member.to_dict() for member in self.members],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MeshBundleManifest:
        members = value.get("members") or ()
        return cls(
            archive_sha256=str(value.get("archive_sha256") or ""),
            archive_size_bytes=int(value.get("archive_size_bytes") or 0),
            expanded_size_bytes=int(value.get("expanded_size_bytes") or 0),
            members=tuple(
                MeshBundleMember.from_dict(item)
                for item in members
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True)
class MeshBundleProfileMatch:
    member: MeshBundleMember
    status: str
    profile_id: str | None = None
    profile_name: str | None = None
    candidate_profile_ids: tuple[str, ...] = ()


@dataclass
class _ProfilePublishState:
    production_root: Path
    rollback_root: Path
    created_files: list[Path]
    overwritten_files: list[tuple[Path, Path]]
    created_directories: list[Path]


class MeshBundleImportError(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code if message is not None else "MESH_BUNDLE_INVALID"


class MeshBundleImportService:
    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = site_name
        self.paths = paths
        self._fingerprints_backfilled: set[str] = set()

    def inspect(
        self,
        archive: Path,
        *,
        original_names: Mapping[str, str] | None = None,
    ) -> MeshBundleManifest:
        archive = archive.resolve()
        if not archive.is_file() or archive.suffix.casefold() != ".zip":
            raise MeshBundleImportError("FILE_TYPE_INVALID", "MESH Bundle 必须是 ZIP 文件")
        archive_size = archive.stat().st_size
        if archive_size <= 0:
            raise MeshBundleImportError("FILE_EMPTY", "MESH ZIP 不能为空")
        if archive_size > _MAX_ARCHIVE_SIZE:
            raise MeshBundleImportError("ARCHIVE_TOO_LARGE", "MESH ZIP 文件不得超过 50 MiB")
        archive_sha256 = _sha256_file(archive)
        members: list[MeshBundleMember] = []
        seen_paths: set[str] = set()
        expanded_total = 0
        original_name_by_member = {
            _safe_member_name(internal_name): _safe_member_name(original_name)
            for internal_name, original_name in (original_names or {}).items()
        }
        try:
            with zipfile.ZipFile(archive) as source:
                entries = source.infolist()
                if len(entries) > _MAX_MEMBER_COUNT:
                    raise MeshBundleImportError("TOO_MANY_MEMBERS", "MESH ZIP 成员数量超过 64")
                for entry in entries:
                    if entry.flag_bits & 0x1:
                        raise MeshBundleImportError("ENCRYPTED_MEMBER", f"ZIP 成员禁止加密：{entry.filename}")
                    normalized = _safe_member_name(entry.filename)
                    if _is_symlink(entry):
                        raise MeshBundleImportError("SYMLINK_MEMBER", f"ZIP 成员禁止为符号链接：{entry.filename}")
                    if _is_unsafe_file_type(entry):
                        raise MeshBundleImportError("UNSAFE_MEMBER_TYPE", f"ZIP 成员类型不安全：{entry.filename}")
                    if entry.is_dir():
                        continue
                    normalized_key = normalized.casefold()
                    safe_name = original_name_by_member.get(normalized, normalized)
                    if normalized_key in seen_paths:
                        raise MeshBundleImportError("DUPLICATE_MEMBER", f"ZIP 成员路径重复：{entry.filename}")
                    seen_paths.add(normalized_key)
                    if not normalized_key.endswith(_ALLOWED_SUFFIXES):
                        raise MeshBundleImportError("FILE_TYPE_INVALID", f"ZIP 包含不支持的文件：{entry.filename}")
                    if entry.file_size > _MAX_FILE_SIZE:
                        raise MeshBundleImportError(
                            "MEMBER_TOO_LARGE",
                            f"单个 MESH 日志超过 {MESH_SINGLE_FILE_MAX_LABEL}：{safe_name}",
                        )
                    _validate_ratio(entry.file_size, entry.compress_size, safe_name)
                    metadata = _inspect_zip_member(source, entry, safe_name)
                    expanded_total += metadata.expanded_size_bytes
                    if expanded_total > _MAX_BUNDLE_SIZE:
                        raise MeshBundleImportError("EXPANDED_SIZE_EXCEEDED", "MESH ZIP 解压总大小超过 100 MiB")
                    train, role, aliases = _infer_mapping(Path(safe_name).name)
                    members.append(
                        MeshBundleMember(
                            member_id=_member_id(len(members) + 1, normalized),
                            internal_member_name=normalized,
                            original_name=safe_name,
                            safe_name=safe_name,
                            size_bytes=entry.file_size,
                            expanded_size_bytes=metadata.expanded_size_bytes,
                            compressed_size_bytes=entry.compress_size,
                            sha256=metadata.raw_sha256,
                            raw_sha256=metadata.raw_sha256,
                            content_sha256=metadata.content_sha256,
                            first_log_timestamp=metadata.first_log_timestamp,
                            last_log_timestamp=metadata.last_log_timestamp,
                            file_order=len(members) + 1,
                            train_number=train,
                            role=role,
                            train_aliases=aliases,
                        )
                    )
        except MeshBundleImportError:
            raise
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            raise MeshBundleImportError("ARCHIVE_INVALID", "MESH ZIP 损坏或无法读取") from exc
        if not members:
            raise MeshBundleImportError("NO_SUPPORTED_MEMBERS", "ZIP 中没有可导入的 MESH 日志")
        _validate_ratio(expanded_total, archive_size, archive.name)
        return MeshBundleManifest(archive_sha256, archive_size, expanded_total, tuple(members))

    def create_preview(
        self,
        file_name: str,
        source: BinaryIO,
        profiles: Iterable[object],
        *,
        original_names: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        display_name = _safe_upload_name(file_name)
        preview_id = uuid4().hex
        root = self._preview_root()
        root.mkdir(parents=True, exist_ok=True)
        self._cleanup_preview_cache()
        preview_dir = self._preview_dir(preview_id)
        preview_dir.mkdir(parents=False, exist_ok=False)
        archive = preview_dir / "source.zip"
        try:
            _copy_upload(source, archive)
            manifest = self.inspect(archive, original_names=original_names)
            profile_rows = tuple(profiles)
            matches = self.match_profiles(manifest, profile_rows)
            candidates = {
                str(_profile_value(profile, "mr_id") or ""): str(
                    _profile_value(profile, "display_name") or ""
                )
                for profile in profile_rows
                if str(_profile_value(profile, "mr_id") or "")
            }
            now = datetime.now(timezone.utc).timestamp()
            meta = {
                "schema_version": _MANIFEST_SCHEMA_VERSION,
                "preview_id": preview_id,
                "site_id": self.site_name,
                "file_name": display_name,
                "created_at": now,
                "expires_at": now + _PREVIEW_TTL_SECONDS,
                "status": "ready",
                "manifest": manifest.to_dict(),
            }
            _write_json_atomic(preview_dir / "preview.json", meta)
            self._enforce_preview_capacity(preview_id)
            match_by_member = {match.member.member_id: match for match in matches}
            items: list[dict[str, object]] = []
            first_member_by_content: dict[str, str] = {}
            reserved_sequences: dict[tuple[str, str], int] = {}
            for member in manifest.members:
                match = match_by_member[member.member_id]
                content_matches = self._find_content_sources(member, backfill=False)
                batch_duplicate_of = first_member_by_content.get(member.content_sha256, "")
                first_member_by_content.setdefault(member.content_sha256, member.member_id)
                candidate_ids = match.candidate_profile_ids
                if match.profile_id:
                    candidate_ids = (match.profile_id,)
                if not candidate_ids:
                    candidate_ids = tuple(candidates)
                profile_states = []
                state_profile_ids = set(match.candidate_profile_ids)
                if match.profile_id:
                    state_profile_ids.add(match.profile_id)
                if len(candidates) == 1:
                    state_profile_ids.update(candidates)
                state_profile_ids.update(
                    str(item.get("profile_id") or "") for item in content_matches
                )
                if not state_profile_ids and candidate_ids:
                    # 保留既有顶层归档命名预览，但未知归属时只计算一个默认候选，
                    # 避免恢复 member × 全部 Profile 的目录扫描。
                    state_profile_ids.add(candidate_ids[0])
                for profile_id in candidate_ids:
                    if profile_id not in state_profile_ids:
                        continue
                    if profile_id not in candidates:
                        continue
                    state = self._preview_profile_state(
                        member,
                        profile_id,
                        candidates.get(profile_id, ""),
                        content_matches,
                    )
                    if not batch_duplicate_of:
                        state = self._reserve_preview_sequence(
                            member,
                            state,
                            reserved_sequences,
                        )
                    profile_states.append(state)
                selected_state = next(
                    (
                        state
                        for state in profile_states
                        if state["profile_id"] == (match.profile_id or "")
                    ),
                    None,
                )
                if selected_state is None:
                    selected_state = next(
                        (
                            state
                            for state in profile_states
                            if state.get("duplicate_status") != "new"
                        ),
                        None,
                    )
                if selected_state is None and profile_states:
                    selected_state = profile_states[0]
                items.append(
                    {
                        **member.to_dict(),
                        "train_number": member.train_number or "",
                        "role": member.role or "",
                        "match_status": "matched" if match.status == "matched" else match.status,
                        "selected_profile_id": match.profile_id or "",
                        "selected_profile_name": match.profile_name or "",
                        "stored_filename": str((selected_state or {}).get("stored_filename") or ""),
                        "daily_sequence": (selected_state or {}).get("daily_sequence"),
                        "duplicate_status": (
                            str((selected_state or {}).get("duplicate_status") or "new")
                            if not batch_duplicate_of
                            else "duplicate_in_current_batch"
                        ),
                        "batch_duplicate_of": batch_duplicate_of,
                        "import_allowed": bool(
                            (selected_state or {}).get("import_allowed", not match.profile_id)
                        ) and not batch_duplicate_of,
                        "existing_source_id": (selected_state or {}).get("existing_source_id"),
                        "existing_stored_filename": str(
                            (selected_state or {}).get("existing_stored_filename") or ""
                        ),
                        "existing_session_id": str(
                            (selected_state or {}).get("existing_session_id") or ""
                        ),
                        "existing_profile_id": str(
                            (selected_state or {}).get("existing_profile_id") or ""
                        ),
                        "existing_profile_name": str(
                            (selected_state or {}).get("existing_profile_name") or ""
                        ),
                        "profile_import_states": profile_states,
                        "candidates": [
                            {"profile_id": profile_id, "display_name": candidates[profile_id]}
                            for profile_id in candidate_ids
                            if profile_id in candidates
                        ],
                    }
                )
            return {
                "preview_id": preview_id,
                "file_name": display_name,
                "archive_sha256": manifest.archive_sha256,
                "archive_size_bytes": manifest.archive_size_bytes,
                "member_count": len(manifest.members),
                "duplicate_archive": self.is_archived(manifest.archive_sha256),
                "expires_at": datetime.fromtimestamp(meta["expires_at"], timezone.utc).isoformat(),
                "items": items,
            }
        except Exception:
            shutil.rmtree(preview_dir, ignore_errors=True)
            raise

    @staticmethod
    def _reserve_preview_sequence(
        member: MeshBundleMember,
        state: dict[str, object],
        reserved_sequences: dict[tuple[str, str], int],
    ) -> dict[str, object]:
        sequence = state.get("daily_sequence")
        if (
            state.get("duplicate_status") != "new"
            or state.get("rename_status")
            not in {"renamed_by_log_date_sequence", "timestamp_not_found"}
            or not isinstance(sequence, int)
        ):
            return state
        profile_id = str(state.get("profile_id") or "")
        log_date = (
            member.first_log_timestamp.date().isoformat()
            if member.first_log_timestamp
            else "unknown_date"
        )
        scope = (profile_id, log_date)
        reserved = max(sequence, reserved_sequences.get(scope, 0) + 1)
        reserved_sequences[scope] = reserved
        if reserved == sequence:
            return state
        stored_filename = str(state.get("stored_filename") or "")
        updated = dict(state)
        updated["daily_sequence"] = reserved
        updated["stored_filename"] = _ARCHIVE_SEQUENCE_RE.sub(
            lambda match: f"_{reserved}{match.group('tail')}",
            stored_filename,
        )
        return updated

    def _preview_profile_state(
        self,
        member: MeshBundleMember,
        profile_id: str,
        profile_name: str,
        matches: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        catalog = MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name))
        profile = catalog.get_profile(profile_id)
        if profile is None:
            return {
                "profile_id": profile_id,
                "duplicate_status": "hash_failed",
                "import_allowed": False,
            }
        matches = matches if matches is not None else self._find_content_sources(
            member, backfill=False
        )
        same = next((item for item in matches if item["profile_id"] == profile_id), None)
        other = next((item for item in matches if item["profile_id"] != profile_id), None)
        stored_filename, sequence, rename_status, rename_warning = suggest_mesh_archive_filename(
            self.paths.mesh_mr_raw_dir(self.site_name, profile.safe_folder_name),
            Path(member.safe_name).name,
            member.first_log_timestamp,
        )
        existing = same or other
        duplicate_status = "duplicate_same_mr" if same else "duplicate_other_mr" if other else "new"
        return {
            "profile_id": profile_id,
            "profile_name": profile_name,
            "stored_filename": stored_filename,
            "daily_sequence": sequence,
            "rename_status": rename_status,
            "rename_warning": rename_warning,
            "duplicate_status": duplicate_status,
            "import_allowed": existing is None,
            "existing_source_id": (existing or {}).get("source_id"),
            "existing_stored_filename": str((existing or {}).get("stored_filename") or ""),
            "existing_session_id": str((existing or {}).get("session_id") or ""),
            "existing_profile_id": str((existing or {}).get("profile_id") or ""),
            "existing_profile_name": str((existing or {}).get("profile_name") or ""),
        }

    def approve_preview(
        self,
        preview_id: str,
        mappings: Iterable[Mapping[str, object]],
        profile_ids: Iterable[str],
    ) -> tuple[MeshBundleManifest, tuple[dict[str, str], ...]]:
        preview_dir, archive, meta, manifest = self.load_preview(preview_id)
        allowed_profiles = {str(profile_id) for profile_id in profile_ids}
        members = {member.member_id: member for member in manifest.members}
        approved: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in mappings:
            member_id = str(value.get("member_id") or "").strip()
            profile_id = str(value.get("profile_id") or "").strip()
            train_number = str(value.get("train_number") or "").strip()
            role = str(value.get("role") or "").strip().upper()
            if member_id not in members or member_id in seen:
                raise MeshBundleImportError("MAPPING_MEMBER_INVALID", "MESH ZIP 文件映射无效或重复")
            if profile_id not in allowed_profiles:
                raise MeshBundleImportError("MAPPING_PROFILE_INVALID", "MESH ZIP 映射的 Profile 不存在")
            if not re.fullmatch(r"\d{1,3}", train_number) or role not in {"CT", "CW"}:
                raise MeshBundleImportError("MAPPING_IDENTITY_INVALID", "列车号或 CT/CW 端位无效")
            seen.add(member_id)
            approved.append(
                {
                    "member_id": member_id,
                    "profile_id": profile_id,
                    "train_number": train_number,
                    "role": role,
                }
            )
        if seen != set(members):
            raise MeshBundleImportError("MAPPING_INCOMPLETE", "必须确认 ZIP 中每个 MESH 日志的映射")
        current = self.inspect(
            archive,
            original_names=_manifest_original_names(manifest),
        )
        if current != manifest:
            raise MeshBundleImportError("PREVIEW_CHANGED", "MESH ZIP 预览内容已变化，请重新预览")
        member_by_id = {member.member_id: member for member in manifest.members}
        profile_by_content: dict[str, str] = {}
        filtered: list[dict[str, str]] = []
        batch_duplicates: list[dict[str, str]] = []
        for mapping in approved:
            member = member_by_id[mapping["member_id"]]
            previous_profile = profile_by_content.get(member.content_sha256)
            if previous_profile and previous_profile != mapping["profile_id"]:
                raise MeshBundleImportError(
                    "DUPLICATE_CONTENT_CROSS_PROFILE",
                    "同一批次存在相同日志正文但映射到不同 MR，请检查 CT/CW、列车号和 MR 归属",
                )
            matches = self._find_content_sources(member, backfill=False)
            same = next(
                (item for item in matches if item["profile_id"] == mapping["profile_id"]),
                None,
            )
            other = next(
                (item for item in matches if item["profile_id"] != mapping["profile_id"]),
                None,
            )
            if same is None and other is not None:
                raise MeshBundleImportError(
                    "DUPLICATE_CONTENT_OTHER_MR",
                    f"日志正文已归属于其他 MR：{other['profile_name']}，请检查映射",
                )
            if previous_profile:
                batch_duplicates.append(mapping)
                continue
            profile_by_content[member.content_sha256] = mapping["profile_id"]
            filtered.append(mapping)
        meta["status"] = "submitted"
        meta["expires_at"] = datetime.now(timezone.utc).timestamp() + _SUBMITTED_PREVIEW_TTL_SECONDS
        meta["submitted_mappings"] = approved
        meta["approved_mappings"] = filtered
        meta["batch_duplicate_mappings"] = batch_duplicates
        _write_json_atomic(preview_dir / "preview.json", meta)
        return manifest, tuple(filtered)

    def load_preview(
        self,
        preview_id: str,
    ) -> tuple[Path, Path, dict[str, object], MeshBundleManifest]:
        preview_dir = self._preview_dir(preview_id)
        meta_path = preview_dir / "preview.json"
        archive = preview_dir / "source.zip"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MeshBundleImportError("PREVIEW_NOT_FOUND", "MESH ZIP 预览不存在或已清理") from exc
        if not isinstance(meta, dict) or meta.get("site_id") != self.site_name:
            raise MeshBundleImportError("PREVIEW_NOT_FOUND", "MESH ZIP 预览不存在或不属于当前局点")
        if float(meta.get("expires_at") or 0) <= datetime.now(timezone.utc).timestamp():
            shutil.rmtree(preview_dir, ignore_errors=True)
            raise MeshBundleImportError("PREVIEW_EXPIRED", "MESH ZIP 预览已过期，请重新预览")
        if not archive.is_file():
            raise MeshBundleImportError("PREVIEW_NOT_FOUND", "MESH ZIP 预览文件已清理")
        value = meta.get("manifest")
        if not isinstance(value, Mapping):
            raise MeshBundleImportError("PREVIEW_INVALID", "MESH ZIP 预览元数据无效")
        return preview_dir, archive, meta, MeshBundleManifest.from_dict(value)

    def match_profiles(
        self,
        manifest: MeshBundleManifest,
        profiles: Iterable[object],
    ) -> tuple[MeshBundleProfileMatch, ...]:
        indexed: dict[tuple[str, str], list[object]] = {}
        for profile in profiles:
            name = str(_profile_value(profile, "display_name") or "")
            profile_id = str(_profile_value(profile, "mr_id") or "")
            identity = _profile_identity(name)
            if identity and profile_id:
                indexed.setdefault(identity, []).append(profile)
        matches: list[MeshBundleProfileMatch] = []
        for member in manifest.members:
            if not member.train_number or not member.role:
                matches.append(MeshBundleProfileMatch(member, "unmatched"))
                continue
            candidates: list[object] = []
            for alias in member.train_aliases:
                candidates.extend(indexed.get((alias, member.role), ()))
            unique = {str(_profile_value(item, "mr_id")): item for item in candidates}
            if len(unique) == 1:
                profile = next(iter(unique.values()))
                matches.append(
                    MeshBundleProfileMatch(
                        member,
                        "matched",
                        str(_profile_value(profile, "mr_id")),
                        str(_profile_value(profile, "display_name")),
                    )
                )
            elif len(unique) > 1:
                matches.append(
                    MeshBundleProfileMatch(
                        member,
                        "ambiguous",
                        candidate_profile_ids=tuple(sorted(unique)),
                    )
                )
            else:
                matches.append(MeshBundleProfileMatch(member, "unmatched"))
        return tuple(matches)

    @contextmanager
    def extract(
        self,
        archive: Path,
        manifest: MeshBundleManifest | None = None,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Iterator[tuple[tuple[MeshBundleMember, Path], ...]]:
        selected = manifest or self.inspect(archive)
        directory = self._transaction_root() / f".extract-{uuid4().hex}"
        directory.mkdir(parents=True, exist_ok=False)
        try:
            extracted: list[tuple[MeshBundleMember, Path]] = []
            with zipfile.ZipFile(archive) as source:
                entries = {
                    _safe_member_name(entry.filename): entry
                    for entry in source.infolist()
                    if not entry.is_dir()
                }
                expanded_total = 0
                for member in selected.members:
                    _raise_if_cancelled(should_cancel)
                    entry = entries.get(member.internal_member_name)
                    if entry is None:
                        raise MeshBundleImportError("PREVIEW_CHANGED", "MESH ZIP 成员已变化")
                    compressed_target = (
                        directory
                        / f"{member.file_order:06d}"
                        / Path(member.safe_name).name
                    )
                    compressed_target.parent.mkdir(parents=True, exist_ok=True)
                    copied = _copy_limited(source.open(entry), compressed_target, _MAX_FILE_SIZE)
                    if copied != member.size_bytes or _sha256_file(compressed_target) != member.sha256:
                        raise MeshBundleImportError("MEMBER_HASH_MISMATCH", f"ZIP 成员校验失败：{member.original_name}")
                    expanded_total += member.expanded_size_bytes
                    if expanded_total > _MAX_BUNDLE_SIZE:
                        raise MeshBundleImportError("EXPANDED_SIZE_EXCEEDED", "MESH ZIP 解压总大小超过 100 MiB")
                    extracted.append((member, compressed_target))
            yield tuple(extracted)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def import_approved_preview(
        self,
        preview_id: str,
        mappings: Iterable[Mapping[str, object]],
        *,
        job_id: str,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[str, int, int, str], None] | None = None,
    ) -> dict[str, object]:
        _preview_dir, archive, meta, manifest = self.load_preview(preview_id)
        approved = tuple(dict(item) for item in mappings)
        if approved != tuple(meta.get("approved_mappings") or ()):
            raise MeshBundleImportError("MAPPING_CHANGED", "MESH ZIP 映射与已确认预览不一致")
        if self.is_archived(manifest.archive_sha256):
            profiles = self._profiles_for_mappings(approved)
            return {
                "archive_sha256": manifest.archive_sha256,
                "member_count": len(manifest.members),
                "imported_count": 0,
                "duplicate_count": len(manifest.members),
                "created_session_ids": self._created_session_ids(profiles, approved, manifest),
                "idempotent": True,
            }
        lock = self._acquire_import_lock(job_id)
        transaction = self._transaction_root() / f".{job_id}.staging"
        rollback = self._transaction_root() / f".{job_id}.rollback"
        try:
            _raise_if_cancelled(should_cancel)
            if self.is_archived(manifest.archive_sha256):
                profiles = self._profiles_for_mappings(approved)
                return {
                    "archive_sha256": manifest.archive_sha256,
                    "member_count": len(manifest.members),
                    "imported_count": 0,
                    "duplicate_count": len(manifest.members),
                    "created_session_ids": self._created_session_ids(profiles, approved, manifest),
                    "idempotent": True,
                }
            current = self.inspect(
                archive,
                original_names=_manifest_original_names(manifest),
            )
            if current != manifest:
                raise MeshBundleImportError("PREVIEW_CHANGED", "MESH ZIP 预览内容已变化，请重新预览")
            members_by_id = {member.member_id: member for member in manifest.members}
            for mapping in approved:
                member = members_by_id[str(mapping["member_id"])]
                matches = self._find_content_sources(member, backfill=True)
                same = next(
                    (item for item in matches if item["profile_id"] == mapping["profile_id"]),
                    None,
                )
                other = next(
                    (item for item in matches if item["profile_id"] != mapping["profile_id"]),
                    None,
                )
                if same is None and other is not None:
                    raise MeshBundleImportError(
                        "DUPLICATE_CONTENT_OTHER_MR",
                        f"日志正文已归属于其他 MR：{other['profile_name']}，请检查映射",
                    )
            profiles = self._profiles_for_mappings(approved)
            self._ensure_identity_snapshot_current()
            self._prepare_transaction(transaction, profiles)
            staging_paths = PathResolver(
                app_root=self.paths.app_root,
                data_root=transaction / "data-root",
            )
            member_paths: dict[str, Path] = {}
            import_hashes: dict[str, str] = {}
            with self.extract(archive, manifest, should_cancel=should_cancel) as extracted:
                member_paths = {member.member_id: path for member, path in extracted}
                import_hashes = {
                    member.member_id: _sha256_file(path)
                    for member, path in extracted
                }
                statuses, counts = self._import_staging_profiles(
                    staging_paths,
                    profiles,
                    approved,
                    member_paths,
                    should_cancel=should_cancel,
                    progress=progress,
                )
            batch_duplicates = tuple(
                dict(item)
                for item in meta.get("batch_duplicate_mappings") or ()
                if isinstance(item, Mapping)
            )
            counts["duplicate_count"] += len(batch_duplicates)
            _raise_if_cancelled(should_cancel)
            self._rewrite_staging_paths(staging_paths, profiles, manifest, import_hashes)
            self._checkpoint_tree(staging_paths.site_mesh_root(self.site_name))
            member_paths.clear()
            import_hashes.clear()
            gc.collect()
            source_results = (
                counts["source_results"]
                if isinstance(counts.get("source_results"), list)
                else []
            )
            source_result_by_content = {
                str(item.get("content_sha256") or ""): item
                for item in source_results
                if isinstance(item, Mapping)
            }
            success_manifest = {
                **manifest.to_dict(),
                "status": "success",
                "site_id": self.site_name,
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "parser_version": PARSER_VERSION,
                "parsed_schema_version": SCHEMA_VERSION,
                "file_mappings": [
                    {
                        **mapping,
                        **members_by_id[str(mapping["member_id"])].to_dict(),
                        **source_result_by_content.get(
                            members_by_id[str(mapping["member_id"])].content_sha256,
                            {},
                        ),
                        "status": statuses[mapping["member_id"]],
                    }
                    for mapping in approved
                ]
                + [
                    {
                        **mapping,
                        **members_by_id[str(mapping["member_id"])].to_dict(),
                        "status": "duplicate_in_current_batch",
                    }
                    for mapping in batch_duplicates
                ],
            }
            self._commit_transaction(
                rollback,
                staging_paths,
                profiles,
                archive,
                manifest,
                success_manifest,
            )
            self._publish_catalog_fingerprints(source_results)
            created_session_ids = self._created_session_ids(profiles, approved, manifest)
            return {
                "archive_sha256": manifest.archive_sha256,
                "member_count": len(manifest.members),
                "imported_count": counts["imported_count"],
                "duplicate_count": counts["duplicate_count"],
                "parsed_record_count": counts["parsed_record_count"],
                "issue_count": counts["issue_count"],
                "raw_archived_count": counts["imported_count"],
                "parsed_source_count": counts["imported_count"],
                "created_session_ids": created_session_ids,
                "source_results": counts["source_results"],
                "failed_files": [],
                "idempotent": False,
            }
        finally:
            shutil.rmtree(transaction, ignore_errors=True)
            shutil.rmtree(rollback, ignore_errors=True)
            self._release_import_lock(lock)

    def _publish_catalog_fingerprints(
        self,
        source_results: Iterable[Mapping[str, object]],
    ) -> None:
        rows = [
            {
                "content_sha256": item.get("content_sha256"),
                "raw_sha256": item.get("raw_sha256"),
                "mr_id": item.get("profile_id"),
                "source_file_id": item.get("source_id"),
                "stored_filename": item.get("stored_filename"),
            }
            for item in source_results
            if item.get("profile_id") and item.get("source_id")
        ]
        catalog = MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name))
        try:
            catalog.upsert_source_fingerprints(rows)
            catalog.mark_index_pending()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            # 业务数据已原子提交；派生目录失败时保留导入成功并交由后台重建补齐。
            app_logger.log_warning(
                "MESH_CATALOG_FINGERPRINT_PUBLISH_FAILED",
                f"site={self.site_name} error={exc}",
            )

    def is_archived(self, archive_sha256: str) -> bool:
        manifest_path = self._bundle_dir(archive_sha256) / "manifest.json"
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(value, dict) and value.get("status") == "success" and value.get("archive_sha256") == archive_sha256

    def _find_content_sources(
        self,
        member: MeshBundleMember,
        *,
        backfill: bool,
    ) -> list[dict[str, object]]:
        del backfill  # 历史缺失指纹由低优先级目录回填处理，预览不得读取历史原始日志。
        rows = MeshCatalogRepository(
            self.paths.mesh_catalog_path(self.site_name)
        ).find_source_fingerprints(
            content_sha256=member.content_sha256,
            raw_sha256=member.raw_sha256,
        )
        return [
            {
                "source_id": int(row["source_file_id"]),
                "stored_filename": str(row.get("stored_filename") or ""),
                "profile_id": str(row["mr_id"]),
                "profile_name": str(row.get("profile_name") or ""),
                "session_id": f"{row['mr_id']}:{int(row['source_file_id'])}",
            }
            for row in rows
        ]

    @staticmethod
    def _find_legacy_content_source(
        database: Path,
        member: MeshBundleMember,
    ) -> dict[str, object] | None:
        for row in MeshSourceIndexRepository(database).list_source_files():
            raw_sha256 = str(row.get("raw_sha256") or row.get("sha256") or "")
            content_sha256 = str(row.get("content_sha256") or "")
            if raw_sha256 == member.raw_sha256 or content_sha256 == member.content_sha256:
                return row
            archived = Path(str(row.get("archived_path") or ""))
            if not archived.is_file():
                continue
            try:
                metadata = inspect_mesh_log_path(archived, max_expanded_size=_MAX_FILE_SIZE)
            except (OSError, ValueError, gzip.BadGzipFile):
                continue
            if metadata.content_sha256 == member.content_sha256:
                return row
        return None

    def _backfill_profile_fingerprints(
        self,
        profile: MeshMrProfile,
        repository: MeshMrRepository,
    ) -> None:
        if profile.mr_id in self._fingerprints_backfilled:
            return
        self._fingerprints_backfilled.add(profile.mr_id)
        for row in repository.list_source_files():
            if str(row.get("content_sha256") or "").strip():
                continue
            archived = Path(str(row.get("archived_path") or ""))
            if not archived.is_file():
                continue
            try:
                metadata = inspect_mesh_log_path(archived, max_expanded_size=_MAX_FILE_SIZE)
                repository.update_source_fingerprints(
                    int(row["id"]),
                    raw_sha256=metadata.raw_sha256,
                    content_sha256=metadata.content_sha256,
                    first_log_timestamp=metadata.first_log_timestamp,
                    last_log_timestamp=metadata.last_log_timestamp,
                )
            except (OSError, ValueError, gzip.BadGzipFile, sqlite3.IntegrityError):
                continue

    def _created_session_ids(
        self,
        profiles: Mapping[str, MeshMrProfile],
        mappings: tuple[dict[str, object], ...],
        manifest: MeshBundleManifest,
    ) -> list[str]:
        members = {member.member_id: member for member in manifest.members}
        result: list[str] = []
        for mapping in mappings:
            profile = profiles[str(mapping["profile_id"])]
            member = members[str(mapping["member_id"])]
            repository = MeshMrRepository(self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name))
            source = repository.find_by_content_sha256(
                member.content_sha256,
                raw_sha256=member.raw_sha256,
            )
            if source is not None:
                result.append(f"{profile.mr_id}:{int(source['id'])}")
        return result

    def _profiles_for_mappings(
        self,
        mappings: Iterable[Mapping[str, object]],
    ) -> dict[str, MeshMrProfile]:
        repository = MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name))
        profiles: dict[str, MeshMrProfile] = {}
        for mapping in mappings:
            profile_id = str(mapping.get("profile_id") or "")
            if profile_id in profiles:
                continue
            profile = repository.get_profile(profile_id)
            if profile is None:
                raise MeshBundleImportError("MAPPING_PROFILE_INVALID", "MESH ZIP 映射的 Profile 不存在")
            profiles[profile_id] = profile
        return profiles

    def _prepare_transaction(
        self,
        transaction: Path,
        profiles: Mapping[str, MeshMrProfile],
    ) -> None:
        if transaction.exists():
            raise MeshBundleImportError("TRANSACTION_CONFLICT", "MESH ZIP 导入临时事务已存在")
        staging_paths = PathResolver(app_root=self.paths.app_root, data_root=transaction / "data-root")
        staging_paths.ensure_site_dirs(self.site_name)
        source_meta = self.paths.site_dir(self.site_name) / "site_meta.json"
        if source_meta.is_file():
            shutil.copy2(source_meta, staging_paths.site_dir(self.site_name) / "site_meta.json")
        source_db = self.paths.site_db_path(self.site_name)
        if source_db.is_file():
            _sqlite_backup(source_db, staging_paths.site_db_path(self.site_name))
        source_catalog = self.paths.mesh_catalog_path(self.site_name)
        if not source_catalog.is_file():
            raise MeshBundleImportError("CATALOG_NOT_FOUND", "MESH Profile 目录库不存在")
        _sqlite_backup(source_catalog, staging_paths.mesh_catalog_path(self.site_name))
        for profile in profiles.values():
            source = self.paths.mesh_mr_root(self.site_name, profile.safe_folder_name).resolve()
            target = staging_paths.mesh_mr_root(self.site_name, profile.safe_folder_name).resolve()
            _require_child(source, self.paths.site_mesh_root(self.site_name).resolve())
            _require_child(target, staging_paths.site_mesh_root(self.site_name).resolve())
            if not source.is_dir():
                raise MeshBundleImportError("PROFILE_STORAGE_NOT_FOUND", "MESH Profile 数据目录不存在")
            _copy_tree_snapshot(source, target)
            if MeshMrRepository._is_compact_schema(target / "mesh.sqlite"):
                self._rewrite_snapshot_paths_to_staging(source, target)

    def _ensure_identity_snapshot_current(self) -> None:
        database_path = self.paths.site_db_path(self.site_name)
        if not database_path.is_file():
            return
        result = ApIdentityQueryService(Database(database_path)).ensure_index(
            "mesh_bundle_import_snapshot"
        )
        if result is None:
            return
        event = (
            "AP_IDENTITY_BASE_ONLY_BUILD_COMPLETED"
            if result.ac_record_count == 0
            else "AP_IDENTITY_INDEX_BUILD_COMPLETED"
        )
        app_logger.log_info(
            event,
            (
                f"site={self.site_name} revision={result.revision} "
                f"source_revision={result.source_revision} "
                f"base_records={result.base_record_count} "
                f"derived_aliases={result.derived_alias_count}"
            ),
        )

    def _rewrite_snapshot_paths_to_staging(
        self,
        production_profile: Path,
        staging_profile: Path,
    ) -> None:
        index_path = staging_profile / "mesh.sqlite"
        with closing(sqlite3.connect(index_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT id, archived_path, parsed_db_path FROM source_files"
            ).fetchall()
            for row in rows:
                production_archived = Path(str(row["archived_path"] or "")).resolve()
                production_parsed = Path(str(row["parsed_db_path"] or "")).resolve()
                _require_child(production_archived, production_profile)
                _require_child(production_parsed, production_profile)
                staging_archived = staging_profile / production_archived.relative_to(production_profile)
                staging_parsed = staging_profile / production_parsed.relative_to(production_profile)
                if not staging_archived.is_file() or not staging_parsed.is_file():
                    raise MeshBundleImportError("PROFILE_SNAPSHOT_INVALID", "MESH Profile 隔离副本不完整")
                connection.execute(
                    "UPDATE source_files SET archived_path = ?, parsed_db_path = ? WHERE id = ?",
                    (str(staging_archived), str(staging_parsed), int(row["id"])),
                )
                with closing(sqlite3.connect(staging_parsed)) as detail:
                    detail.execute(
                        "UPDATE source_files SET archived_path = ? WHERE archived_path = ?",
                        (str(staging_archived), str(production_archived)),
                    )
                    detail.execute(
                        "UPDATE parse_issues SET source_file = ? WHERE source_file = ?",
                        (str(staging_archived), str(production_archived)),
                    )
                    detail.commit()
            connection.commit()

    def _import_staging_profiles(
        self,
        staging_paths: PathResolver,
        profiles: Mapping[str, MeshMrProfile],
        mappings: tuple[dict[str, object], ...],
        member_paths: Mapping[str, Path],
        *,
        should_cancel: Callable[[], bool] | None,
        progress: Callable[[str, int, int, str], None] | None,
    ) -> tuple[dict[str, str], dict[str, object]]:
        grouped: dict[str, list[dict[str, object]]] = {}
        for mapping in mappings:
            grouped.setdefault(str(mapping["profile_id"]), []).append(mapping)
        statuses: dict[str, str] = {}
        counts = {
            "imported_count": 0,
            "duplicate_count": 0,
            "parsed_record_count": 0,
            "issue_count": 0,
            "source_results": [],
        }
        completed = 0
        total = len(mappings)
        for profile_id, rows in grouped.items():
            _raise_if_cancelled(should_cancel)
            profile = profiles[profile_id]
            service = MeshImportService(self.site_name, staging_paths)
            try:
                repository = service.storage.mr_repository(profile)
            except MeshSchemaRebuildRequired:
                legacy_sources = MeshSourceIndexRepository(
                    staging_paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name)
                ).list_source_files()
                MeshParsedRebuildService(staging_paths).rebuild(
                    self.site_name,
                    profile.mr_id,
                    should_cancel=should_cancel,
                )
                self._discard_staging_schema_archives(
                    staging_paths.mesh_mr_root(self.site_name, profile.safe_folder_name)
                )
                repository = service.storage.mr_repository(profile)
                self._restore_rebuilt_provenance(repository, legacy_sources)
            files: list[Path] = []
            for row in rows:
                member_id = str(row["member_id"])
                source = member_paths[member_id]
                metadata = inspect_mesh_log_path(source, max_expanded_size=_MAX_FILE_SIZE)
                statuses[member_id] = (
                    "duplicate_same_mr"
                    if repository.has_content_sha256(
                        metadata.content_sha256,
                        raw_sha256=metadata.raw_sha256,
                    )
                    else "imported"
                )
                files.append(source)

            def on_progress(file_index: int, _total: int, lines: int, parsed: int, skipped: int) -> None:
                if progress:
                    progress(
                        f"mesh_bundle_import:{lines}:{parsed}:{skipped}",
                        min(total, completed + file_index),
                        total,
                        "正在隔离导入 MESH ZIP 日志",
                    )

            result = service.import_files(
                profile,
                files,
                should_cancel=should_cancel,
                progress=on_progress,
            )
            _raise_if_cancelled(should_cancel)
            completed += len(rows)
            counts["imported_count"] += result.imported_count
            counts["duplicate_count"] += result.duplicate_count
            counts["parsed_record_count"] += result.parsed_record_count
            counts["issue_count"] += len(result.issues)
            source_results = counts["source_results"]
            if isinstance(source_results, list):
                source_results.extend(result.source_results)
            if progress:
                progress("mesh_bundle_import", completed, total, "MESH ZIP Profile 导入完成")
        return statuses, counts

    @staticmethod
    def _discard_staging_schema_archives(profile_root: Path) -> None:
        for archive in profile_root.glob("*.schema_archive_*"):
            _require_child(archive.resolve(), profile_root.resolve())
            if archive.is_symlink():
                raise MeshBundleImportError("PROFILE_STORAGE_INVALID", "MESH staging 归档不能是符号链接")
            if archive.is_dir():
                shutil.rmtree(archive)
            else:
                archive.unlink()

    @staticmethod
    def _restore_rebuilt_provenance(
        repository: MeshMrRepository,
        legacy_sources: list[dict[str, object]],
    ) -> None:
        rebuilt = {str(row.get("sha256") or ""): row for row in repository.list_source_files()}
        for legacy in legacy_sources:
            row = rebuilt.get(str(legacy.get("sha256") or ""))
            if row is None:
                continue
            repository.update_source_provenance(
                int(row["id"]),
                raw_relative_path=str(row.get("raw_relative_path") or ""),
                parsed_relative_path=str(row.get("parsed_relative_path") or ""),
                archive_sha256=str(legacy.get("archive_sha256") or ""),
                bundle_member_id=str(legacy.get("bundle_member_id") or ""),
                bundle_member_sha256=str(legacy.get("bundle_member_sha256") or ""),
            )

    def _rewrite_staging_paths(
        self,
        staging_paths: PathResolver,
        profiles: Mapping[str, MeshMrProfile],
        manifest: MeshBundleManifest,
        import_hashes: Mapping[str, str],
    ) -> None:
        originals_by_sha: dict[str, str] = {}
        members_by_sha: dict[str, MeshBundleMember] = {}
        for member in manifest.members:
            digest = import_hashes.get(member.member_id, member.sha256)
            originals_by_sha.setdefault(digest, member.original_name)
            members_by_sha.setdefault(digest, member)
        stale_root = str(staging_paths.data_root.resolve())
        for profile in profiles.values():
            staging_profile = staging_paths.mesh_mr_root(self.site_name, profile.safe_folder_name).resolve()
            final_profile = self.paths.mesh_mr_root(self.site_name, profile.safe_folder_name).resolve()
            index_path = staging_profile / "mesh.sqlite"
            with closing(sqlite3.connect(index_path)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT id, sha256, original_path, original_filename, archived_filename,
                           archived_path, parsed_db_path,
                           archive_sha256, bundle_member_id, bundle_member_sha256
                    FROM source_files
                    """
                ).fetchall()
                for row in rows:
                    staging_archived = Path(str(row["archived_path"] or "")).resolve()
                    _require_child(staging_archived, staging_profile)
                    if not staging_archived.is_file():
                        raise MeshBundleImportError("STAGING_RAW_MISSING", "隔离导入的 raw 日志不存在")
                    final_archived = final_profile / staging_archived.relative_to(staging_profile)
                    staging_parsed = Path(str(row["parsed_db_path"] or "")).resolve()
                    _require_child(staging_parsed, staging_profile)
                    if not staging_parsed.is_file():
                        raise MeshBundleImportError("STAGING_PARSED_MISSING", "隔离导入的 parsed 数据库不存在")
                    final_parsed = final_profile / staging_parsed.relative_to(staging_profile)
                    original_name = originals_by_sha.get(
                        str(row["sha256"] or ""),
                        str(row["original_filename"] or row["archived_filename"] or staging_archived.name),
                    )
                    member = members_by_sha.get(str(row["sha256"] or ""))
                    raw_relative = final_archived.relative_to(final_profile).as_posix()
                    parsed_relative = final_parsed.relative_to(final_profile).as_posix()
                    connection.execute(
                        """
                        UPDATE source_files
                        SET original_path = ?, archived_path = ?, parsed_db_path = ?,
                            raw_relative_path = ?, parsed_relative_path = ?, archive_sha256 = ?,
                            bundle_member_id = ?, bundle_member_sha256 = ?
                        WHERE id = ?
                        """,
                        (
                            original_name,
                            str(final_archived),
                            str(final_parsed),
                            raw_relative,
                            parsed_relative,
                            manifest.archive_sha256 if member else str(row["archive_sha256"] or ""),
                            member.member_id if member else str(row["bundle_member_id"] or ""),
                            member.sha256 if member else str(row["bundle_member_sha256"] or ""),
                            int(row["id"]),
                        ),
                    )
                    with closing(sqlite3.connect(staging_parsed)) as detail:
                        detail.execute(
                            "UPDATE source_files SET original_path = ?, archived_path = ?",
                            (original_name, str(final_archived)),
                        )
                        detail.execute(
                            "UPDATE parse_issues SET source_file = ? WHERE source_file = ?",
                            (str(final_archived), str(staging_archived)),
                        )
                        detail.commit()
                    _assert_no_stale_path(staging_parsed, stale_root)
                connection.commit()
            _assert_no_stale_path(index_path, stale_root)

    def _commit_transaction(
        self,
        rollback: Path,
        staging_paths: PathResolver,
        profiles: Mapping[str, MeshMrProfile],
        archive: Path,
        manifest: MeshBundleManifest,
        success_manifest: Mapping[str, object],
    ) -> None:
        rollback.mkdir(parents=True, exist_ok=False)
        published: list[_ProfilePublishState] = []
        production_catalog = self.paths.mesh_catalog_path(self.site_name)
        staging_catalog = staging_paths.mesh_catalog_path(self.site_name)
        previous_catalog_summaries = _read_catalog_summaries(
            production_catalog,
            profiles,
        )
        staged_catalog_summaries = _read_catalog_summaries(
            staging_catalog,
            profiles,
        )
        catalog_updated = False
        try:
            for profile in sorted(profiles.values(), key=lambda item: item.safe_folder_name.casefold()):
                production = self.paths.mesh_mr_root(self.site_name, profile.safe_folder_name).resolve()
                staging = staging_paths.mesh_mr_root(self.site_name, profile.safe_folder_name).resolve()
                state = _ProfilePublishState(
                    production_root=production,
                    rollback_root=rollback / profile.safe_folder_name,
                    created_files=[],
                    overwritten_files=[],
                    created_directories=[],
                )
                published.append(state)
                _publish_profile_snapshot(staging, state)
            self._verify_final_paths(profiles)
            _write_catalog_summaries(production_catalog, staged_catalog_summaries)
            catalog_updated = True
            self._finalize_archive(archive, manifest, success_manifest)
        except Exception:
            rollback_error: Exception | None = None
            try:
                if catalog_updated:
                    _write_catalog_summaries(
                        production_catalog,
                        previous_catalog_summaries,
                    )
            except Exception as exc:
                rollback_error = exc
            finally:
                for state in reversed(published):
                    try:
                        _rollback_profile_snapshot(state)
                    except Exception as exc:
                        rollback_error = rollback_error or exc
            if rollback_error is not None:
                raise MeshBundleImportError(
                    "ROLLBACK_FAILED",
                    "MESH ZIP 导入回滚失败，请保留现场数据并检查 Backend 日志",
                ) from rollback_error
            raise

    def _verify_final_paths(self, profiles: Mapping[str, MeshMrProfile]) -> None:
        for profile in profiles.values():
            profile_root = self.paths.mesh_mr_root(self.site_name, profile.safe_folder_name).resolve()
            index_path = profile_root / "mesh.sqlite"
            with closing(sqlite3.connect(index_path)) as connection:
                rows = connection.execute(
                    "SELECT archived_path, parsed_db_path FROM source_files"
                ).fetchall()
            for archived_value, parsed_value in rows:
                archived = Path(str(archived_value or "")).resolve()
                parsed = Path(str(parsed_value or "")).resolve()
                _require_child(archived, profile_root)
                _require_child(parsed, profile_root)
                if not archived.is_file() or not parsed.is_file():
                    raise MeshBundleImportError("COMMIT_PATH_INVALID", "MESH ZIP 提交后的 raw/parsed 路径校验失败")

    def _finalize_archive(
        self,
        archive: Path,
        manifest: MeshBundleManifest,
        success_manifest: Mapping[str, object],
    ) -> None:
        root = self._bundle_root()
        root.mkdir(parents=True, exist_ok=True)
        final = self._bundle_dir(manifest.archive_sha256)
        if final.exists():
            if self.is_archived(manifest.archive_sha256):
                return
            raise MeshBundleImportError("ARCHIVE_CONFLICT", "同 SHA 的 MESH ZIP 归档状态异常")
        staging = root / f".{manifest.archive_sha256}.{uuid4().hex}.staging"
        try:
            staging.mkdir(parents=False, exist_ok=False)
            shutil.copy2(archive, staging / "source.zip")
            if _sha256_file(staging / "source.zip") != manifest.archive_sha256:
                raise MeshBundleImportError("ARCHIVE_HASH_MISMATCH", "MESH ZIP 正式归档校验失败")
            _write_json_atomic(staging / "manifest.json", dict(success_manifest))
            staging.replace(final)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _checkpoint_tree(self, root: Path) -> None:
        for path in root.rglob("*.sqlite"):
            _checkpoint_database(path)

    def _preview_root(self) -> Path:
        return (self.paths.runtime_cache_dir / "mesh_bundle_previews" / self.site_name).resolve()

    def _preview_dir(self, preview_id: str) -> Path:
        value = str(preview_id or "").strip().casefold()
        if not _PREVIEW_ID_RE.fullmatch(value):
            raise MeshBundleImportError("PREVIEW_ID_INVALID", "MESH ZIP 预览标识无效")
        root = self._preview_root()
        path = (root / value).resolve()
        _require_child(path, root)
        return path

    def _cleanup_preview_cache(self) -> None:
        root = self._preview_root()
        if not root.exists():
            return
        now = datetime.now(timezone.utc).timestamp()
        for path in root.iterdir():
            if not path.is_dir() or not _PREVIEW_ID_RE.fullmatch(path.name):
                continue
            try:
                meta = json.loads((path / "preview.json").read_text(encoding="utf-8"))
                expired = float(meta.get("expires_at") or 0) <= now
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                expired = True
            if expired:
                shutil.rmtree(path, ignore_errors=True)

    def _enforce_preview_capacity(self, current_preview_id: str) -> None:
        root = self._preview_root()
        entries: list[tuple[float, Path, int, str]] = []
        for path in root.iterdir():
            if not path.is_dir() or not _PREVIEW_ID_RE.fullmatch(path.name):
                continue
            try:
                meta = json.loads((path / "preview.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
            size = (path / "source.zip").stat().st_size if (path / "source.zip").is_file() else 0
            entries.append((float(meta.get("created_at") or 0), path, size, str(meta.get("status") or "")))
        total = sum(item[2] for item in entries)
        for _created, path, size, status_value in sorted(entries):
            if len(entries) <= _MAX_PREVIEW_COUNT and total <= _MAX_PREVIEW_BYTES:
                break
            if path.name == current_preview_id or status_value == "submitted":
                continue
            shutil.rmtree(path, ignore_errors=True)
            entries = [item for item in entries if item[1] != path]
            total -= size
        if len(entries) > _MAX_PREVIEW_COUNT or total > _MAX_PREVIEW_BYTES:
            raise MeshBundleImportError("PREVIEW_CACHE_FULL", "MESH ZIP 预览缓存已满，请等待现有任务完成")

    def _bundle_root(self) -> Path:
        return (self.paths.site_mesh_root(self.site_name) / "bundles").resolve()

    def _bundle_dir(self, archive_sha256: str) -> Path:
        value = str(archive_sha256 or "").strip().casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise MeshBundleImportError("ARCHIVE_SHA_INVALID", "MESH ZIP SHA-256 无效")
        root = self._bundle_root()
        path = (root / value).resolve()
        _require_child(path, root)
        return path

    def _transaction_root(self) -> Path:
        return (self.paths.site_imports_dir(self.site_name) / "mesh_bundle").resolve()

    def _acquire_import_lock(self, job_id: str) -> Path:
        root = self._transaction_root()
        root.mkdir(parents=True, exist_ok=True)
        lock = root / ".import.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            try:
                value = json.loads(lock.read_text(encoding="utf-8"))
                owner_pid = int(value.get("pid") or 0)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                owner_pid = 0
            if owner_pid > 0 and _process_is_alive(owner_pid):
                raise MeshBundleImportError("IMPORT_BUSY", "已有 MESH ZIP 导入任务正在提交") from exc
            lock.unlink(missing_ok=True)
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as retry_exc:
                raise MeshBundleImportError("IMPORT_BUSY", "已有 MESH ZIP 导入任务正在提交") from retry_exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"job_id": str(job_id), "pid": os.getpid()}, handle)
        return lock

    @staticmethod
    def _release_import_lock(lock: Path) -> None:
        lock.unlink(missing_ok=True)


def _safe_upload_name(value: str) -> str:
    normalized = str(value or "").replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    if not name or len(name) > 255 or not name.casefold().endswith(".zip"):
        raise MeshBundleImportError("FILE_TYPE_INVALID", "MESH Bundle 必须是 ZIP 文件")
    return name


def _copy_upload(source: BinaryIO, target: Path) -> None:
    total = 0
    with target.open("xb") as handle:
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > _MAX_ARCHIVE_SIZE:
                raise MeshBundleImportError("ARCHIVE_TOO_LARGE", "MESH ZIP 文件不得超过 50 MiB")
            handle.write(chunk)
    if total <= 0:
        raise MeshBundleImportError("FILE_EMPTY", "MESH ZIP 不能为空")


def _member_id(file_order: int, internal_member_name: str) -> str:
    digest = hashlib.sha256(
        f"{file_order}\0{internal_member_name}".encode("utf-8")
    ).hexdigest()
    return f"member-{file_order:06d}-{digest[:24]}"


def _manifest_original_names(
    manifest: MeshBundleManifest,
) -> dict[str, str]:
    return {
        member.internal_member_name: member.original_name
        for member in manifest.members
    }


def _safe_member_name(value: str) -> str:
    normalized = str(value or "").replace("\\", "/")
    if "\x00" in normalized or not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise MeshBundleImportError("MEMBER_PATH_INVALID", f"ZIP 成员路径无效：{value}")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        raise MeshBundleImportError("MEMBER_PATH_TRAVERSAL", f"ZIP 成员路径越界：{value}")
    return "/".join(parts)


def _is_unsafe_file_type(entry: zipfile.ZipInfo) -> bool:
    mode = (entry.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    return stat.S_ISLNK(mode) or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}


def _is_symlink(entry: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((entry.external_attr >> 16) & 0xFFFF)


def _validate_ratio(expanded: int, compressed: int, name: str) -> None:
    if expanded <= 0:
        return
    if compressed <= 0 or expanded / compressed > _MAX_COMPRESSION_RATIO:
        raise MeshBundleImportError("COMPRESSION_RATIO_EXCEEDED", f"ZIP/GZIP 压缩比异常：{name}")


def _inspect_zip_member(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    safe_name: str,
) -> MeshLogContentMetadata:
    try:
        with archive.open(entry) as raw_stream:
            raw_sha256 = _sha256_stream(raw_stream)
        with archive.open(entry) as raw_stream:
            if safe_name.casefold().endswith(".gz"):
                with gzip.GzipFile(fileobj=raw_stream, mode="rb") as content_stream:
                    metadata = inspect_mesh_log_stream(
                        content_stream,
                        raw_sha256=raw_sha256,
                        size_bytes=entry.file_size,
                        max_expanded_size=_MAX_FILE_SIZE,
                    )
            else:
                metadata = inspect_mesh_log_stream(
                    raw_stream,
                    raw_sha256=raw_sha256,
                    size_bytes=entry.file_size,
                    max_expanded_size=_MAX_FILE_SIZE,
                )
    except MeshLogSizeLimitError as exc:
        code = "GZIP_EXPANDED_TOO_LARGE" if safe_name.casefold().endswith(".gz") else "MEMBER_TOO_LARGE"
        message = (
            f"GZIP 日志解压后超过 {MESH_SINGLE_FILE_MAX_LABEL}：{safe_name}"
            if safe_name.casefold().endswith(".gz")
            else f"单个 MESH 日志超过 {MESH_SINGLE_FILE_MAX_LABEL}：{safe_name}"
        )
        raise MeshBundleImportError(code, message) from exc
    except (gzip.BadGzipFile, EOFError, OSError, ValueError) as exc:
        code = "GZIP_INVALID" if safe_name.casefold().endswith(".gz") else "MEMBER_SIZE_MISMATCH"
        message = (
            f"GZIP 日志损坏或无法读取：{safe_name}"
            if safe_name.casefold().endswith(".gz")
            else f"ZIP 成员大小校验失败：{safe_name}"
        )
        raise MeshBundleImportError(code, message) from exc
    if metadata.size_bytes != entry.file_size:
        raise MeshBundleImportError("MEMBER_SIZE_MISMATCH", f"ZIP 成员大小校验失败：{safe_name}")
    _validate_ratio(metadata.expanded_size_bytes, entry.file_size, safe_name)
    return metadata


def _parse_manifest_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _infer_mapping(name: str) -> tuple[str | None, str | None, tuple[str, ...]]:
    match = _MESH_MEMBER_RE.fullmatch(name)
    if not match:
        return None, None, ()
    raw_train = match.group("train")
    canonical = raw_train.zfill(2)
    aliases = tuple(dict.fromkeys((raw_train, canonical)))
    return canonical, match.group("role").upper(), aliases


def _profile_value(profile: object, key: str) -> object:
    if isinstance(profile, Mapping):
        return profile.get(key)
    return getattr(profile, key, None)


def _profile_identity(name: str) -> tuple[str, str] | None:
    compact = re.sub(r"[^0-9A-Za-z]", "", name).casefold()
    match = re.search(r"(?P<train>\d{1,2})mr(?P<role>ct|cw|tc)$", compact)
    if not match:
        return None
    role = match.group("role").upper()
    return match.group("train").zfill(2), "CW" if role == "TC" else role


def _copy_limited(source: BinaryIO, target: Path, maximum: int) -> int:
    total = 0
    with source, target.open("xb") as handle:
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise MeshBundleImportError("MEMBER_TOO_LARGE", "MESH 日志解压后超过安全上限")
            handle.write(chunk)
    return total


def _copy_tree_snapshot(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    sqlite_files: list[tuple[Path, Path]] = []
    for path in source.rglob("*"):
        if path.is_symlink():
            raise MeshBundleImportError("PROFILE_STORAGE_INVALID", "MESH Profile 目录包含符号链接")
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.name.endswith(("-wal", "-shm")):
            continue
        elif path.suffix.casefold() == ".sqlite":
            sqlite_files.append((path, destination))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    for source_db, target_db in sqlite_files:
        _sqlite_backup(source_db, target_db)


def _publish_profile_snapshot(staging: Path, state: _ProfilePublishState) -> None:
    production = state.production_root
    if not staging.is_dir() or not production.is_dir():
        raise MeshBundleImportError("PROFILE_STORAGE_NOT_FOUND", "MESH Profile 数据目录不存在")
    entries = list(staging.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise MeshBundleImportError("PROFILE_STORAGE_INVALID", "MESH Profile 目录包含符号链接")
    files = [path for path in entries if path.is_file() and not path.name.endswith(("-wal", "-shm"))]
    files.sort(
        key=lambda path: (
            path.relative_to(staging).as_posix().casefold() == "mesh.sqlite",
            path.relative_to(staging).as_posix().casefold(),
        )
    )
    state.rollback_root.mkdir(parents=True, exist_ok=False)
    for source in files:
        relative = source.relative_to(staging)
        target = production / relative
        backup = state.rollback_root / relative
        _require_child(target.resolve(), production)
        if target.is_symlink():
            raise MeshBundleImportError("PROFILE_STORAGE_INVALID", "MESH Profile 目录包含符号链接")
        _create_publish_parent(target.parent, production, state.created_directories)
        is_database = source.suffix.casefold() == ".sqlite"
        if target.exists():
            if not target.is_file():
                raise MeshBundleImportError("PROFILE_STORAGE_INVALID", "MESH Profile 文件路径发生冲突")
            if not is_database and _sha256_file(source) == _sha256_file(target):
                continue
            backup.parent.mkdir(parents=True, exist_ok=True)
            if is_database:
                _sqlite_backup(target, backup)
            else:
                shutil.copy2(target, backup)
            state.overwritten_files.append((target, backup))
        else:
            state.created_files.append(target)
        if is_database:
            _sqlite_backup(source, target)
        else:
            _copy_file_atomic(source, target)


def _rollback_profile_snapshot(state: _ProfilePublishState) -> None:
    for target, backup in reversed(state.overwritten_files):
        if backup.suffix.casefold() == ".sqlite":
            _sqlite_backup(backup, target)
        else:
            _copy_file_atomic(backup, target)
    for target in reversed(state.created_files):
        target.unlink(missing_ok=True)
        if target.suffix.casefold() == ".sqlite":
            for suffix in ("-wal", "-shm"):
                target.with_name(target.name + suffix).unlink(missing_ok=True)
    for directory in reversed(state.created_directories):
        try:
            directory.rmdir()
        except OSError:
            pass


def _create_publish_parent(parent: Path, root: Path, created: list[Path]) -> None:
    missing: list[Path] = []
    current = parent
    while current != root and not current.exists():
        _require_child(current.resolve(), root)
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=False)
        created.append(directory)


def _copy_file_atomic(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _sqlite_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source, timeout=30)) as source_connection, closing(
        sqlite3.connect(target, timeout=30)
    ) as target_connection:
        source_connection.execute("PRAGMA busy_timeout = 30000")
        target_connection.execute("PRAGMA busy_timeout = 30000")
        source_connection.backup(target_connection)
        target_connection.commit()


def _read_catalog_summaries(
    path: Path,
    profiles: Mapping[str, MeshMrProfile],
) -> dict[str, tuple[object, ...]]:
    profile_ids = tuple(profiles)
    if not profile_ids:
        return {}
    placeholders = ", ".join("?" for _ in profile_ids)
    fields = ", ".join(_CATALOG_SUMMARY_FIELDS)
    with closing(sqlite3.connect(path, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"SELECT mr_id, {fields} FROM mr_profiles WHERE mr_id IN ({placeholders})",
            profile_ids,
        ).fetchall()
    summaries = {
        str(row["mr_id"]): tuple(row[field] for field in _CATALOG_SUMMARY_FIELDS)
        for row in rows
    }
    if summaries.keys() != profiles.keys():
        raise MeshBundleImportError(
            "CATALOG_PROFILE_MISSING",
            "MESH Profile 目录库与导入映射不一致",
        )
    return summaries


def _write_catalog_summaries(
    path: Path,
    summaries: Mapping[str, tuple[object, ...]],
) -> None:
    if not summaries:
        return
    assignments = ", ".join(f"{field} = ?" for field in _CATALOG_SUMMARY_FIELDS)
    with closing(sqlite3.connect(path, timeout=30)) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            connection.execute("BEGIN IMMEDIATE")
            for profile_id, values in summaries.items():
                cursor = connection.execute(
                    f"UPDATE mr_profiles SET {assignments} WHERE mr_id = ?",
                    (*values, profile_id),
                )
                if cursor.rowcount != 1:
                    raise MeshBundleImportError(
                        "CATALOG_PROFILE_MISSING",
                        "MESH Profile 目录库与导入映射不一致",
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _checkpoint_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _assert_no_stale_path(database: Path, stale_root: str) -> None:
    with closing(sqlite3.connect(database)) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table_name,) in tables:
            table_sql = _quote_identifier(str(table_name))
            columns = connection.execute(f"PRAGMA table_info({table_sql})").fetchall()
            for column in columns:
                column_name = str(column[1])
                column_type = str(column[2] or "").upper()
                if "TEXT" not in column_type:
                    continue
                column_sql = _quote_identifier(column_name)
                found = connection.execute(
                    f"SELECT 1 FROM {table_sql} WHERE instr(COALESCE({column_sql}, ''), ?) > 0 LIMIT 1",
                    (stale_root,),
                ).fetchone()
                if found:
                    raise MeshBundleImportError("STAGING_PATH_REMAINS", "parsed 数据库仍包含 staging 绝对路径")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _require_child(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise MeshBundleImportError("PATH_OUTSIDE_ROOT", "MESH ZIP 路径不在受控目录") from exc
    if path == root:
        raise MeshBundleImportError("PATH_OUTSIDE_ROOT", "MESH ZIP 文件路径不能等于受控目录")


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _raise_if_cancelled(callback: Callable[[], bool] | None) -> None:
    if callback is not None and callback():
        from netconsole.services.job_center.job_context import BackgroundTaskCancelled

        raise BackgroundTaskCancelled("后台任务已取消")


def _process_is_alive(process_id: int) -> bool:
    try:
        os.kill(int(process_id), 0)
    except OSError:
        return False
    return True


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


__all__ = [
    "MeshBundleImportError",
    "MeshBundleImportService",
    "MeshBundleManifest",
    "MeshBundleMember",
    "MeshBundleProfileMatch",
]
