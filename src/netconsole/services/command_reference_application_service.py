from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from netconsole.application.web_artifacts import WebArtifactError, WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.command_reference import (
    CommandReferenceDTO,
    CommandReferenceFiltersDTO,
    CommandReferencePageDTO,
    CommandReferenceSummaryDTO,
)
from netconsole.models.task_state import TaskState
from netconsole.services.command_reference_service import (
    CommandReference,
    command_reference_path,
    load_command_references,
    unique_values,
)
from netconsole.services.export.export_task_builders import command_reference_markdown_spec
from netconsole.services.job_center.local_process_adapter import LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.web_export_event_safety import sanitize_web_export_snapshot


class CommandReferenceApplicationError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class CommandReferenceApplicationService:
    _OWNER = "web_command_reference"
    _TASK_TYPE = "web_export_command_reference_markdown"
    _ARTIFACT_SOURCE = "command_reference_export"
    _ARTIFACT_DISPLAY_NAME = "NetConsole_软件使用命令清单.md"

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        export_adapter: WebExportProcessAdapter,
        artifact_store: WebArtifactStore,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.export_adapter = export_adapter
        self.artifact_store = artifact_store

    def list_references(self, **filters: str) -> CommandReferencePageDTO:
        references = load_command_references(self.paths)
        keyword = str(filters.pop("query", "") or "").strip().casefold()
        result = [
            item
            for item in references
            if (not keyword or keyword in self._search_blob(item))
            and all(not value or str(getattr(item, field, "")) == value for field, value in filters.items())
        ]
        return CommandReferencePageDTO(
            items=[self._reference_dto(item) for item in result],
            filters=CommandReferenceFiltersDTO(
                modules=unique_values(references, "module"),
                device_scopes=unique_values(references, "device_scope"),
                vendors=unique_values(references, "vendor"),
                protocols=unique_values(references, "protocol"),
                categories=unique_values(references, "category"),
                risk_levels=unique_values(references, "risk_level"),
            ),
            summary=CommandReferenceSummaryDTO(
                total=len(references),
                shown=len(result),
                switch_count=sum(item.device_scope.startswith("交换机") for item in references),
                non_cli_count=sum(not item.is_cli for item in references),
            ),
        )

    def start_export(self, selected_ids: list[str]):
        site_id = self.current_site_id()
        known_ids = {item.id for item in load_command_references(self.paths)}
        selected = list(dict.fromkeys(str(value) for value in selected_ids if str(value)))
        if len(selected) != len(selected_ids) or any(value not in known_ids for value in selected):
            raise CommandReferenceApplicationError("INVALID_EXPORT_SELECTION", "导出范围包含无效命令标识")
        task_id = f"command-reference-export-{uuid4().hex}"
        try:
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source=self._ARTIFACT_SOURCE,
                artifact_type="md",
                task_id=task_id,
                task_type=self._TASK_TYPE,
                output_root=self._export_root(site_id),
                preferred_name=self._ARTIFACT_DISPLAY_NAME,
            )
        except WebArtifactError as exc:
            raise CommandReferenceApplicationError("ARTIFACT_CONTRACT_UNAVAILABLE", "命令说明导出能力暂时不可用") from exc
        job = command_reference_markdown_spec(
            reservation.output_path,
            resource_path=command_reference_path(self.paths),
            selected_ids=selected,
            title="导出命令说明",
            open_dir_on_success=False,
        ).to_job(task_id)
        job = replace(job, site_name=site_id)

        def completed(value: LocalProcessCompletion) -> None:
            if value.exit_code == 0 and not value.cancelled:
                try:
                    self.artifact_store.complete(reservation)
                    return
                except WebArtifactError:
                    pass
            self.artifact_store.fail(reservation, "命令说明 Artifact 不可用")

        try:
            self.export_adapter.start_export(
                job,
                task_name="命令说明 Markdown 导出",
                owner=self._OWNER,
                public_result={
                    "artifact_id": reservation.artifact_id,
                    "artifact_name": self._ARTIFACT_DISPLAY_NAME,
                    "artifact_source": self._ARTIFACT_SOURCE,
                    "artifact_type": "md",
                },
                on_complete=completed,
            )
        except Exception:
            self.artifact_store.fail(reservation, "命令说明导出启动失败")
            raise
        return self.get_task(task_id, site_id=site_id)

    def get_task(self, task_id: str, *, site_id: str | None = None):
        site_id = site_id or self.current_site_id()
        snapshot = self._snapshot(site_id, task_id)
        if snapshot.status is TaskState.COMPLETED and snapshot.result.get("artifact_pending") is True:
            self.artifact_store.recover_task(
                site_id,
                task_id,
                owner=self._OWNER,
                source_task_types={self._ARTIFACT_SOURCE: self._TASK_TYPE},
                succeeded=True,
            )
            snapshot = self._snapshot(site_id, task_id)
        return snapshot

    def cancel_task(self, task_id: str):
        site_id = self.current_site_id()
        self._snapshot(site_id, task_id)
        if not self.task_service.cancel_task(task_id):
            raise CommandReferenceApplicationError("EXPORT_NOT_CANCELLABLE", "导出任务当前不可取消")
        return self.get_task(task_id, site_id=site_id)

    def open_artifact(self, artifact_id: str) -> tuple[Path, str]:
        try:
            path, name, _manifest = self.artifact_store.open(
                site_id=self.current_site_id(),
                artifact_id=artifact_id,
                owner=self._OWNER,
                source=self._ARTIFACT_SOURCE,
                artifact_type="md",
                task_type=self._TASK_TYPE,
            )
        except WebArtifactError as exc:
            raise CommandReferenceApplicationError("ARTIFACT_NOT_AVAILABLE", "Markdown Artifact 不存在或不可用") from exc
        return path, name

    def current_site_id(self) -> str:
        try:
            return SiteManager(self.paths).validate_site_name(str(SiteManager(self.paths).get_current_site() or "demo"))
        except (OSError, ValueError, KeyError) as exc:
            raise CommandReferenceApplicationError("SITE_CONTEXT_INVALID", "当前局点上下文无效") from exc

    def _snapshot(self, site_id: str, task_id: str):
        snapshot = self.task_service.repository(site_id).get(str(task_id or ""))
        if snapshot is None or snapshot.site_name != site_id or not self._authorized(snapshot):
            raise CommandReferenceApplicationError("EXPORT_NOT_FOUND", "导出任务不存在或不属于命令说明")
        return sanitize_web_export_snapshot(snapshot)

    def _authorized(self, snapshot) -> bool:
        return snapshot.owner == self._OWNER and snapshot.source == "local" and snapshot.task_type == self._TASK_TYPE

    def _export_root(self, site_id: str) -> Path:
        return self.paths.site_files_dir(site_id) / "command_reference" / "exports"

    @staticmethod
    def _search_blob(item: CommandReference) -> str:
        return " ".join(
            (
                item.id,
                item.module,
                item.device_scope,
                item.vendor,
                item.protocol,
                item.category,
                item.command_template,
                item.purpose,
                item.parser,
                item.consumer,
                item.notes,
                " ".join(item.source_locations),
            )
        ).casefold()

    @staticmethod
    def _reference_dto(item: CommandReference) -> CommandReferenceDTO:
        read_only = True if item.risk_level == "read_only" else False if item.risk_level == "config_write" else None
        return CommandReferenceDTO(
            **asdict(item),
            read_only=read_only,
            modifies_device_config=item.risk_level == "config_write",
            requires_interactive_confirmation=item.interactive_input,
        )


__all__ = ["CommandReferenceApplicationError", "CommandReferenceApplicationService"]
