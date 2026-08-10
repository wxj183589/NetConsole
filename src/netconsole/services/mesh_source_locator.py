from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MeshSourceLocation:
    raw_path: Path | None
    raw_directory: Path | None = None
    raw_relative_path: str = ""
    rebuild_capability: str = "raw_missing"
    recoverable: bool = False
    recovery_source: str = ""
    missing_reason: str = ""
    archive_sha256: str = ""
    bundle_member_id: str = ""
    bundle_member_sha256: str = ""


class MeshSourceLocator:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def locate(
        self,
        site_id: str,
        profile: MeshMrProfile | Mapping[str, object],
        source: Mapping[str, object],
    ) -> MeshSourceLocation:
        safe_name = str(self._value(profile, "safe_folder_name") or "")
        profile_root = self.paths.mesh_mr_root(site_id, safe_name).resolve()
        raw_root = self.paths.mesh_mr_raw_dir(site_id, safe_name).resolve()
        self._require_inside(raw_root, profile_root)
        digest = str(source.get("sha256") or "").strip().casefold()
        digest = digest if _SHA256_RE.fullmatch(digest) else ""
        candidates: list[tuple[Path, str]] = []
        relative = str(source.get("raw_relative_path") or "").replace("\\", "/").strip("/")
        if relative:
            candidates.append(((profile_root / relative).resolve(), "relative_path"))
        archived_name = Path(str(source.get("archived_filename") or "")).name
        if archived_name:
            candidates.append(((raw_root / archived_name).resolve(), "archived_filename"))
            if raw_root.is_dir():
                candidates.extend((path.resolve(), "archived_filename") for path in raw_root.rglob(archived_name))
        legacy = str(source.get("archived_path") or "").strip().strip("'\"")
        if legacy:
            candidates.append((Path(legacy).resolve(), "legacy_path"))
        seen: set[Path] = set()
        for candidate, origin in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.is_file() and not candidate.is_symlink() and self._inside(candidate, raw_root):
                return MeshSourceLocation(
                    raw_path=candidate,
                    raw_relative_path=candidate.relative_to(profile_root).as_posix(),
                    rebuild_capability="ready",
                    recovery_source=origin,
                    archive_sha256=str(source.get("archive_sha256") or ""),
                    bundle_member_id=str(source.get("bundle_member_id") or ""),
                    bundle_member_sha256=str(source.get("bundle_member_sha256") or ""),
                )
        if digest and raw_root.is_dir():
            for path in raw_root.rglob("*"):
                if not path.is_file() or path.is_symlink() or not self._inside(path.resolve(), raw_root):
                    continue
                if self._sha256(path) == digest:
                    resolved = path.resolve()
                    return MeshSourceLocation(
                        raw_path=resolved,
                        raw_relative_path=resolved.relative_to(profile_root).as_posix(),
                        rebuild_capability="ready",
                        recovery_source="sha256",
                        archive_sha256=str(source.get("archive_sha256") or ""),
                        bundle_member_id=str(source.get("bundle_member_id") or ""),
                        bundle_member_sha256=str(source.get("bundle_member_sha256") or ""),
                    )
        for candidate, _origin in candidates:
            directory = candidate.parent.resolve()
            if (
                directory.is_dir()
                and not directory.is_symlink()
                and self._inside(directory, raw_root)
            ):
                return MeshSourceLocation(
                    raw_path=None,
                    raw_directory=directory,
                    missing_reason="原始日志文件已不存在，可打开其受管目录。",
                )
        if raw_root.is_dir() and not raw_root.is_symlink():
            return MeshSourceLocation(
                raw_path=None,
                raw_directory=raw_root,
                missing_reason="原始日志文件已不存在，可打开其受管目录。",
            )
        bundle = self.find_bundle(site_id, str(self._value(profile, "mr_id") or ""), source)
        if bundle is not None:
            return MeshSourceLocation(
                raw_path=None,
                rebuild_capability="recoverable_from_bundle",
                recoverable=True,
                recovery_source="bundle_archive",
                missing_reason="原始日志可从受保护 ZIP 归档恢复。",
                **bundle,
            )
        return MeshSourceLocation(
            raw_path=None,
            missing_reason="未找到原始日志或归档 ZIP，请重新导入该日志。",
        )

    def find_bundle(self, site_id: str, profile_id: str, source: Mapping[str, object]) -> dict[str, str] | None:
        source_sha = str(source.get("sha256") or "").strip().casefold()
        archive_sha = str(source.get("archive_sha256") or "").strip().casefold()
        member_id = str(source.get("bundle_member_id") or "").strip()
        member_sha = str(source.get("bundle_member_sha256") or "").strip().casefold()
        bundle_root = (self.paths.site_mesh_root(site_id) / "bundles").resolve()
        if not bundle_root.is_dir():
            return None
        directories: list[Path] = []
        if _SHA256_RE.fullmatch(archive_sha):
            directories.append((bundle_root / archive_sha).resolve())
        directories.extend(
            path.resolve()
            for path in bundle_root.iterdir()
            if path.is_dir() and _SHA256_RE.fullmatch(path.name.casefold()) and path.resolve() not in directories
        )
        for directory in directories:
            if not self._inside(directory, bundle_root):
                continue
            manifest_path = directory / "manifest.json"
            archive = directory / "source.zip"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("status") != "success" or not archive.is_file():
                continue
            mappings = manifest.get("file_mappings") or ()
            for mapping in mappings:
                if not isinstance(mapping, Mapping):
                    continue
                candidate_id = str(mapping.get("member_id") or "")
                candidate_sha = str(mapping.get("sha256") or "").casefold()
                candidate_profile = str(mapping.get("profile_id") or "")
                if member_id and candidate_id != member_id:
                    continue
                if member_sha and candidate_sha != member_sha:
                    continue
                if source_sha and candidate_sha != source_sha:
                    continue
                if profile_id and candidate_profile and candidate_profile != profile_id:
                    continue
                return {
                    "archive_sha256": str(manifest.get("archive_sha256") or directory.name),
                    "bundle_member_id": candidate_id,
                    "bundle_member_sha256": candidate_sha,
                }
        return None

    @staticmethod
    def _value(value: MeshMrProfile | Mapping[str, object], key: str) -> object:
        return value.get(key) if isinstance(value, Mapping) else getattr(value, key, None)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _inside(candidate: Path, root: Path) -> bool:
        return candidate == root or candidate.is_relative_to(root)

    @classmethod
    def _require_inside(cls, candidate: Path, root: Path) -> None:
        if not cls._inside(candidate, root):
            raise ValueError("MESH 来源路径越过允许目录")


__all__ = ["MeshSourceLocation", "MeshSourceLocator"]
