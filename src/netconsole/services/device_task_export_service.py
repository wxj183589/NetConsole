from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

from netconsole.models.task_state import TERMINAL_TASK_STATES
from netconsole.services.device_task_service import DEVICE_TASK_OWNER, DeviceTaskApplicationService
from netconsole.services.export.export_task_builders import markdown_text_spec, table_xlsx_spec
from netconsole.services.job_center.local_process_adapter import LocalProcessCompletion
from netconsole.services.web_artifacts import WebArtifactError, WebArtifactStore
from netconsole.services.web_export_process_adapter import WebExportProcessAdapter


class DeviceTaskExportService:
    def __init__(
        self, devices: DeviceTaskApplicationService, adapter: WebExportProcessAdapter,
        artifacts: WebArtifactStore,
    ) -> None:
        self.devices = devices
        self.adapter = adapter
        self.artifacts = artifacts

    def start(self, site: str, task_id: str) -> dict[str, str]:
        result = self.devices.result(site, task_id)
        snapshot = self.devices.task_service.repository(site).get(task_id)
        if snapshot.status not in TERMINAL_TASK_STATES:
            raise ValueError("任务结束后才能导出结果")
        if result.get("kind") == "config_generate":
            commands = result.get("commands", [])
            if result.get("business_status") != "SUCCESS" or not commands:
                raise ValueError("只有成功生成的配置可以另存")
            return self._export_configuration(site, commands)
        rows = []
        for item in result.get("items", [])[:64]:
            # Keep every bounded output, splitting text across Excel's cell limit.
            detail = json.dumps(item, ensure_ascii=False, default=str)
            chunks = [detail[index:index + 30000] for index in range(0, len(detail), 30000)]
            for index, chunk in enumerate(chunks, 1):
                rows.append({
                    "task_id": task_id, "kind": result.get("kind", ""),
                    "template_id": result.get("template", {}).get("template_id", ""),
                    "template_version": result.get("template", {}).get("version", ""),
                    "device_uuid": item.get("device_uuid", ""), "device_name": item.get("device_name", ""),
                    "status": item.get("status", ""), "started_at": item.get("started_at", ""),
                    "finished_at": item.get("finished_at", ""), "elapsed_ms": item.get("elapsed_ms", ""),
                    "part": index, "detail": chunk,
                })
        export_id = f"device-task-export-{uuid4().hex}"
        reservation = self.artifacts.reserve(
            site_id=site, owner=DEVICE_TASK_OWNER, source="device_task_results", artifact_type="xlsx",
            task_id=export_id, task_type="web_export_table_xlsx",
            output_root=self.devices.paths.site_files_dir(site) / "web_artifacts" / "device_tasks",
            preferred_name="设备任务结果.xlsx",
        )
        try:
            job = table_xlsx_spec(
                reservation.output_path,
                columns=[("任务 ID", "task_id"), ("任务类型", "kind"), ("模板 ID", "template_id"),
                         ("模板版本", "template_version"), ("设备 UUID", "device_uuid"),
                         ("设备", "device_name"), ("状态", "status"), ("开始时间", "started_at"),
                         ("完成时间", "finished_at"), ("耗时 ms", "elapsed_ms"),
                         ("结果分段", "part"), ("完整结果 JSON 分段", "detail")],
                rows=rows, sheet_name="设备任务结果", title="设备任务结果", open_dir_on_success=False,
                allow_inline_rows=True, inline_reason="Frozen persisted results for at most 64 devices",
            ).to_job(export_id)

            def completed(value: LocalProcessCompletion) -> None:
                if value.exit_code == 0 and not value.cancelled:
                    try:
                        self.artifacts.complete(reservation)
                        return
                    except WebArtifactError:
                        pass
                self.artifacts.fail(reservation, "设备任务结果导出失败")

            self.adapter.start_export(
                replace(job, site_name=site), task_name="设备任务结果导出", owner=DEVICE_TASK_OWNER,
                public_result={"artifact_id": reservation.artifact_id, "artifact_name": "设备任务结果.xlsx",
                               "artifact_source": "device_task_results", "artifact_type": "xlsx"},
                on_complete=completed,
            )
        except Exception:
            self.artifacts.fail(reservation, "设备任务结果导出启动失败")
            raise
        return {"task_id": export_id}

    def _export_configuration(self, site: str, commands: list[str]) -> dict[str, str]:
        export_id = f"device-task-export-{uuid4().hex}"
        title = "待审阅配置"
        name = f"{title}.txt"
        reservation = self.artifacts.reserve(
            site_id=site, owner=DEVICE_TASK_OWNER, source="device_task_results", artifact_type="txt",
            task_id=export_id, task_type="web_export_markdown_text",
            output_root=self.devices.paths.site_files_dir(site) / "web_artifacts" / "device_tasks",
            preferred_name=name,
        )
        try:
            job = markdown_text_spec(
                reservation.output_path, text="\n".join(commands) + "\n", title=title,
                open_dir_on_success=False, inline_reason="Bounded rendered template from persisted device task",
            ).to_job(export_id)

            def completed(value: LocalProcessCompletion) -> None:
                if value.exit_code == 0 and not value.cancelled:
                    try:
                        self.artifacts.complete(reservation)
                        return
                    except WebArtifactError:
                        pass
                self.artifacts.fail(reservation, "配置另存失败")

            self.adapter.start_export(
                replace(job, site_name=site), task_name=title, owner=DEVICE_TASK_OWNER,
                public_result={"artifact_id": reservation.artifact_id, "artifact_name": name,
                               "artifact_source": "device_task_results", "artifact_type": "txt"},
                on_complete=completed,
            )
        except Exception:
            self.artifacts.fail(reservation, "配置另存启动失败")
            raise
        return {"task_id": export_id}
