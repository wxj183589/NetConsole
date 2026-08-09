from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from netconsole.application.desktop import DesktopActionService
from netconsole.application.web_artifacts import ReservedWebArtifact, WebArtifactError, WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.core import app_logger
from netconsole.core.log_policy import LOG_POLICY
from netconsole.core.paths import PathResolver
from netconsole.core.resources import changelog_path
from netconsole.core.sites import SiteManager
from netconsole.core.version import APP_AUTHOR, APP_TITLE_DISPLAY, APP_VERSION_DISPLAY, REPOSITORY_WEB_URLS
from netconsole.models.api.system_maintenance import (
    AboutDTO,
    AboutLinkDTO,
    ChangelogDTO,
    CleanupItemDTO,
    DesktopActionDTO,
    ExternalLinkDTO,
    LogEntryDTO,
    LogPageDTO,
    MaintenanceTaskDTO,
    OpenSourceComponentDTO,
)
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.services.background_job import BackgroundJob
from netconsole.services.app_auto_cleanup import (
    AUTO_CLEANUP_ITEM_IDS,
    AppCleanupService,
    claim_auto_cleanup,
    finish_auto_cleanup,
)
from netconsole.services.export.export_task_builders import app_logs_csv_spec, open_source_notices_spec
from netconsole.services.export.export_task_builders import ExportTaskSpec
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.web_export_event_safety import sanitize_web_export_snapshot
from netconsole.services.system_maintenance_redaction import redact_system_maintenance_text
from netconsole.services.log_display import display_log_row


class SystemMaintenanceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SystemMaintenanceResolver:
    """只解析固定模块 ID；不保存 Artifact 或任务状态。"""

    ARTIFACTS = {
        "logs_current": ("system_logs_current", "csv", "web_export_app_logs_csv", "app_log_current.csv"),
        "logs_all": ("system_logs_all", "csv", "web_export_app_logs_csv", "app_log_all.csv"),
        "open_source_txt": ("system_open_source_txt", "txt", "web_export_open_source_notices", "open_source_notices.txt"),
        "open_source_xlsx": ("system_open_source_xlsx", "xlsx", "web_export_open_source_notices", "open_source_notices.xlsx"),
    }
    DIRECTORIES = {"logs": "system_logs", "cache": "system_cache"}

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def output_root(self, site_id: str) -> Path:
        return self.paths.site_files_dir(site_id) / "system_maintenance" / "outputs"

    def artifact(self, kind: str) -> tuple[str, str, str, str]:
        try:
            return self.ARTIFACTS[str(kind)]
        except KeyError as exc:
            raise SystemMaintenanceError("ARTIFACT_KIND_INVALID", "导出类型无效") from exc

    def artifact_kind(self, source: str) -> str:
        return next((kind for kind, value in self.ARTIFACTS.items() if value[0] == source), "")

    def source_task_types(self) -> dict[str, str]:
        return {source: task_type for source, _artifact_type, task_type, _name in self.ARTIFACTS.values()}

    def directory_id(self, kind: str) -> str:
        try:
            return self.DIRECTORIES[str(kind)]
        except KeyError as exc:
            raise SystemMaintenanceError("DIRECTORY_KIND_INVALID", "目录类型无效") from exc


SYSTEM_MAINTENANCE_WEB_OWNER = "web_system_maintenance"
SYSTEM_MAINTENANCE_TASK_TYPES = frozenset(
    {
        "system_maintenance_cleanup",
        "open_source_notice_scan",
        "web_export_app_logs_csv",
        "web_export_open_source_notices",
    }
)


class SystemMaintenanceApplicationService:
    _OWNER = SYSTEM_MAINTENANCE_WEB_OWNER
    _TASK_TYPES = SYSTEM_MAINTENANCE_TASK_TYPES

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        process_adapter: LocalProcessAdapter,
        export_adapter: WebExportProcessAdapter,
        artifact_store: WebArtifactStore,
        desktop_action_service: DesktopActionService,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter
        self.export_adapter = export_adapter
        self.artifact_store = artifact_store
        self.desktop_action_service = desktop_action_service
        self.resolver = SystemMaintenanceResolver(paths)

    def current_site_id(self) -> str:
        try:
            data = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
            value = data.get("current_site") if isinstance(data, dict) else None
        except (OSError, TypeError, json.JSONDecodeError):
            value = self.task_service.site_name
        return self._site(str(value or self.task_service.site_name or "demo"))

    def list_logs(self, *, page: int, page_size: int, keyword: str = "", level: str = "") -> LogPageDTO:
        result = app_logger.get_logs(
            page=page,
            page_size=page_size,
            keyword=keyword or None,
            level=level or None,
            log_path=self.paths.app_log_path,
        )
        items: list[LogEntryDTO] = []
        for row in result.rows:
            display = display_log_row({key: redact_system_maintenance_text(value) for key, value in row.items()})
            items.append(
                LogEntryDTO(
                    time=str(display.get("time") or ""),
                    level=str(display.get("raw_level") or ""),
                    display_level=str(display.get("display_level") or ""),
                    display_event=str(display.get("display_event") or ""),
                    display_detail=str(display.get("display_detail") or ""),
                    raw_event=str(display.get("raw_event") or ""),
                    raw_detail=str(display.get("raw_detail") or ""),
                )
            )
        return LogPageDTO(
            items=items,
            page=result.state.current_page,
            page_size=result.state.page_size,
            total=result.state.total_items,
            total_pages=result.state.total_pages,
        )

    def clear_logs(self) -> DesktopActionDTO:
        app_logger.clear_logs(self.paths.app_log_path)
        app_logger.log_info("LOGS_CLEARED", "运行日志已清空", log_path=self.paths.app_log_path)
        return DesktopActionDTO(success=True, code="completed", message="日志中心记录已清空")

    def start_cleanup(
        self,
        site_id: str,
        *,
        dry_run: bool,
        retention_days: int = 3,
        selected_item_ids: list[str] | tuple[str, ...] = (),
        confirmed: bool = False,
        automatic: bool = False,
    ) -> MaintenanceTaskDTO | None:
        site_id = self._site(site_id)
        days = LOG_POLICY.backend.retention_days if automatic else int(retention_days)
        if not 1 <= days <= 365:
            raise SystemMaintenanceError("RETENTION_DAYS_INVALID", "保留天数必须在 1 到 365 之间")
        selected = [str(value).strip() for value in selected_item_ids]
        if automatic:
            if dry_run:
                raise SystemMaintenanceError("CLEANUP_REQUEST_INVALID", "自动清理不能使用扫描模式")
            selected = list(AUTO_CLEANUP_ITEM_IDS)
            confirmed = True
        if dry_run:
            if selected or confirmed:
                raise SystemMaintenanceError("CLEANUP_REQUEST_INVALID", "扫描请求不能包含清理选择或确认")
        elif not selected or not confirmed:
            raise SystemMaintenanceError("CLEANUP_CONFIRMATION_REQUIRED", "正式清理必须选择项目并明确确认")
        else:
            try:
                selected = list(AppCleanupService.validate_item_ids(selected))
            except ValueError as exc:
                raise SystemMaintenanceError("CLEANUP_ITEMS_INVALID", str(exc)) from exc
        task_id = f"system-maintenance-{uuid4().hex}"
        action = "cleanup_scan" if dry_run else ("cleanup_auto" if automatic else "cleanup_clean")
        name = {"cleanup_scan": "扫描日志与缓存", "cleanup_clean": "安全清理日志与缓存", "cleanup_auto": "自动清理软件运行日志"}[action]
        if automatic and not claim_auto_cleanup(self.paths, task_id):
            return None
        try:
            self.process_adapter.start_job(
                BackgroundJob(
                    job_id=task_id,
                    task_type="system_maintenance_cleanup",
                    params={
                        "site_name": site_id,
                        "task_name": name,
                        "owner": self._OWNER,
                        "task_source": "local",
                        "app_root": str(self.paths.app_root),
                        "data_root": str(self.paths.data_root),
                        "retention_days": days,
                        "dry_run": dry_run,
                        "selected_item_ids": selected,
                        "confirmed": bool(confirmed),
                        "automatic": automatic,
                        "_cancel_grace_ms": 3_000,
                    },
                )
            )
        except Exception:
            if automatic:
                finish_auto_cleanup(self.paths, task_id, succeeded=False)
            raise
        return self.get_task(site_id, task_id)

    def start_open_source_scan(self, site_id: str) -> MaintenanceTaskDTO:
        site_id = self._site(site_id)
        task_id = f"open-source-scan-{uuid4().hex}"
        self.process_adapter.start_job(
            BackgroundJob(
                job_id=task_id,
                task_type="open_source_notice_scan",
                params={
                    "site_name": site_id,
                    "task_name": "扫描开源依赖",
                    "owner": self._OWNER,
                    "task_source": "local",
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                },
            )
        )
        return self.get_task(site_id, task_id)

    def start_log_export(
        self,
        site_id: str,
        *,
        scope: str,
        keyword: str,
        level: str,
        page: int,
        page_size: int,
    ) -> MaintenanceTaskDTO:
        site_id = self._site(site_id)
        kind = "logs_current" if scope == "current" else "logs_all"
        source, artifact_type, task_type, name = self.resolver.artifact(kind)
        task_id = f"system-log-export-{uuid4().hex}"
        reservation = self._reserve(site_id, task_id, source, artifact_type, task_type, name)
        spec = app_logs_csv_spec(
            reservation.output_path,
            log_path=self.paths.app_log_path,
            log_paths=app_logger.log_files(self.paths.app_log_path),
            keyword=keyword or None,
            level=level or None,
            offset=(page - 1) * page_size if scope == "current" else 0,
            limit=page_size if scope == "current" else 0,
            redact_web=True,
            title="导出当前页日志" if scope == "current" else "导出全部筛选日志",
        )
        return self._start_export(site_id, spec, reservation, kind)

    def start_open_source_export(self, site_id: str, *, format: str) -> MaintenanceTaskDTO:
        site_id = self._site(site_id)
        kind = f"open_source_{format}"
        source, artifact_type, task_type, name = self.resolver.artifact(kind)
        task_id = f"open-source-export-{uuid4().hex}"
        reservation = self._reserve(site_id, task_id, source, artifact_type, task_type, name)
        spec = open_source_notices_spec(
            reservation.output_path,
            base_dir=self.paths.app_root,
            format=format,
            title="导出开源许可说明",
        )
        return self._start_export(site_id, spec, reservation, kind)

    def get_task(self, site_id: str, task_id: str) -> MaintenanceTaskDTO:
        site_id = self._site(site_id)
        snapshot = self.task_service.repository(site_id).get(str(task_id or ""))
        if snapshot is None or snapshot.site_name != site_id or not self._authorized(snapshot):
            raise SystemMaintenanceError("TASK_NOT_FOUND", "任务不存在或不属于当前模块")
        return self._task_dto(site_id, snapshot)

    def recover_tasks(self, site_id: str) -> list[MaintenanceTaskDTO]:
        site_id = self._site(site_id)
        repository = self.task_service.repository(site_id)
        for snapshot in repository.list(statuses=TERMINAL_TASK_STATES, limit=1000):
            if snapshot.site_name != site_id or not self._authorized(snapshot) or not snapshot.task_type.startswith("web_export_"):
                continue
            try:
                self.artifact_store.recover_task(
                    site_id,
                    snapshot.task_id,
                    owner=self._OWNER,
                    source_task_types=self.resolver.source_task_types(),
                    succeeded=snapshot.status is TaskState.COMPLETED,
                )
            except WebArtifactError:
                continue
        return [
            self._task_dto(site_id, item)
            for item in repository.list(limit=200)
            if item.site_name == site_id and self._authorized(item)
        ]

    def cancel_task(self, site_id: str, task_id: str) -> MaintenanceTaskDTO:
        task = self.get_task(site_id, task_id)
        if task.status in {state.value for state in TERMINAL_TASK_STATES}:
            return task
        cancelled = self.process_adapter.cancel_job(task_id)
        if not cancelled:
            cancelled = self.export_adapter.cancel_job(task_id)
        if not cancelled:
            raise SystemMaintenanceError("TASK_NOT_CANCELLABLE", "任务当前不支持取消或执行进程已退出")
        return self.get_task(site_id, task_id)

    def open_artifact(self, site_id: str, kind: str, artifact_id: str) -> tuple[Path, str]:
        source, artifact_type, task_type, name = self.resolver.artifact(kind)
        try:
            path, _stored_name, _manifest = self.artifact_store.open(
                site_id=self._site(site_id),
                artifact_id=artifact_id,
                owner=self._OWNER,
                source=source,
                artifact_type=artifact_type,
                task_type=task_type,
            )
        except WebArtifactError as exc:
            raise SystemMaintenanceError("ARTIFACT_INVALID", redact_system_maintenance_text(exc)) from exc
        return path, _stored_name or name

    def changelog(self) -> ChangelogDTO:
        try:
            content = changelog_path().read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemMaintenanceError("CHANGELOG_UNAVAILABLE", "更新日志暂不可用") from exc
        return ChangelogDTO(title=f"更新日志 {APP_VERSION_DISPLAY}", version=APP_VERSION_DISPLAY, content=content)

    def about(self) -> AboutDTO:
        return AboutDTO(
            title=APP_TITLE_DISPLAY,
            version=APP_VERSION_DISPLAY,
            author=APP_AUTHOR,
            external_tool_notice=(
                "IPOP v4.1 为第三方可选外部工具，不随 NetConsole 分发。"
                "NetConsole 仅启动用户自行取得并配置的本地程序，相关权利归其权利人所有。"
            ),
            repositories=[AboutLinkDTO(link_id=f"repository-{index}", label=url) for index, url in enumerate(REPOSITORY_WEB_URLS, start=1)],
        )

    def about_link(self, link_id: str) -> ExternalLinkDTO:
        try:
            index = int(str(link_id).removeprefix("repository-")) - 1
            if index < 0:
                raise IndexError(index)
            url = REPOSITORY_WEB_URLS[index]
        except (ValueError, IndexError) as exc:
            raise SystemMaintenanceError("LINK_NOT_FOUND", "外链标识无效") from exc
        return ExternalLinkDTO(url=self._https_url(url))

    def open_source_link(self, site_id: str, task_id: str, component_index: int) -> ExternalLinkDTO:
        task = self.get_task(site_id, task_id)
        if task.action != "open_source_scan" or task.status != TaskState.COMPLETED.value:
            raise SystemMaintenanceError("LINK_NOT_READY", "依赖扫描任务尚未完成")
        try:
            if component_index < 0:
                raise IndexError(component_index)
            url = task.components[component_index].homepage
        except IndexError as exc:
            raise SystemMaintenanceError("LINK_NOT_FOUND", "组件外链不存在") from exc
        return ExternalLinkDTO(url=self._https_url(url))

    def open_directory(self, kind: str) -> DesktopActionDTO:
        path = self.paths.logs_dir if kind == "logs" else self.paths.runtime_cache_dir if kind == "cache" else None
        if path is None:
            raise SystemMaintenanceError("DIRECTORY_KIND_INVALID", "目录类型无效")
        path.mkdir(parents=True, exist_ok=True)
        result = self.desktop_action_service.open_controlled_directory(self.resolver.directory_id(kind))
        return DesktopActionDTO(success=result.success, code=result.code, message=redact_system_maintenance_text(result.message))

    def _reserve(
        self,
        site_id: str,
        task_id: str,
        source: str,
        artifact_type: str,
        task_type: str,
        name: str,
    ) -> ReservedWebArtifact:
        try:
            return self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source=source,
                artifact_type=artifact_type,
                task_id=task_id,
                task_type=task_type,
                output_root=self.resolver.output_root(site_id),
                preferred_name=name,
            )
        except WebArtifactError as exc:
            if "来源不受支持" in str(exc):
                raise SystemMaintenanceError(
                    "BLOCKED_ON_TASK_WINDOW",
                    "BLOCKED_ON_TASK_WINDOW：统一任务窗口尚未登记系统维护 Artifact 来源",
                ) from exc
            raise SystemMaintenanceError("ARTIFACT_RESERVE_FAILED", redact_system_maintenance_text(exc)) from exc

    def _start_export(
        self,
        site_id: str,
        spec: ExportTaskSpec,
        reservation: ReservedWebArtifact,
        kind: str,
    ) -> MaintenanceTaskDTO:
        job = replace(spec.to_job(reservation.task_id), site_name=site_id)

        def completed(value: LocalProcessCompletion) -> None:
            try:
                if value.exit_code == 0 and not value.cancelled:
                    self.artifact_store.complete(reservation)
                else:
                    self.artifact_store.fail(reservation)
            except WebArtifactError:
                self.artifact_store.fail(reservation)

        try:
            public_name = self.resolver.artifact(kind)[3]
            self.export_adapter.start_export(
                job,
                task_name=kind,
                owner=self._OWNER,
                public_result={
                    "artifact_id": reservation.artifact_id,
                    "artifact_name": public_name,
                    "artifact_source": reservation.source,
                    "artifact_type": reservation.artifact_type,
                },
                on_complete=completed,
            )
        except Exception as exc:
            self.artifact_store.fail(reservation)
            raise SystemMaintenanceError("EXPORT_START_FAILED", redact_system_maintenance_text(exc)) from exc
        return self.get_task(site_id, reservation.task_id)

    def _task_dto(self, site_id: str, snapshot) -> MaintenanceTaskDTO:
        snapshot = sanitize_web_export_snapshot(snapshot)
        metadata = self.artifact_store.task_metadata(
            site_id,
            snapshot.task_id,
            owner=self._OWNER,
            source_task_types=self.resolver.source_task_types(),
        )
        result = dict(snapshot.result or {})
        progress_details = self._progress_details(site_id, snapshot.task_id)
        cleanup_items = [CleanupItemDTO(**item) for item in result.get("cleanup_items", []) if isinstance(item, dict)]
        components: list[OpenSourceComponentDTO] = []
        for item in result.get("components", []):
            if not isinstance(item, dict):
                continue
            components.append(
                OpenSourceComponentDTO(
                    name=redact_system_maintenance_text(item.get("name")),
                    version=redact_system_maintenance_text(item.get("version")),
                    license=redact_system_maintenance_text(item.get("license")),
                    purpose=redact_system_maintenance_text(item.get("purpose")),
                    homepage=self._optional_https_url(item.get("homepage")),
                    note=redact_system_maintenance_text(item.get("note")),
                )
            )
        source = str((metadata or {}).get("source") or "")
        action = self.resolver.artifact_kind(source) or {
            "扫描日志与缓存": "cleanup_scan",
            "安全清理日志与缓存": "cleanup_clean",
            "自动安全清理": "cleanup_auto",
            "自动清理软件运行日志": "cleanup_auto",
            "扫描开源依赖": "open_source_scan",
        }.get(snapshot.task_name, snapshot.task_type)
        return MaintenanceTaskDTO(
            task_id=snapshot.task_id,
            status=snapshot.status.value,
            action=action,
            progress=snapshot.progress,
            stage=snapshot.stage,
            message=redact_system_maintenance_text(snapshot.message),
            error_message=redact_system_maintenance_text(snapshot.error_message),
            artifact_id=str((metadata or {}).get("artifact_id") or ""),
            artifact_kind=self.resolver.artifact_kind(source),
            artifact_name=str((metadata or {}).get("display_name") or ""),
            available=bool(metadata and metadata.get("completed") is True),
            sha256=str((metadata or {}).get("sha256") or ""),
            size_bytes=int((metadata or {}).get("size_bytes") or 0),
            cleanup_items=cleanup_items,
            processed_files=int(result.get("processed_files") or progress_details.get("processed_files") or snapshot.current or 0),
            deleted_files=int(result.get("deleted_files") or progress_details.get("deleted_files") or 0),
            failed_count=int(result.get("failed_count") or progress_details.get("failed_count") or 0),
            freed_bytes=int(result.get("freed_bytes") or progress_details.get("freed_bytes") or 0),
            deleted_log_records=int(result.get("deleted_log_records") or progress_details.get("deleted_log_records") or 0),
            scanned_log_records=int(result.get("scanned_log_records") or progress_details.get("scanned_log_records") or 0),
            malformed_log_records=int(result.get("malformed_log_records") or progress_details.get("malformed_log_records") or 0),
            rewritten_log_files=int(result.get("rewritten_log_files") or progress_details.get("rewritten_log_files") or 0),
            cutoff=str(result.get("cutoff") or ""),
            components=components,
        )

    def _progress_details(self, site_id: str, task_id: str) -> dict[str, int]:
        repository = self.task_service.repository(site_id)
        after_sequence = max(0, repository.last_event_sequence() - 500)
        events = repository.list_events(task_id, after_sequence=after_sequence, limit=500)
        for event in reversed(events):
            if event.get("type") != "progress":
                continue
            payload = event.get("payload")
            details = payload.get("details") if isinstance(payload, dict) else None
            if not isinstance(details, dict):
                continue
            return {
                key: _nonnegative_int(details.get(key))
                for key in (
                    "processed_files",
                    "deleted_files",
                    "failed_count",
                    "freed_bytes",
                    "deleted_log_records",
                    "scanned_log_records",
                    "malformed_log_records",
                    "rewritten_log_files",
                )
            }
        return {}

    def _authorized(self, snapshot) -> bool:
        return snapshot.owner == self._OWNER and snapshot.source == "local" and snapshot.task_type in self._TASK_TYPES

    def _site(self, site_id: str) -> str:
        try:
            site = SiteManager(self.paths).validate_site_name(str(site_id or ""))
        except ValueError as exc:
            raise SystemMaintenanceError("SITE_INVALID", "局点标识无效") from exc
        if not self.paths.site_dir(site).is_dir():
            raise SystemMaintenanceError("SITE_NOT_FOUND", "局点不存在")
        return site

    @staticmethod
    def _https_url(value: object) -> str:
        url = str(value or "").strip()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise SystemMaintenanceError("LINK_NOT_ALLOWED", "只允许打开已登记的 HTTPS 外链")
        return url

    @classmethod
    def _optional_https_url(cls, value: object) -> str:
        try:
            return cls._https_url(value)
        except SystemMaintenanceError:
            return ""


__all__ = ["SystemMaintenanceApplicationService", "SystemMaintenanceError", "SystemMaintenanceResolver"]


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
