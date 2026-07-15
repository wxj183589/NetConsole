from __future__ import annotations

import json
import re
import shutil
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from netconsole.application.web_artifacts import ReservedWebArtifact, WebArtifactError, WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.online_mr import OnlineMrDownsampleMode, OnlineMrMetricType
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.services.background_job import BackgroundJob
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_task_builders import online_mr_report_xlsx_spec
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryError, MeshAnalysisQueryService


class RailTransitWebError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RailTransitWebApplicationService:
    """轨交 Web 用例边界；任务、导出和 Artifact 都复用正式生命周期。"""

    _TASK_NAMES = {
        "mesh_log_import": "MESH 原始日志导入分析",
        "car_network_refresh_all": "车内通信检测刷新",
    }
    _UPLOAD_SUFFIXES = {".log", ".txt"}
    _SAFE_NAME = re.compile(r"[^0-9A-Za-z._-]+")
    _ALLOWED_TASK_TYPES = {
        *_TASK_NAMES,
        "web_export_online_mr_report_xlsx",
        "web_export_mesh_analysis_report",
    }
    _OWNER = "web_rail_transit"
    _ARTIFACT_SOURCES = {"online_mr_report", "mesh_analysis_report"}
    _ACTIONS = {
        "web_export_online_mr_report_xlsx": "online_mr_report",
        "web_export_mesh_analysis_report": "mesh_analysis_report",
    }

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        process_adapter: LocalProcessAdapter,
        export_adapter: WebExportProcessAdapter,
        query_service: OnlineMrQueryService | None = None,
        mesh_query_service: MeshAnalysisQueryService | None = None,
        artifact_store: WebArtifactStore | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter
        self.export_adapter = export_adapter
        self.query_service = query_service or OnlineMrQueryService(paths)
        self.mesh_query_service = mesh_query_service or MeshAnalysisQueryService(paths)
        self.artifact_store = artifact_store or WebArtifactStore(paths)

    def create_mesh_staging(self, site_id: str) -> Path:
        site_id = self._site(site_id)
        root = (self.paths.runtime_cache_dir / "rail_web_uploads" / site_id).resolve()
        root.mkdir(parents=True, exist_ok=True)
        staging = (root / uuid4().hex).resolve()
        if root not in staging.parents:
            raise RailTransitWebError("STAGING_INVALID", "MESH 临时目录无效")
        staging.mkdir(parents=False, exist_ok=False)
        return staging

    def discard_mesh_staging(self, site_id: str, staging_dir: Path) -> None:
        self._cleanup_staging(self._site(site_id), staging_dir)

    def start_mesh_import(
        self,
        site_id: str,
        *,
        profile: dict[str, object],
        staging_dir: Path,
        uploads: list[Path],
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        try:
            staged = self._validated_staged_files(site_id, staging_dir, uploads)
            mr_id = str(profile.get("mr_id") or "").strip()
            display_name = str(profile.get("display_name") or "").strip()
            if not mr_id or not display_name:
                raise RailTransitWebError("PROFILE_REQUIRED", "MESH 导入缺少 MR 身份")
            safe_folder = self._safe_name(str(profile.get("safe_folder_name") or mr_id))
            if not safe_folder:
                raise RailTransitWebError("PROFILE_INVALID", "MESH MR 目录名无效")
            profile_payload = {
                "mr_id": mr_id,
                "display_name": display_name,
                "safe_folder_name": safe_folder,
                "relative_folder_path": f"files/rail_transit/mr_raw_mesh/{safe_folder}",
                "linked_device_id": profile.get("linked_device_id"),
                "notes": str(profile.get("notes") or ""),
            }
            return self._start_task(
                site_id,
                "mesh_log_import",
                {"profile": profile_payload, "files": [str(path) for path in staged]},
                on_complete=lambda _value: self._cleanup_staging(site_id, staging_dir),
            )
        except Exception:
            self._cleanup_staging(site_id, staging_dir)
            raise

    def start_car_network_diagnostic(self, site_id: str, *, train_id: str = "") -> RailTransitTaskDTO:
        return self._start_task(self._site(site_id), "car_network_refresh_all", {"train_id": str(train_id or "").strip()})

    def start_online_mr_report(self, site_id: str, session_id: str, output_name: str = "") -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        detail = self.query_service.get_session(site_id, session_id)
        root = self.paths.online_mr_root(site_id).resolve()
        session_dir = (root / detail.session_path_reference).resolve()
        self._require_within(session_dir, root)
        if not session_dir.is_dir() or session_dir.is_symlink():
            raise RailTransitWebError("SESSION_NOT_FOUND", "Online MR 会话不存在")
        task_id = f"rail-export-{uuid4().hex}"
        name = self._report_name(output_name or f"{session_id}_online_mr.xlsx")
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner=self._OWNER,
            source="online_mr_report",
            artifact_type="xlsx",
            task_id=task_id,
            output_root=root / "reports",
            preferred_name=name,
        )
        job = online_mr_report_xlsx_spec(
            reservation.output_path,
            session_dir=session_dir,
            title="Online MR 分析报告",
            open_dir_on_success=False,
        ).to_job(task_id)
        return self._start_export(site_id, replace(job, site_name=site_id), "online_mr_report", reservation)

    def start_mesh_report(self, site_id: str, session_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        try:
            context = self.mesh_query_service._context(site_id, session_id)
        except MeshAnalysisQueryError as exc:
            raise RailTransitWebError("MESH_SESSION_NOT_FOUND", str(exc)) from exc
        if context.detail_db is None or not context.detail_db.is_file():
            raise RailTransitWebError("MESH_RESULT_NOT_FOUND", "MESH 结构化分析结果不存在")
        output_root = self.paths.mesh_mr_export_dir(site_id, context.safe_folder_name).resolve()
        self._require_within(output_root, self.paths.site_mesh_root(site_id).resolve())
        task_id = f"rail-export-{uuid4().hex}"
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner=self._OWNER,
            source="mesh_analysis_report",
            artifact_type="xlsx",
            task_id=task_id,
            output_root=output_root,
            preferred_name=f"{context.mr_name}_MESH分析报告.xlsx",
        )
        job = ExportJob(
            job_id=task_id,
            job_type="mesh_analysis_report",
            site_name=site_id,
            output_path=str(reservation.output_path),
            db_path=str(context.detail_db),
            params={
                "payload": {
                    "mr_name": context.mr_name,
                    "source_file_ids": [context.source_id],
                    "options": {"report_name": f"{context.mr_name} MESH 分析报告"},
                }
            },
        )
        return self._start_export(site_id, job, "mesh_analysis_report", reservation)

    def get_task(self, site_id: str, task_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        return self._task_dto(site_id, self._snapshot(site_id, task_id))

    def cancel_task(self, site_id: str, task_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        snapshot = self._snapshot(site_id, task_id)
        if snapshot.status not in TERMINAL_TASK_STATES:
            cancelled = self.process_adapter.cancel_job(task_id) or self.export_adapter.cancel_job(task_id)
            if not cancelled:
                self._reconcile_owned_orphans(site_id)
            snapshot = self._snapshot(site_id, task_id)
        return self._task_dto(site_id, snapshot)

    def recover_tasks(self, site_id: str) -> list[RailTransitTaskDTO]:
        site_id = self._site(site_id)
        repository = self.task_service.repository(site_id)
        recovered = {item.task_id: item for item in self._reconcile_owned_orphans(site_id)}
        for item in repository.list(statuses=TERMINAL_TASK_STATES, limit=1000):
            if item.site_name != site_id or not self._authorized(item):
                continue
            cleaned = self._cleanup_recovered_task(site_id, item)
            if item.task_type.startswith("web_export_"):
                cleaned = self.artifact_store.recover_task(
                    site_id,
                    item.task_id,
                    owner=self._OWNER,
                    sources=self._ARTIFACT_SOURCES,
                    succeeded=item.status == TaskState.COMPLETED,
                ) or cleaned
            if cleaned:
                recovered[item.task_id] = item
        return [self._task_dto(site_id, item) for item in recovered.values()]

    def open_online_mr_report(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "online_mr_report")

    def open_mesh_report(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "mesh_analysis_report")

    def query_metrics(
        self,
        site_id: str,
        session_id: str,
        metric_types: list[str],
        *,
        start_time: str = "",
        end_time: str = "",
        limit: int = 5_000,
        downsample: str = OnlineMrDownsampleMode.NONE.value,
        bucket_seconds: int = 1,
    ):
        site_id = self._site(site_id)
        return self.query_service.query_metrics(
            site_id,
            session_id,
            [OnlineMrMetricType(value) for value in metric_types],
            start_time=start_time or None,
            end_time=end_time or None,
            limit=limit,
            downsample=downsample,
            bucket_seconds=bucket_seconds,
        )

    def query_timeline(self, site_id: str, session_id: str, *, limit: int = 500, offset: int = 0):
        return self.query_service.query_timeline(self._site(site_id), session_id, limit=limit, offset=offset)

    def database_summary(self, site_id: str, session_id: str):
        return self.query_service.get_database_summary(self._site(site_id), session_id)

    def artifacts(self, site_id: str, session_id: str):
        return self.query_service.list_artifacts(self._site(site_id), session_id)

    def _start_task(
        self,
        site_id: str,
        task_type: str,
        params: dict[str, object],
        *,
        on_complete=None,
    ) -> RailTransitTaskDTO:
        if task_type not in self._TASK_NAMES:
            raise RailTransitWebError("TASK_NOT_ALLOWED", "不支持的轨交 Web 任务")
        task_id = f"rail-web-{uuid4().hex}"
        job_params = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": self._TASK_NAMES[task_type],
            "owner": self._OWNER,
            "task_source": "local",
            **params,
        }
        self.process_adapter.start_job(
            BackgroundJob(job_id=task_id, task_type=task_type, params=job_params),
            on_complete=on_complete,
        )
        return self.get_task(site_id, task_id)

    def _start_export(
        self,
        site_id: str,
        job: ExportJob,
        action: str,
        reservation: ReservedWebArtifact,
    ) -> RailTransitTaskDTO:
        def completed(value: LocalProcessCompletion) -> None:
            if value.exit_code == 0 and not value.cancelled:
                try:
                    self.artifact_store.complete(reservation)
                except WebArtifactError:
                    self.artifact_store.fail(reservation)
            else:
                self.artifact_store.fail(reservation)

        try:
            self.export_adapter.start_export(job, task_name=action, owner=self._OWNER, on_complete=completed)
        except Exception:
            self.artifact_store.fail(reservation)
            raise
        snapshot = self._snapshot(site_id, job.job_id)
        return RailTransitTaskDTO(
            task_id=job.job_id,
            status=snapshot.status.value,
            action=action,
            artifact_id=reservation.artifact_id,
        )

    def _snapshot(self, site_id: str, task_id: str):
        snapshot = self.task_service.repository(site_id).get(str(task_id or ""))
        if snapshot is None or not self._authorized(snapshot) or snapshot.site_name != site_id:
            raise RailTransitWebError("TASK_NOT_FOUND", "任务不存在或不属于当前局点")
        return snapshot

    def _authorized(self, snapshot) -> bool:
        return (
            snapshot.owner == self._OWNER
            and snapshot.source == "local"
            and snapshot.task_type in self._ALLOWED_TASK_TYPES
        )

    def _task_dto(self, site_id: str, snapshot) -> RailTransitTaskDTO:
        metadata = self.artifact_store.task_metadata(
            site_id, snapshot.task_id, owner=self._OWNER, sources=self._ARTIFACT_SOURCES
        )
        action = self._ACTIONS.get(snapshot.task_type, snapshot.task_type)
        return RailTransitTaskDTO(
            task_id=snapshot.task_id,
            status=snapshot.status.value,
            action=action,
            artifact_id=str((metadata or {}).get("artifact_id") or ""),
            available=bool(metadata and metadata.get("completed") is True),
            sha256=str((metadata or {}).get("sha256") or ""),
            size_bytes=int((metadata or {}).get("size_bytes") or 0),
        )

    def _open_artifact(self, site_id: str, artifact_id: str, source: str) -> tuple[Path, str]:
        try:
            path, name, _manifest = self.artifact_store.open(
                site_id=self._site(site_id),
                artifact_id=artifact_id,
                owner=self._OWNER,
                source=source,
                artifact_type="xlsx",
            )
        except WebArtifactError as exc:
            raise RailTransitWebError("ARTIFACT_INVALID", str(exc)) from exc
        return path, name

    def _validated_staged_files(self, site_id: str, staging_dir: Path, uploads: list[Path]) -> list[Path]:
        expected_root = (self.paths.runtime_cache_dir / "rail_web_uploads" / site_id).resolve()
        if staging_dir.is_symlink():
            raise RailTransitWebError("STAGING_INVALID", "MESH 临时目录不受控")
        staging = staging_dir.resolve()
        if staging.parent != expected_root or not staging.is_dir():
            raise RailTransitWebError("STAGING_INVALID", "MESH 临时目录不受控")
        if not uploads:
            raise RailTransitWebError("FILE_REQUIRED", "至少选择一个 MESH 原始日志文件")
        result: list[Path] = []
        for path in uploads:
            if path.is_symlink():
                raise RailTransitWebError("FILE_PATH_INVALID", "MESH 上传文件路径无效")
            candidate = path.resolve()
            if candidate.parent != staging or not candidate.is_file():
                raise RailTransitWebError("FILE_PATH_INVALID", "MESH 上传文件路径无效")
            if candidate.suffix.casefold() not in self._UPLOAD_SUFFIXES:
                raise RailTransitWebError("FILE_TYPE_INVALID", "MESH 导入仅支持 LOG/TXT 文件")
            result.append(candidate)
        return result

    def _cleanup_staging(self, site_id: str, staging_dir: Path) -> None:
        root = (self.paths.runtime_cache_dir / "rail_web_uploads" / self._site(site_id)).resolve()
        staging = staging_dir.resolve()
        if staging.parent != root or staging == root:
            return
        try:
            shutil.rmtree(staging)
        except FileNotFoundError:
            pass

    def _reconcile_owned_orphans(self, site_id: str):
        repository = self.task_service.repository(site_id)
        active = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        owned_pids = {
            item.owner_pid
            for item in repository.list(statuses=active, limit=1000)
            if item.site_name == site_id and self._authorized(item) and item.owner_pid > 0
        }
        if not owned_pids:
            return []
        return repository.reconcile_orphaned_local_tasks(
            lambda pid: True if pid not in owned_pids else self.task_service._is_process_alive(pid)
        )

    def _cleanup_recovered_task(self, site_id: str, snapshot) -> bool:
        cleaned = False
        if snapshot.task_type == "mesh_log_import":
            job_path = self.paths.runtime_cache_dir / "background_jobs" / f"{snapshot.task_id}.json"
            try:
                payload = json.loads(job_path.read_text(encoding="utf-8"))
                params = dict(payload.get("params") or {})
                files = [Path(str(value)) for value in params.get("files") or ()]
                if params.get("site_name") == site_id and files:
                    self._cleanup_staging(site_id, files[0].parent)
                    cleaned = True
            except (OSError, ValueError, TypeError):
                pass
        for directory, suffix in (
            (self.paths.runtime_cache_dir / "background_jobs", ".json"),
            (self.paths.runtime_cache_dir / "background_jobs", ".cancel"),
            (self.paths.runtime_cache_dir / "export_jobs", ".json"),
            (self.paths.runtime_cache_dir / "export_jobs", ".json.tmp"),
        ):
            path = (directory / f"{snapshot.task_id}{suffix}").resolve()
            try:
                if directory.resolve() in path.parents and path.exists():
                    path.unlink(missing_ok=True)
                    cleaned = True
            except OSError:
                pass
        return cleaned

    def _site(self, site_id: str) -> str:
        try:
            value = SiteManager(self.paths).validate_site_name(str(site_id or ""))
        except ValueError as exc:
            raise RailTransitWebError("SITE_CONTEXT_INVALID", "局点标识无效") from exc
        root = self.paths.site_dir(value).resolve()
        self._require_within(root, self.paths.sites_dir.resolve())
        if not root.is_dir():
            raise RailTransitWebError("SITE_CONTEXT_INVALID", "当前局点不存在")
        return value

    @classmethod
    def _safe_name(cls, value: str) -> str:
        return cls._SAFE_NAME.sub("_", Path(value).name).strip("._ ")

    @classmethod
    def _report_name(cls, value: str) -> str:
        name = cls._safe_name(value)
        if not name.casefold().endswith(".xlsx"):
            name += ".xlsx"
        return name

    @staticmethod
    def _require_within(path: Path, root: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise RailTransitWebError("PATH_OUTSIDE_ROOT", "路径不在受控目录") from exc
        if path == root:
            raise RailTransitWebError("PATH_OUTSIDE_ROOT", "文件路径不能等于受控目录")


__all__ = ["RailTransitWebApplicationService", "RailTransitWebError"]
