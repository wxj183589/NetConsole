from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

from netconsole.core.paths import PathResolver
from netconsole.models.api.online_mr import OnlineMrOperationSnapshotDTO
from netconsole.models.api.online_mr_agent_control import (
    OnlineMrAgentCapabilitiesDTO,
    OnlineMrAgentProfileDTO,
    OnlineMrAgentReadinessDTO,
    OnlineMrAgentWebOperationDTO,
    OnlineMrAgentWebStartRequestDTO,
    OnlineMrAgentWebStatusDTO,
)
from netconsole.models.api.online_mr_control import OnlineMrWebStartRequestDTO
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrPhase,
)
from netconsole.services.online_mr.agent_controller_service import (
    OnlineMrAgentControllerService,
)
from netconsole.services.online_mr.agent_http_client import OnlineMrAgentClientError
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.errors import (
    OnlineMrApplicationError,
    OnlineMrApplicationErrorCode,
    OnlineMrQueryError,
    OnlineMrWebControlError,
    OnlineMrWebControlErrorCode,
)
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.online_mr.web_control_service import (
    ONLINE_MR_ACTIVE_MAPPING_STATES,
    ONLINE_MR_WEB_START_LOCK,
    OnlineMrWebControlService,
)
from netconsole.services.agent.controller import AgentControllerError


class OnlineMrAgentWebControlService:
    """把 Desktop WebHost 的白名单请求接入既有 Agent executor。"""

    def __init__(
        self,
        paths: PathResolver,
        application_service: OnlineMrApplicationService | None,
        local_control: OnlineMrWebControlService,
        query_service: OnlineMrQueryService,
        agent_controller: OnlineMrAgentControllerService,
        *,
        enabled: bool = False,
    ) -> None:
        self.paths = paths
        self._application_service = application_service
        self.local_control = local_control
        self.query_service = query_service
        self.agent_controller = agent_controller
        self.enabled = bool(enabled)

    def capabilities(self, site_id: str) -> OnlineMrAgentCapabilitiesDTO:
        return OnlineMrAgentCapabilitiesDTO(
            agent_executor_enabled=self._is_enabled(),
            site_id=site_id,
            profiles=[
                self._profile_dto(item)
                for item in self.agent_controller.list_profiles()
            ],
        )

    def profiles(self) -> list[OnlineMrAgentProfileDTO]:
        return [
            self._profile_dto(item) for item in self.agent_controller.list_profiles()
        ]

    def readiness(self, profile_id: str) -> OnlineMrAgentReadinessDTO:
        profile = self._profile(profile_id)
        if not self._is_enabled():
            return OnlineMrAgentReadinessDTO(
                profile_id=profile_id,
                ready=False,
                reachable=False,
                authenticated=bool(profile.get("has_credential"))
                or str(profile.get("authentication_type")) == "none",
                error_code=OnlineMrApplicationErrorCode.AGENT_EXECUTOR_DISABLED.value,
                error_summary="Online MR Agent 执行器未启用",
            )
        if not bool(profile.get("enabled")):
            return OnlineMrAgentReadinessDTO(
                profile_id=profile_id,
                ready=False,
                reachable=False,
                authenticated=False,
                error_code=OnlineMrApplicationErrorCode.AGENT_UNREACHABLE.value,
                error_summary="Agent Profile 已禁用",
            )
        try:
            result = asyncio.run(self.agent_controller.test_connection(profile_id))
        except (OnlineMrAgentClientError, OnlineMrApplicationError) as exc:
            code = str(
                getattr(
                    exc, "code", OnlineMrApplicationErrorCode.AGENT_UNREACHABLE.value
                )
            )
            return OnlineMrAgentReadinessDTO(
                profile_id=profile_id,
                ready=False,
                reachable=code != OnlineMrApplicationErrorCode.AGENT_UNREACHABLE.value,
                authenticated=code
                != OnlineMrApplicationErrorCode.AGENT_AUTH_FAILED.value,
                error_code=code,
                error_summary=self._safe_connection_error(code),
            )
        except Exception:
            return OnlineMrAgentReadinessDTO(
                profile_id=profile_id,
                ready=False,
                reachable=False,
                authenticated=False,
                error_code=OnlineMrApplicationErrorCode.AGENT_UNREACHABLE.value,
                error_summary="Agent 当前不可达",
            )
        tools = result.tools
        return OnlineMrAgentReadinessDTO(
            profile_id=profile_id,
            ready=tools.mr_collector.ready,
            reachable=True,
            authenticated=True,
            agent_id=result.agent_status.agent_id,
            version=result.agent_status.version,
            mr_collector_ready=tools.mr_collector.ready,
            fping_ready=tools.fping.ready,
            iperf3_ready=tools.iperf3.ready,
            error_code=""
            if tools.mr_collector.ready
            else OnlineMrApplicationErrorCode.AGENT_MR_COLLECTOR_MISSING.value,
            error_summary="" if tools.mr_collector.ready else "Agent MR 采集器不可用",
        )

    def status(self, site_id: str) -> OnlineMrAgentWebStatusDTO:
        operations = (
            [
                item
                for item in self.application_service.list_operations(
                    site_id=site_id, limit=50
                )
                if item.executor_kind is OnlineMrExecutorKind.AGENT
            ]
            if self._is_enabled()
            else []
        )
        return OnlineMrAgentWebStatusDTO(
            agent_executor_enabled=self._is_enabled(),
            site_id=site_id,
            operations=[self._operation_dto(item) for item in operations],
        )

    def get_operation(
        self, operation_id: str, *, site_id: str | None = None
    ) -> OnlineMrAgentWebOperationDTO:
        self._require_enabled()
        try:
            operation = self.application_service.get_operation(
                operation_id, site_id=site_id
            )
        except OnlineMrApplicationError as exc:
            raise OnlineMrWebControlError(
                exc.code, exc.message, status_code=404
            ) from exc
        self._require_agent_operation(operation)
        return self._operation_dto(operation)

    def start(
        self,
        request: OnlineMrAgentWebStartRequestDTO,
        *,
        current_site_id: str,
    ) -> OnlineMrAgentWebOperationDTO:
        self._require_enabled()
        if request.site_id != current_site_id:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.INVALID_REQUEST,
                "启动局点必须与主程序当前局点一致",
                status_code=422,
            )
        profile = self._profile(request.agent_profile_id)
        if not bool(profile.get("enabled")):
            raise OnlineMrWebControlError(
                OnlineMrApplicationErrorCode.AGENT_UNREACHABLE,
                "Agent Profile 已禁用",
                status_code=409,
            )
        with ONLINE_MR_WEB_START_LOCK:
            existing = self._active_for_device(current_site_id, request.device_id)
            if (
                existing is not None
                and existing.mr_id == request.mr_id
                and existing.agent_profile_id == request.agent_profile_id
            ):
                return self._operation_dto(existing)
            local_payload = OnlineMrWebStartRequestDTO.model_validate(
                {
                    **request.model_dump(exclude={"agent_profile_id", "executor"}),
                    "executor": "LOCAL",
                }
            )
            start_request = self.local_control.build_start_request(
                local_payload,
                executor_kind=OnlineMrExecutorKind.AGENT,
                agent_id=request.agent_profile_id,
                owner="web_agent",
            )
            try:
                operation = self.application_service.start_collection(start_request)
            except OnlineMrApplicationError as exc:
                raise OnlineMrWebControlError(
                    exc.code, exc.message, status_code=409
                ) from exc
        return self._operation_dto(operation)

    def stop(self, operation_id: str, *, site_id: str | None = None) -> OnlineMrAgentWebOperationDTO:
        self._require_enabled()
        with ONLINE_MR_WEB_START_LOCK:
            try:
                current = self.application_service.get_operation(
                    operation_id, site_id=site_id
                )
            except OnlineMrApplicationError as exc:
                raise OnlineMrWebControlError(
                    exc.code, exc.message, status_code=404
                ) from exc
            self._require_agent_operation(current)
            try:
                operation = self.application_service.stop_operation(
                    operation_id,
                    site_id=site_id,
                    stop_reason="web_agent_user_stop",
                )
            except OnlineMrApplicationError as exc:
                status_code = 404 if "NOT_FOUND" in str(exc.code) else 409
                raise OnlineMrWebControlError(
                    exc.code, exc.message, status_code=status_code
                ) from exc
        return self._operation_dto(operation)

    def _active_for_device(
        self, site_id: str, device_id: int | str
    ) -> OnlineMrOperationSnapshotDTO | None:
        rows = self.application_service.list_operations(
            site_id=site_id,
            states=ONLINE_MR_ACTIVE_MAPPING_STATES,
            device_id=device_id,
            limit=10,
        )
        return next(
            (
                item
                for item in rows
                if item.executor_kind is OnlineMrExecutorKind.AGENT
                and item.phase is not OnlineMrPhase.TERMINAL
            ),
            None,
        )

    def _operation_dto(
        self, operation: OnlineMrOperationSnapshotDTO
    ) -> OnlineMrAgentWebOperationDTO:
        self._require_agent_operation(operation)
        data_integrity = "unknown"
        if operation.session_id:
            try:
                data_integrity = str(
                    self.query_service.get_session(
                        operation.site_id, operation.session_id
                    ).data_integrity
                )
            except OnlineMrQueryError:
                pass
        package_status = (
            "imported"
            if operation.session_id
            else "ready"
            if operation.remote_package_id
            else "waiting"
            if operation.phase is OnlineMrPhase.FINALIZING
            else "failed"
            if operation.phase is OnlineMrPhase.TERMINAL and operation.error_code
            else "pending"
        )
        return OnlineMrAgentWebOperationDTO(
            operation_id=operation.controller_task_id,
            controller_task_id=operation.controller_task_id,
            session_id=operation.session_id,
            site_id=operation.site_id,
            device_id=operation.device_id,
            device_name=operation.device_name,
            mr_id=operation.mr_id,
            mr_name=operation.mr_name,
            agent_id=operation.agent_id,
            agent_profile_id=operation.agent_profile_id,
            agent_task_id=operation.agent_task_id,
            remote_session_id=operation.remote_session_id,
            remote_package_id=operation.remote_package_id,
            state=self._web_state(operation),
            phase=operation.phase.value,
            remote_status=operation.last_remote_status,
            task_status=operation.task_status.value if operation.task_status else None,
            mapping_status=operation.mapping_state.value,
            started_at=operation.started_at,
            updated_at=operation.updated_at,
            deadline_at=operation.deadline_at,
            duration_minutes=operation.duration_minutes,
            consecutive_status_failures=operation.consecutive_status_failures,
            package_status=package_status,
            download_status="completed"
            if operation.session_id
            else "in_progress"
            if operation.remote_package_id
            else "pending",
            import_status="completed"
            if operation.session_id
            else "in_progress"
            if operation.remote_package_id
            else "pending",
            data_integrity=data_integrity,
            error_code=operation.error_code,
            error_summary=self._safe_error_summary(
                operation.error_summary or operation.error_message
            ),
        )

    @staticmethod
    def _web_state(operation: OnlineMrOperationSnapshotDTO) -> str:
        if (
            operation.error_code
            == OnlineMrApplicationErrorCode.AGENT_REMOTE_STATUS_UNKNOWN.value
        ):
            return "remote_unknown"
        if operation.consecutive_status_failures:
            return "remote_status_degraded"
        if operation.phase in {
            OnlineMrPhase.VALIDATING,
            OnlineMrPhase.PREPARING_TASK,
            OnlineMrPhase.PREPARING_SESSION,
        }:
            return "preparing"
        if operation.phase in {
            OnlineMrPhase.CONNECTING,
            OnlineMrPhase.STARTING_COLLECTION,
        }:
            return "starting"
        if operation.phase is OnlineMrPhase.COLLECTING:
            return "running"
        if operation.phase in {
            OnlineMrPhase.STOPPING_TRAFFIC,
            OnlineMrPhase.STOPPING_COLLECTION,
        }:
            return "stopping"
        if operation.phase is OnlineMrPhase.FINALIZING:
            return "importing" if operation.remote_package_id else "waiting_package"
        if operation.error_code:
            return "failed"
        return "stopped"

    @staticmethod
    def _profile_dto(profile: dict[str, object]) -> OnlineMrAgentProfileDTO:
        return OnlineMrAgentProfileDTO(
            profile_id=str(profile.get("agent_id") or ""),
            name=str(profile.get("name") or ""),
            address_display=OnlineMrAgentWebControlService._masked_address(
                str(profile.get("base_url") or "")
            ),
            enabled=bool(profile.get("enabled")),
            status=str(profile.get("status") or "UNKNOWN"),
            has_credential=bool(profile.get("has_credential")),
        )

    @staticmethod
    def _masked_address(value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme or 'http'}://***{port}"
        except ValueError:
            return "***"

    def _profile(self, profile_id: str) -> dict[str, object]:
        try:
            return dict(self.agent_controller.get_profile(profile_id))
        except (AgentControllerError, OnlineMrApplicationError) as exc:
            raise OnlineMrWebControlError(
                str(
                    getattr(
                        exc,
                        "code",
                        OnlineMrApplicationErrorCode.AGENT_UNREACHABLE.value,
                    )
                ),
                "Agent Profile 不存在",
                status_code=404,
            ) from exc

    def _is_enabled(self) -> bool:
        executor = (
            self._application_service.agent_executor
            if self._application_service is not None
            else None
        )
        return bool(self.enabled and executor is not None and executor.settings.enabled)

    def _require_enabled(self) -> None:
        if not self._is_enabled():
            raise OnlineMrWebControlError(
                OnlineMrApplicationErrorCode.AGENT_EXECUTOR_DISABLED,
                "Online MR Agent 执行器默认关闭",
                status_code=403,
            )

    @property
    def application_service(self) -> OnlineMrApplicationService:
        if self._application_service is None:
            self._require_enabled()
        assert self._application_service is not None
        return self._application_service

    @staticmethod
    def _require_agent_operation(operation: OnlineMrOperationSnapshotDTO) -> None:
        if operation.executor_kind is not OnlineMrExecutorKind.AGENT:
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.LOCAL_ONLY,
                "Agent 控制入口只允许 AGENT operation",
                status_code=409,
            )

    @staticmethod
    def _safe_connection_error(code: str) -> str:
        return {
            OnlineMrApplicationErrorCode.AGENT_AUTH_FAILED.value: "Agent 认证失败",
            OnlineMrApplicationErrorCode.AGENT_VERSION_UNSUPPORTED.value: "Agent 版本不受支持",
            OnlineMrApplicationErrorCode.AGENT_MR_COLLECTOR_MISSING.value: "Agent MR 采集器不可用",
        }.get(code, "Agent 当前不可达")

    @staticmethod
    def _safe_error_summary(value: object) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ")
        text = re.sub(r"(?i)https?://[^\s,;]+", "<redacted>", text)
        text = re.sub(r"(?i)(?:[a-z]:\\|/)[^\s,;]+", "<path>", text)
        text = re.sub(
            r"(?i)((?:token|password)\s*[:=]\s*)[^\s,;]+", r"\1<redacted>", text
        )
        return text[:500]


__all__ = ["OnlineMrAgentWebControlService"]
