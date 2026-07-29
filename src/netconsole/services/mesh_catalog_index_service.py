from __future__ import annotations

import hashlib
import gzip
import logging
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.parsers.mesh_log_parser import inspect_mesh_log_path
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_mr_repository import MeshMrRepository, MeshSchemaRebuildRequired

LOGGER = logging.getLogger(__name__)


class MeshCatalogIndexService:
    """以低优先级维护 MESH 来源目录；HTTP 查询只消费目录库。"""

    _running: set[tuple[str, str]] = set()
    _lock = threading.Lock()

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def schedule(self, site_id: str, *, force: bool = False) -> bool:
        key = (str(self.paths.data_root), site_id)
        with self._lock:
            if key in self._running:
                return False
            if not force and self._is_ready(site_id):
                return False
            self._running.add(key)
        thread = threading.Thread(
            target=self._run_guarded,
            args=(site_id, key),
            name=f"mesh-catalog-index-{site_id}"[:80],
            daemon=True,
        )
        thread.start()
        return True

    def rebuild_now(self, site_id: str) -> None:
        self._rebuild(site_id)

    def _run_guarded(self, site_id: str, key: tuple[str, str]) -> None:
        try:
            self._rebuild(site_id)
        except Exception as exc:
            LOGGER.exception("MESH 目录索引后台回填失败 site=%s", site_id)
            try:
                repository = MeshCatalogRepository(self.paths.mesh_catalog_path(site_id))
                repository.mark_index_failed(type(exc).__name__)
            except Exception:
                LOGGER.exception("MESH 目录索引失败状态写入失败 site=%s", site_id)
        finally:
            with self._lock:
                self._running.discard(key)

    def _is_ready(self, site_id: str) -> bool:
        catalog = self.paths.mesh_catalog_path(site_id)
        if not catalog.is_file():
            return False
        try:
            uri = f"file:{catalog.as_posix()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as conn:
                row = conn.execute(
                    """
                    SELECT status FROM mesh_catalog_index_state
                    WHERE singleton = 1
                    """
                ).fetchone()
            return bool(row and str(row[0]) == "ready")
        except sqlite3.Error:
            return False

    def _rebuild(self, site_id: str) -> None:
        # 延迟导入，避免只读查询服务与后台索引服务形成模块循环。
        from netconsole.services.rail_transit.mesh_analysis_query_service import (
            MeshAnalysisQueryService,
        )

        repository = MeshCatalogRepository(self.paths.mesh_catalog_path(site_id))
        profiles = repository.list_profiles()
        revisions = repository.session_index_revisions()
        query = MeshAnalysisQueryService(self.paths, schedule_catalog_index=False)
        discovered: list[tuple[dict[str, Any], dict[str, Any], Path, str]] = []
        repository.update_index_state(
            status="discovering",
            discovered=0,
            indexed=len(revisions),
            detail_indexed=sum(int(value[1]) for value in revisions.values()),
        )
        for profile_model in profiles:
            profile = {
                "mr_id": profile_model.mr_id,
                "display_name": profile_model.display_name,
                "safe_folder_name": profile_model.safe_folder_name,
                "linked_device_id": profile_model.linked_device_id,
                "linked_device_uuid": profile_model.linked_device_uuid,
            }
            index_db = self.paths.mesh_mr_db_path(site_id, profile_model.safe_folder_name)
            if not index_db.is_file():
                continue
            try:
                with closing(query._connect_readonly(index_db)) as conn:
                    if not query._table_exists(conn, "source_files"):
                        continue
                    columns = query._table_columns(conn, "source_files")
                    where = (
                        "WHERE COALESCE(parsed_deleted_at, '') = ''"
                        if "parsed_deleted_at" in columns
                        else ""
                    )
                    rows = [
                        dict(row)
                        for row in conn.execute(
                            f"SELECT * FROM source_files {where} ORDER BY id"
                        )
                    ]
            except sqlite3.Error:
                LOGGER.warning("跳过不可读取的 MESH 来源索引：%s", index_db, exc_info=True)
                continue
            for source in rows:
                revision = self._source_revision(index_db, source)
                discovered.append((profile, source, index_db, revision))

        active_ids = {
            f"{profile['mr_id']}:{int(source['id'])}"
            for profile, source, _index_db, _revision in discovered
        }
        repository.delete_stale_session_index(active_ids)

        # 第一阶段只消费各 Profile 的 source_files，不打开任何来源明细库。
        basic_rows: list[dict[str, object]] = []
        fingerprint_rows: list[dict[str, object]] = []
        for profile, source, _index_db, revision in discovered:
            session_id = f"{profile['mr_id']}:{int(source['id'])}"
            previous = revisions.get(session_id)
            if previous and previous[0] == revision:
                fingerprint_rows.append(self._fingerprint_row(profile, source))
                continue
            basic_rows.append(self._basic_index_row(site_id, profile, source, revision))
            fingerprint_rows.append(self._fingerprint_row(profile, source))
        repository.upsert_session_indexes(basic_rows)
        repository.upsert_source_fingerprints(fingerprint_rows)

        repository.update_index_state(
            status="enriching",
            discovered=len(discovered),
            indexed=len(discovered),
            detail_indexed=sum(
                int(revisions.get(session_id, ("", False))[1])
                for session_id in active_ids
            ),
        )

        # 第二阶段逐来源补齐统计；每个明细库最多打开一次，且不阻塞 HTTP。
        detail_indexed = 0
        detail_rows: list[dict[str, object]] = []
        for profile, source, index_db, revision in discovered:
            session_id = f"{profile['mr_id']}:{int(source['id'])}"
            previous = revisions.get(session_id)
            if previous and previous == (revision, True):
                detail_indexed += 1
                continue
            context = query._context_from_rows(site_id, profile, source, index_db)
            stats = query._stats(context)
            dto = query._session_dto(context, stats)
            detail_rows.append(
                repository.session_index_row(
                    dto=dto,
                    mr_id=str(profile["mr_id"]),
                    source_file_id=int(source["id"]),
                    stats=stats,
                    source_revision=revision,
                    detail_indexed=True,
                )
            )
            self._backfill_fingerprint(
                repository,
                profile,
                source,
                index_db,
                context.raw_path,
            )
            detail_indexed += 1
            if detail_indexed % 25 == 0:
                repository.upsert_session_indexes(detail_rows)
                detail_rows.clear()
                repository.update_index_state(
                    status="enriching",
                    discovered=len(discovered),
                    indexed=len(discovered),
                    detail_indexed=detail_indexed,
                )
        repository.upsert_session_indexes(detail_rows)
        repository.update_index_state(
            status="ready",
            discovered=len(discovered),
            indexed=len(discovered),
            detail_indexed=detail_indexed,
        )

    @staticmethod
    def _source_revision(index_db: Path, source: dict[str, Any]) -> str:
        del index_db
        recorded = str(source.get("parsed_db_path") or "")
        detail = Path(recorded.strip().strip("'\"")) if recorded else None
        try:
            detail_revision = f"{detail.stat().st_mtime_ns}:{detail.stat().st_size}" if detail else ""
        except OSError:
            detail_revision = "missing"
        payload = "\0".join(
            str(source.get(field) or "")
            for field in (
                "id", "parse_status", "issue_count", "records_parsed", "imported_at",
                "first_sample_time", "last_sample_time", "parsed_deleted_at",
                "parsed_db_path", "content_sha256", "raw_sha256", "sha256",
            )
        )
        payload += f"\0{detail_revision}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _mr_identity(value: str) -> tuple[str, str]:
        from netconsole.services.rail_transit.mesh_analysis_query_service import (
            MeshAnalysisQueryService,
        )

        return MeshAnalysisQueryService._mr_identity(value)

    def _basic_index_row(
        self,
        site_id: str,
        profile: dict[str, Any],
        source: dict[str, Any],
        revision: str,
    ) -> dict[str, object]:
        mr_name = str(profile["display_name"])
        train_name, role = self._mr_identity(mr_name)
        issue_count = int(source.get("issue_count") or 0)
        now = datetime.now().isoformat(sep=" ", timespec="milliseconds")
        return {
            "session_id": f"{profile['mr_id']}:{int(source['id'])}",
            "mr_id": str(profile["mr_id"]),
            "source_file_id": int(source["id"]),
            "train_name": train_name,
            "mr_name": mr_name,
            "mr_role": role,
            "source_type": "raw_mesh_log",
            "original_filename": str(
                source.get("original_filename")
                or source.get("archived_filename")
                or source.get("stored_filename")
                or ""
            ),
            "analysis_time": str(source.get("imported_at") or "") or None,
            "first_sample_time": str(source.get("first_sample_time") or "") or None,
            "last_sample_time": str(source.get("last_sample_time") or "") or None,
            "link_record_count": None,
            "active_link_count": None,
            "standby_link_count": None,
            "event_count": None,
            "link_up_event_count": None,
            "link_down_event_count": None,
            "switch_event_count": None,
            "short_link_count": None,
            "pingpong_count": None,
            "rssi_anomaly_count": None,
            "channel_busy_anomaly_count": None,
            "unmatched_ap_count": None,
            "data_integrity": "partial",
            "analysis_status": str(source.get("parse_status") or "unknown"),
            "parsed_status": "indexing",
            "parsed_message": "目录索引已就绪，明细统计正在后台补齐。",
            "schema_version": str(source.get("db_schema_version") or "") or None,
            "available_capabilities_json": "[]",
            "missing_capabilities_json": "[]",
            "warning_count": issue_count,
            "report_count": 0,
            "source_revision": revision,
            "detail_indexed": 0,
            "updated_at": now,
        }

    @staticmethod
    def _fingerprint_row(
        profile: dict[str, Any],
        source: dict[str, Any],
    ) -> dict[str, object]:
        return {
            "content_sha256": str(source.get("content_sha256") or ""),
            "raw_sha256": str(source.get("raw_sha256") or source.get("sha256") or ""),
            "mr_id": str(profile["mr_id"]),
            "source_file_id": int(source["id"]),
            "stored_filename": str(
                source.get("stored_filename")
                or source.get("archived_filename")
                or source.get("original_filename")
                or ""
            ),
        }

    @staticmethod
    def _backfill_fingerprint(
        catalog: MeshCatalogRepository,
        profile: dict[str, Any],
        source: dict[str, Any],
        index_db: Path,
        raw_path: Path | None,
    ) -> None:
        if str(source.get("content_sha256") or "").strip() or raw_path is None:
            return
        try:
            metadata = inspect_mesh_log_path(raw_path, max_expanded_size=100 * 1024 * 1024)
            MeshMrRepository(index_db).update_source_fingerprints(
                int(source["id"]),
                raw_sha256=metadata.raw_sha256,
                content_sha256=metadata.content_sha256,
                first_log_timestamp=metadata.first_log_timestamp,
                last_log_timestamp=metadata.last_log_timestamp,
            )
            catalog.upsert_source_fingerprint(
                content_sha256=metadata.content_sha256,
                raw_sha256=metadata.raw_sha256,
                mr_id=str(profile["mr_id"]),
                source_file_id=int(source["id"]),
                stored_filename=str(
                    source.get("stored_filename")
                    or source.get("archived_filename")
                    or source.get("original_filename")
                    or ""
                ),
            )
        except (
            OSError,
            ValueError,
            gzip.BadGzipFile,
            sqlite3.Error,
            MeshSchemaRebuildRequired,
        ):
            LOGGER.warning(
                "MESH 历史来源指纹后台补齐失败 session=%s:%s",
                profile.get("mr_id"),
                source.get("id"),
                exc_info=True,
            )
