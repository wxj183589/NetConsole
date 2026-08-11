from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_source_index_repository import MeshSourceIndexRepository
from netconsole.services.mesh_source_locator import MeshSourceLocator
from netconsole.services.mesh_storage_service import MeshStorageService


@dataclass(frozen=True)
class MeshImportPreflightResult:
    session_id: str
    mr_id: str
    source_file_id: int
    health_status: str
    reason_codes: tuple[str, ...]
    profile_directory_exists: bool
    raw_directory_exists: bool
    parsed_directory_exists: bool
    source_index_exists: bool
    source_index_row_exists: bool
    raw_file_exists: bool
    parsed_file_exists: bool
    parsed_file_readable: bool
    catalog_fingerprint_exists: bool
    catalog_session_exists: bool
    recoverable_from_selected_file: bool

    @property
    def broken(self) -> bool:
        return self.health_status == "BROKEN_SOURCE"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MeshImportPreflightService:
    """Reconcile MESH catalog/index/files before duplicate decisions.

    The service never removes history.  Broken state is persisted in the
    catalog lifecycle ledger and recovery keeps the existing public session id.
    """

    def __init__(self, site_id: str, paths: PathResolver) -> None:
        self.site_id = str(site_id)
        self.paths = paths
        self.catalog = MeshCatalogRepository(paths.mesh_catalog_path(self.site_id))

    def inspect_import(
        self,
        profile: MeshMrProfile,
        *,
        content_sha256: str,
        raw_sha256: str = "",
    ) -> list[MeshImportPreflightResult]:
        matches = self.catalog.find_source_fingerprints(
            content_sha256=content_sha256,
            raw_sha256=raw_sha256,
        )
        profile_matches = [
            row for row in matches if str(row.get("mr_id") or "") == profile.mr_id
        ]
        index_path = self.paths.mesh_mr_db_path(
            self.site_id,
            profile.safe_folder_name,
        )
        if not index_path.is_file():
            return [
                self._missing_index_result(profile, row)
                for row in profile_matches
            ]

        repository = MeshSourceIndexRepository(index_path)
        indexed = repository.list_source_files()
        candidates = [
            row
            for row in indexed
            if _hash_matches(
                row,
                content_sha256=content_sha256,
                raw_sha256=raw_sha256,
            )
        ]
        results = [self.inspect_source(profile, source) for source in candidates]
        indexed_ids = {int(row.get("id") or 0) for row in candidates}
        results.extend(
            self._missing_index_row_result(profile, row)
            for row in profile_matches
            if int(row.get("source_file_id") or 0) not in indexed_ids
        )
        return results

    def inspect_source(
        self,
        profile: MeshMrProfile,
        source: dict[str, object],
    ) -> MeshImportPreflightResult:
        source_id = int(source.get("id") or 0)
        session_id = f"{profile.mr_id}:{source_id}"
        profile_root = self.paths.mesh_mr_root(
            self.site_id,
            profile.safe_folder_name,
        )
        raw_root = self.paths.mesh_mr_raw_dir(
            self.site_id,
            profile.safe_folder_name,
        )
        parsed_root = self.paths.mesh_mr_parsed_dir(
            self.site_id,
            profile.safe_folder_name,
        )
        index_path = self.paths.mesh_mr_db_path(
            self.site_id,
            profile.safe_folder_name,
        )
        raw_path = MeshSourceLocator(self.paths).locate(
            self.site_id,
            profile,
            source,
        ).raw_path
        parsed_value = str(source.get("parsed_db_path") or "").strip().strip("'\"")
        parsed_path = Path(parsed_value) if parsed_value else None
        parsed_exists = bool(parsed_path and parsed_path.is_file())
        parsed_readable = bool(parsed_path and _sqlite_readable(parsed_path))
        fingerprint_exists = self._catalog_fingerprint_exists(profile, source)
        catalog_session_exists = self.catalog.get_session_index(session_id) is not None

        reasons: list[str] = []
        if not profile_root.is_dir():
            reasons.append("PROFILE_DIRECTORY_MISSING")
        if not raw_root.is_dir():
            reasons.append("RAW_DIRECTORY_MISSING")
        if not parsed_root.is_dir():
            reasons.append("PARSED_DIRECTORY_MISSING")
        if not index_path.is_file():
            reasons.append("SOURCE_INDEX_MISSING")
        if raw_path is None:
            reasons.append("RAW_FILE_MISSING")
        if not parsed_exists:
            reasons.append("PARSED_FILE_MISSING")
        elif not parsed_readable:
            reasons.append("PARSED_FILE_UNREADABLE")

        physical_reasons = tuple(dict.fromkeys(reasons))
        health = "BROKEN_SOURCE" if physical_reasons else "HEALTHY"
        details = {
            "reason_codes": list(physical_reasons),
            "profile_directory_exists": profile_root.is_dir(),
            "raw_directory_exists": raw_root.is_dir(),
            "parsed_directory_exists": parsed_root.is_dir(),
            "source_index_exists": index_path.is_file(),
            "raw_file_exists": raw_path is not None,
            "parsed_file_exists": parsed_exists,
            "parsed_file_readable": parsed_readable,
            "catalog_fingerprint_exists": fingerprint_exists,
            "catalog_session_exists": catalog_session_exists,
        }
        self.catalog.record_source_health(
            session_id=session_id,
            mr_id=profile.mr_id,
            source_file_id=source_id,
            health_status=health,
            reason_code=physical_reasons[0] if physical_reasons else "",
            details=details,
        )
        if health == "BROKEN_SOURCE" and index_path.is_file():
            MeshSourceIndexRepository(index_path).mark_source_broken(
                source_id,
                raw_exists=raw_path is not None,
                reason_code=physical_reasons[0],
            )

        if not fingerprint_exists:
            self._publish_fingerprint(profile, source)
        if not catalog_session_exists:
            self.catalog.mark_index_pending()

        return MeshImportPreflightResult(
            session_id=session_id,
            mr_id=profile.mr_id,
            source_file_id=source_id,
            health_status=health,
            reason_codes=physical_reasons,
            profile_directory_exists=profile_root.is_dir(),
            raw_directory_exists=raw_root.is_dir(),
            parsed_directory_exists=parsed_root.is_dir(),
            source_index_exists=index_path.is_file(),
            source_index_row_exists=True,
            raw_file_exists=raw_path is not None,
            parsed_file_exists=parsed_exists,
            parsed_file_readable=parsed_readable,
            catalog_fingerprint_exists=fingerprint_exists,
            catalog_session_exists=catalog_session_exists,
            recoverable_from_selected_file=health == "BROKEN_SOURCE",
        )

    def prepare_broken_duplicate(
        self,
        profile: MeshMrProfile,
        source: dict[str, object],
        *,
        selected_file: Path,
        metadata: Any,
    ) -> dict[str, object]:
        assessment = self.inspect_source(profile, source)
        if not assessment.broken:
            return {"recovered": False, "assessment": assessment.to_dict()}

        storage = MeshStorageService(self.site_id, self.paths)
        profile_root = storage.ensure_mr_dirs(profile).resolve()
        raw_location = MeshSourceLocator(self.paths).locate(
            self.site_id,
            profile,
            source,
        )
        raw_path = raw_location.raw_path
        if raw_path is None:
            archive = storage.archive_raw_file_with_metadata(
                profile,
                selected_file,
                getattr(metadata, "first_log_timestamp", None),
            )
            raw_path = archive.path.resolve()
            MeshSourceIndexRepository(
                self.paths.mesh_mr_db_path(self.site_id, profile.safe_folder_name)
            ).restore_raw_archive(
                assessment.source_file_id,
                raw_path=raw_path,
                raw_relative_path=raw_path.relative_to(profile_root).as_posix(),
                raw_sha256=str(getattr(metadata, "raw_sha256", "") or ""),
                content_sha256=str(
                    getattr(metadata, "content_sha256", "") or ""
                ),
            )

        rebuild_result: dict[str, object] = {}
        if not assessment.parsed_file_exists or not assessment.parsed_file_readable:
            # Local import workers already run outside the request thread.  Keep
            # the existing source/session identity and rebuild only this source.
            from netconsole.services.mesh_source_rebuild_service import (
                MeshSourceRebuildService,
            )

            rebuild_result = MeshSourceRebuildService(self.paths).rebuild_source(
                self.site_id,
                assessment.session_id,
                force_reparse=True,
            )

        refreshed = MeshSourceIndexRepository(
            self.paths.mesh_mr_db_path(self.site_id, profile.safe_folder_name)
        ).get_source_file(assessment.source_file_id)
        if refreshed is None:
            raise RuntimeError("MESH 来源恢复后索引记录不存在")
        self._publish_fingerprint(profile, refreshed)
        self.catalog.mark_session_index_dirty(assessment.session_id)
        self.catalog.record_source_health(
            session_id=assessment.session_id,
            mr_id=profile.mr_id,
            source_file_id=assessment.source_file_id,
            health_status="HEALTHY",
            reason_code="RECOVERED_FROM_REIMPORT",
            details={"recovered_from_selected_file": True},
        )
        storage.refresh_catalog_summary(profile)
        return {
            "recovered": True,
            "session_id": assessment.session_id,
            "source_file_id": assessment.source_file_id,
            "raw_path": str(raw_path),
            "parsed_record_count": int(
                rebuild_result.get("parsed_record_count")
                or refreshed.get("records_parsed")
                or 0
            ),
            "assessment": assessment.to_dict(),
            "rebuild": rebuild_result,
        }

    def _missing_index_result(
        self,
        profile: MeshMrProfile,
        row: dict[str, object],
    ) -> MeshImportPreflightResult:
        return self._record_central_orphan(
            profile,
            row,
            reason_code="SOURCE_INDEX_MISSING",
        )

    def _missing_index_row_result(
        self,
        profile: MeshMrProfile,
        row: dict[str, object],
    ) -> MeshImportPreflightResult:
        return self._record_central_orphan(
            profile,
            row,
            reason_code="SOURCE_INDEX_ROW_MISSING",
        )

    def _record_central_orphan(
        self,
        profile: MeshMrProfile,
        row: dict[str, object],
        *,
        reason_code: str,
    ) -> MeshImportPreflightResult:
        source_id = int(row.get("source_file_id") or 0)
        session_id = f"{profile.mr_id}:{source_id}"
        profile_root = self.paths.mesh_mr_root(
            self.site_id,
            profile.safe_folder_name,
        )
        raw_root = self.paths.mesh_mr_raw_dir(
            self.site_id,
            profile.safe_folder_name,
        )
        parsed_root = self.paths.mesh_mr_parsed_dir(
            self.site_id,
            profile.safe_folder_name,
        )
        index_path = self.paths.mesh_mr_db_path(
            self.site_id,
            profile.safe_folder_name,
        )
        details = {
            "reason_codes": [reason_code],
            "catalog_fingerprint_exists": True,
            "catalog_session_exists": self.catalog.get_session_index(session_id)
            is not None,
        }
        self.catalog.record_source_health(
            session_id=session_id,
            mr_id=profile.mr_id,
            source_file_id=source_id,
            health_status="BROKEN_SOURCE",
            reason_code=reason_code,
            details=details,
        )
        return MeshImportPreflightResult(
            session_id=session_id,
            mr_id=profile.mr_id,
            source_file_id=source_id,
            health_status="BROKEN_SOURCE",
            reason_codes=(reason_code,),
            profile_directory_exists=profile_root.is_dir(),
            raw_directory_exists=raw_root.is_dir(),
            parsed_directory_exists=parsed_root.is_dir(),
            source_index_exists=index_path.is_file(),
            source_index_row_exists=False,
            raw_file_exists=False,
            parsed_file_exists=False,
            parsed_file_readable=False,
            catalog_fingerprint_exists=True,
            catalog_session_exists=bool(details["catalog_session_exists"]),
            recoverable_from_selected_file=True,
        )

    def _catalog_fingerprint_exists(
        self,
        profile: MeshMrProfile,
        source: dict[str, object],
    ) -> bool:
        rows = self.catalog.find_source_fingerprints(
            content_sha256=str(source.get("content_sha256") or ""),
            raw_sha256=str(source.get("raw_sha256") or ""),
        )
        source_id = int(source.get("id") or 0)
        return any(
            str(row.get("mr_id") or "") == profile.mr_id
            and int(row.get("source_file_id") or 0) == source_id
            for row in rows
        )

    def _publish_fingerprint(
        self,
        profile: MeshMrProfile,
        source: dict[str, object],
    ) -> None:
        self.catalog.upsert_source_fingerprint(
            content_sha256=str(source.get("content_sha256") or ""),
            raw_sha256=str(source.get("raw_sha256") or ""),
            mr_id=profile.mr_id,
            source_file_id=int(source.get("id") or 0),
            stored_filename=str(
                source.get("stored_filename")
                or source.get("archived_filename")
                or ""
            ),
        )


def _hash_matches(
    row: dict[str, object],
    *,
    content_sha256: str,
    raw_sha256: str,
) -> bool:
    content = str(content_sha256 or "").strip().casefold()
    raw = str(raw_sha256 or "").strip().casefold()
    return bool(
        (content and str(row.get("content_sha256") or "").casefold() == content)
        or (raw and str(row.get("raw_sha256") or "").casefold() == raw)
    )


def _sqlite_readable(path: Path) -> bool:
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            return True
    except (OSError, sqlite3.Error):
        return False


__all__ = ["MeshImportPreflightResult", "MeshImportPreflightService"]
