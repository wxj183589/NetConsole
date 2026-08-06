from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
    TaskResourceConflictError,
)
from netconsole.services.mesh_derived_data_maintenance_service import (
    MeshDerivedDataMaintenanceError,
    MeshDerivedDataMaintenanceService,
)


class MeshDerivedDataRepairCoordinator:
    """为同一局点合并等待的导入操作并复用唯一维护任务。"""

    TASK_TYPE = "mesh_derived_data_repair"
    _OWNER = "web_rail_transit"

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        process_adapter: LocalProcessAdapter,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter

    def enqueue_if_required(
        self,
        site_id: str,
        *,
        operation_kind: str,
        operation_payload: Mapping[str, object],
    ) -> RailTransitTaskDTO | None:
        maintenance = MeshDerivedDataMaintenanceService(self.paths)
        inspection = maintenance.inspect(site_id)
        if bool(inspection["compatible"]):
            return None
        maintenance.enqueue_operation(
            site_id,
            kind=operation_kind,
            payload=operation_payload,
        )
        task_id = f"mesh-derived-repair-{uuid4().hex}"
        job = BackgroundJob(
            job_id=task_id,
            task_type=self.TASK_TYPE,
            params={
                "site_name": site_id,
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
                "task_name": "自动修复 MESH 分析数据库",
                "owner": self._OWNER,
                "task_source": "local",
                "resource_keys": [
                    f"mesh-derived-repair:{site_id}",
                    f"mesh-import:{site_id}",
                ],
                "resource_conflict_message": "当前局点正在自动修复 MESH 分析数据库",
            },
        )
        try:
            self.process_adapter.start_job(job)
        except TaskResourceConflictError as exc:
            if exc.task.task_type != self.TASK_TYPE:
                raise MeshDerivedDataMaintenanceError("当前局点已有 MESH 导入任务正在运行") from exc
            task_id = exc.task.task_id
        except Exception as exc:
            raise MeshDerivedDataMaintenanceError("MESH 分析数据库自动修复任务启动失败") from exc
        maintenance.set_repair_task(site_id, task_id)
        snapshot = self.task_service.repository(site_id).get(task_id)
        if snapshot is None:
            raise MeshDerivedDataMaintenanceError("MESH 分析数据库自动修复任务未进入任务中心")
        return RailTransitTaskDTO(
            task_id=snapshot.task_id,
            status=snapshot.status.value,
            action=self.TASK_TYPE,
            message=snapshot.message,
            error_message=snapshot.error_message,
        )


__all__ = ["MeshDerivedDataRepairCoordinator"]
