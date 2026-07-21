from __future__ import annotations

import ipaddress
import re
import threading

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.online_mr import OnlineMrOperationSnapshotDTO
from netconsole.models.api.online_mr_control import (
    OnlineMrWebControlStatusDTO,
    OnlineMrWebOperationDTO,
    OnlineMrWebStartRequestDTO,
)
from netconsole.models.device import Device
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrStartRequest,
)
from netconsole.models.online_mr_models import (
    FpingConfig,
    IperfTrafficConfig,
    OnlineMrConnectionConfig,
    OnlineMrIntervals,
    OnlineMrRadioConfig,
    OnlineMrTaskToggles,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.errors import (
    OnlineMrApplicationError,
    OnlineMrQueryError,
    OnlineMrWebControlError,
    OnlineMrWebControlErrorCode,
)
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.online_mr.real_device_test_policy import (
    OnlineMrRealDeviceTestPolicy,
    REAL_DEVICE_FPING_INTERVAL_MS,
    REAL_DEVICE_FPING_TIMEOUT_MS,
    REAL_DEVICE_IPERF_BANDWIDTH,
    REAL_DEVICE_IPERF_SERVER,
)
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


ONLINE_MR_ACTIVE_MAPPING_STATES = {
    OnlineMrMappingState.PENDING_SESSION,
    OnlineMrMappingState.LINKED,
}
ONLINE_MR_WEB_START_LOCK = threading.RLock()


class OnlineMrWebControlService:
    """把受控 Web 请求转换为既有 LOCAL Online MR ApplicationService 调用。"""

    def __init__(
        self,
        paths: PathResolver,
        application_service: OnlineMrApplicationService | None,
        base_query: RailTransitBaseDataQueryService,
        query_service: OnlineMrQueryService,
        *,
        enabled: bool = False,
        real_device_policy: OnlineMrRealDeviceTestPolicy | None = None,
    ) -> None:
        self.paths = paths
        self._application_service = application_service
        self.base_query = base_query
        self.query_service = query_service
        self.enabled = bool(enabled)
        self.real_device_policy = real_device_policy or OnlineMrRealDeviceTestPolicy.from_environment()

    def status(self, site_id: str) -> OnlineMrWebControlStatusDTO:
        operations = (
            [
                item
                for item in self.application_service.list_operations(site_id=site_id, limit=50)
                if item.executor_kind is OnlineMrExecutorKind.LOCAL and item.phase is not OnlineMrPhase.TERMINAL
            ]
            if self.enabled
            else []
        )
        return OnlineMrWebControlStatusDTO(
            enabled=self.enabled,
            site_id=site_id,
            operations=[self._operation_dto(item) for item in operations],
            real_device_test=self.real_device_policy.enabled,
            safety_constraints=self.real_device_policy.constraints(),
        )

    def get_operation(self, operation_id: str, *, site_id: str | None = None) -> OnlineMrWebOperationDTO:
        self._require_enabled()
        try:
            operation = self.application_service.get_operation(operation_id, site_id=site_id)
        except OnlineMrApplicationError as exc:
            raise OnlineMrWebControlError(exc.code, exc.message, status_code=404) from exc
        if operation.executor_kind is not OnlineMrExecutorKind.LOCAL:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.LOCAL_ONLY,
                "Web Online MR 控制仅支持本机 LOCAL operation",
                status_code=409,
            )
        return self._operation_dto(operation)

    def start(self, request: OnlineMrWebStartRequestDTO, *, current_site_id: str) -> OnlineMrWebOperationDTO:
        self._require_enabled()
        if request.executor != "LOCAL":
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.LOCAL_ONLY,
                "Web Online MR 控制仅支持本机 LOCAL 执行端",
                status_code=422,
            )
        if request.site_id != current_site_id:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.INVALID_REQUEST,
                "启动局点必须与主程序当前局点一致",
                status_code=422,
            )
        with ONLINE_MR_WEB_START_LOCK:
            existing = self._active_for_site(current_site_id)
            if existing is not None:
                if (
                    existing.executor_kind is OnlineMrExecutorKind.LOCAL
                    and str(existing.device_id) == str(request.device_id)
                ):
                    return self._operation_dto(existing)
                raise OnlineMrWebControlError(
                    OnlineMrWebControlErrorCode.ALREADY_RUNNING,
                    "当前局点已有实时采集任务，请先正常停止后再启动新任务",
                    status_code=409,
                )
            start_request = self.build_start_request(request)
            try:
                return self._operation_dto(self.application_service.start_local_collection(start_request))
            except OnlineMrApplicationError as exc:
                raise OnlineMrWebControlError(exc.code, exc.message, status_code=409) from exc

    def stop(self, operation_id: str, *, site_id: str | None = None) -> OnlineMrWebOperationDTO:
        self._require_enabled()
        with ONLINE_MR_WEB_START_LOCK:
            try:
                operation = self.application_service.stop_operation(
                    operation_id,
                    site_id=site_id,
                    stop_reason="web_user_stop",
                )
            except OnlineMrApplicationError as exc:
                status_code = 404 if "NOT_FOUND" in str(exc.code) else 409
                raise OnlineMrWebControlError(
                    OnlineMrWebControlErrorCode.STOP_FAILED,
                    exc.message,
                    status_code=status_code,
                ) from exc
        return self._operation_dto(operation)

    def force_stop(self, operation_id: str, *, site_id: str | None = None) -> OnlineMrWebOperationDTO:
        self._require_enabled()
        with ONLINE_MR_WEB_START_LOCK:
            try:
                operation = self.application_service.force_stop_operation(
                    operation_id,
                    site_id=site_id,
                    stop_reason="web_user_force_stop",
                )
            except OnlineMrApplicationError as exc:
                status_code = 404 if "NOT_FOUND" in str(exc.code) else 409
                raise OnlineMrWebControlError(
                    OnlineMrWebControlErrorCode.STOP_FAILED,
                    exc.message,
                    status_code=status_code,
                ) from exc
        return self._operation_dto(operation)

    def recover(self, site_id: str) -> list[OnlineMrWebOperationDTO]:
        self._require_enabled()
        try:
            operations = self.application_service.recover_mappings(site_id=site_id)
        except OnlineMrApplicationError as exc:
            raise OnlineMrWebControlError(exc.code, exc.message, status_code=409) from exc
        return [
            self._operation_dto(operation)
            for operation in operations
            if operation.executor_kind is OnlineMrExecutorKind.LOCAL
        ]

    def build_start_request(
        self,
        request: OnlineMrWebStartRequestDTO,
        *,
        executor_kind: OnlineMrExecutorKind = OnlineMrExecutorKind.LOCAL,
        agent_id: str = "",
        owner: str = "web_local",
    ) -> OnlineMrStartRequest:
        detail = self.base_query.get_mr(request.site_id, request.mr_id)
        if detail is None or detail.mr.device_id is None or str(detail.mr.device_id) != str(request.device_id):
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.DEVICE_NOT_FOUND,
                "所选 MR 不存在或未绑定正式设备资料",
                status_code=404,
            )
        self.real_device_policy.require_allowed_target(
            site_id=request.site_id,
            train_no=detail.mr.train_no,
        )
        device = self._device(request.site_id, detail.mr.device_id)
        protocol, port, username, password = self._connection_fields(device)
        host = str(device.primary_address or "").strip()
        if not host or not protocol or not username or not password:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.CREDENTIAL_UNAVAILABLE,
                "所选 MR 缺少可用的受控连接凭据",
                status_code=409,
            )
        real_test = self.real_device_policy.enabled
        fping_enabled = request.fping.enabled or real_test
        iperf_enabled = request.iperf.enabled or real_test
        fping_target = (
            detail.mr.management_ip.strip()
            if real_test
            else request.fping.target.strip() or detail.mr.management_ip.strip()
        )
        if fping_enabled:
            self._validated_ip(fping_target, "fping 目标")
        iperf_server = REAL_DEVICE_IPERF_SERVER if real_test else request.iperf.server_ip.strip()
        if iperf_enabled:
            self._validated_ip(iperf_server, "iPerf 服务端")
        config = OnlineMrConnectionConfig(
            site=request.site_id,
            mr_id=detail.mr.id,
            mr_name=detail.mr.name,
            safe_mr_name=self._safe_folder_name(detail.mr.name, detail.mr.device_id),
            device_id=detail.mr.device_id,
            device_name=device.name,
            host=host,
            protocol=protocol,
            port=port,
            username=username,
            password=password,
            intervals=OnlineMrIntervals(
                mesh_link=request.intervals.mesh_link,
                channel_busy=request.intervals.channel_busy,
                ap_radio_statistics=request.intervals.ap_radio_statistics,
                switch_history=request.intervals.switch_history,
                interface_rate=request.intervals.interface_rate,
                fping_interval_ms=(
                    REAL_DEVICE_FPING_INTERVAL_MS if real_test else request.fping.interval_ms
                ),
                wireless_status=request.intervals.wireless_status,
            ),
            tasks=OnlineMrTaskToggles(
                mesh_link=request.items.mesh_link,
                channel_busy=request.items.channel_busy,
                ap_radio_statistics=request.items.ap_radio_statistics,
                switch_history=request.items.switch_history,
                interface_rate=request.items.interface_rate,
                wireless_status=request.items.wireless_status,
            ),
            radio=OnlineMrRadioConfig(**request.radio.model_dump()),
            fping=FpingConfig(
                enabled=fping_enabled,
                target=fping_target if fping_enabled else "",
                preset_key="real_device_test" if real_test else "web_local",
                preset_name="真实设备保护模式" if real_test else "Web 本地受控",
                packet_size=request.fping.packet_size,
                interval_ms=REAL_DEVICE_FPING_INTERVAL_MS if real_test else request.fping.interval_ms,
                loss_threshold_ms=REAL_DEVICE_FPING_TIMEOUT_MS if real_test else request.fping.timeout_ms,
                loss_warn_percent=request.fping.loss_warn_percent,
                latency_warn_ms=request.fping.latency_warn_ms,
            ),
            iperf=IperfTrafficConfig(
                enabled=iperf_enabled,
                server_ip=iperf_server,
                port=5201 if real_test else request.iperf.port,
                preset_key="real_device_test" if real_test else "web_local",
                preset_name="真实设备保护模式" if real_test else "Web 本地受控",
                protocol="TCP" if real_test else request.iperf.protocol,
                direction="upload" if real_test else "download" if request.iperf.reverse else "upload",
                parallel=1 if real_test else request.iperf.parallel,
                interval_seconds=request.iperf.interval_seconds,
                tcp_report_threshold_mbps=request.iperf.tcp_report_threshold_mbps,
                target_bandwidth=REAL_DEVICE_IPERF_BANDWIDTH if real_test else None,
                tcp_pacing_enabled=real_test,
                tcp_pacing_mbps=2.0 if real_test else None,
                udp_bitrate_mbps=None if real_test else request.iperf.udp_bitrate_mbps,
                follow_collection=True,
            ),
            duration_minutes=request.duration_minutes or None,
        )
        return OnlineMrStartRequest(
            site_id=request.site_id,
            device_id=detail.mr.device_id,
            device_name=device.name,
            mr_name=detail.mr.name,
            config=config,
            executor_kind=executor_kind,
            agent_id=agent_id,
            owner=owner,
        )

    def _active_for_site(self, site_id: str) -> OnlineMrOperationSnapshotDTO | None:
        rows = self.application_service.list_operations(
            site_id=site_id,
            states=ONLINE_MR_ACTIVE_MAPPING_STATES,
            limit=50,
        )
        return next(
            (
                item
                for item in rows
                if item.phase is not OnlineMrPhase.TERMINAL
            ),
            None,
        )

    def current_session_id(self, site_id: str) -> str | None:
        if self._application_service is None:
            return None
        operation = self._active_for_site(site_id)
        return operation.session_id if operation is not None else None

    def _operation_dto(self, operation: OnlineMrOperationSnapshotDTO) -> OnlineMrWebOperationDTO:
        if operation.executor_kind is not OnlineMrExecutorKind.LOCAL:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.LOCAL_ONLY,
                "Web Online MR 控制仅支持本机 LOCAL operation",
                status_code=409,
            )
        task = self.application_service.task_service.repository(operation.site_id).get(operation.controller_task_id)
        collectors = []
        session_status = None
        duration_limit = None
        package_reference = None
        data_integrity = "unknown"
        if operation.session_id:
            try:
                detail = self.query_service.get_session(operation.site_id, operation.session_id)
                session_status = detail.status or None
                duration_limit = self._optional_int(detail.collection_config.get("duration_minutes"))
                package_reference = detail.package_reference
                data_integrity = str(detail.data_integrity)
                collectors = self.query_service.list_collectors(operation.site_id, operation.session_id)
            except OnlineMrQueryError:
                pass
        collector_status = {item.name: item.status for item in collectors}
        warning = bool(operation.error_summary) and not operation.error_code
        package_status = "ready" if package_reference else "unavailable" if operation.phase is OnlineMrPhase.TERMINAL else "pending"
        return OnlineMrWebOperationDTO(
            operation_id=operation.controller_task_id,
            task_id=operation.controller_task_id,
            session_id=operation.session_id,
            site_id=operation.site_id,
            device_id=operation.device_id,
            device_name=operation.device_name,
            mr_id=operation.mr_id,
            mr_name=operation.mr_name,
            owner=task.owner if task else "",
            state=self._web_state(operation, session_status, warning),
            phase=str(operation.phase),
            task_status=str(operation.task_status) if operation.task_status else None,
            session_status=session_status,
            mapping_status=str(operation.mapping_state),
            started_at=operation.started_at,
            updated_at=operation.updated_at,
            duration_minutes=operation.duration_minutes,
            duration_limit=duration_limit,
            collectors=collectors,
            fping_status=collector_status.get("fping_v5", "disabled"),
            iperf_status=collector_status.get("iperf_client", "disabled"),
            package_status=package_status,
            package_path_reference=package_reference,
            error_code=operation.error_code,
            error_summary=operation.error_summary or operation.error_message,
            data_integrity=data_integrity,
        )

    @staticmethod
    def _web_state(operation: OnlineMrOperationSnapshotDTO, session_status: str | None, warning: bool) -> str:
        if operation.phase in {OnlineMrPhase.VALIDATING, OnlineMrPhase.PREPARING_TASK, OnlineMrPhase.PREPARING_SESSION}:
            return "preparing"
        if operation.phase in {OnlineMrPhase.CONNECTING, OnlineMrPhase.STARTING_COLLECTION}:
            return "starting"
        if operation.phase is OnlineMrPhase.COLLECTING:
            return "running"
        if operation.phase in {
            OnlineMrPhase.STOPPING_TRAFFIC,
            OnlineMrPhase.STOPPING_COLLECTION,
            OnlineMrPhase.FINALIZING,
            OnlineMrPhase.PARSING,
            OnlineMrPhase.PACKAGING,
        }:
            return "stopping"
        status = str(session_status or "").upper()
        if operation.force_stopped or status in {"ABORTED", "FORCED_STOPPED"}:
            return "aborted"
        if operation.error_code or status == "FAILED" or str(operation.task_status or "") == "FAILED":
            return "failed"
        return "completed_with_warnings" if warning else "stopped"

    def _device(self, site_id: str, device_id: int) -> Device:
        try:
            return DeviceRepository(Database(self.paths.site_db_path(site_id))).get(int(device_id))
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.DEVICE_NOT_FOUND,
                "所选 MR 对应设备不存在",
                status_code=404,
            ) from exc

    @staticmethod
    def _connection_fields(device: Device) -> tuple[str, int, str, str]:
        if device.ssh_enabled:
            return (
                "SSH",
                int(device.ssh_port or device.port or 22),
                str(device.ssh_username or device.username or "").strip(),
                str(device.ssh_password or device.password or ""),
            )
        if device.telnet_enabled:
            return (
                "Telnet",
                int(device.telnet_port or device.port or 23),
                str(device.telnet_username or device.username or "").strip(),
                str(device.telnet_password or device.password or ""),
            )
        return "", 0, "", ""

    @staticmethod
    def _validated_ip(value: str, label: str) -> str:
        try:
            return str(ipaddress.ip_address(str(value or "").strip()))
        except ValueError as exc:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.INVALID_REQUEST,
                f"{label}必须是有效 IP 地址",
                status_code=422,
            ) from exc

    @staticmethod
    def _safe_folder_name(name: str, device_id: int) -> str:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", str(name or "device")).strip(" ._") or "device"
        return f"{safe}__{device_id}"

    @staticmethod
    def _optional_int(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.CONTROL_DISABLED,
                "Web 本地 Online MR 控制默认关闭",
                status_code=403,
            )

    @property
    def application_service(self) -> OnlineMrApplicationService:
        if self._application_service is None:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.CONTROL_DISABLED,
                "Web 本地 Online MR 控制默认关闭",
                status_code=403,
            )
        return self._application_service


__all__ = ["OnlineMrWebControlService"]
