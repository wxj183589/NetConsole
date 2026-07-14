from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from pydantic import SecretStr

from netconsole.core.paths import PathResolver
from netconsole.models.agent import AgentAuthenticationType
from netconsole.models.online_mr_agent import (
    OnlineMrAgentConnectionConfig,
    OnlineMrAgentConnectionResult,
    OnlineMrAgentDeviceMatchStatus,
    OnlineMrAgentPackageInfo,
    OnlineMrAgentPackageSyncResult,
    OnlineMrAgentPingResponse,
    OnlineMrAgentSyncedPackage,
    OnlineMrAgentSystemStatus,
    OnlineMrAgentStartRequest,
    OnlineMrAgentTaskStatusResponse,
    OnlineMrAgentToolsStatus,
)
from netconsole.services.agent.controller import AgentControllerService
from netconsole.services.online_mr.agent_download_service import (
    OnlineMrAgentDownloadImportResult,
    OnlineMrAgentDownloadService,
)
from netconsole.services.online_mr.agent_http_client import (
    OnlineMrAgentClientError,
    OnlineMrAgentHttpClient,
)
from netconsole.services.online_mr.agent_sync_service import (
    OnlineMrAgentDeviceResolver,
    OnlineMrAgentImportStatusResolver,
)
from netconsole.services.online_mr.errors import (
    OnlineMrApplicationError,
    OnlineMrApplicationErrorCode,
)


class OnlineMrAgentControllerService:
    """从已配置 Profile 建立 Online MR Agent 控制与包导入边界。"""

    def __init__(
        self,
        paths: PathResolver,
        client: OnlineMrAgentHttpClient | None = None,
        *,
        download_service: OnlineMrAgentDownloadService | None = None,
        profile_controller: AgentControllerService | None = None,
        device_resolver: OnlineMrAgentDeviceResolver | None = None,
        import_status_resolver: OnlineMrAgentImportStatusResolver | None = None,
    ) -> None:
        self.paths = paths
        self.client = client
        self.download_service = download_service
        self.profile_controller = profile_controller
        self.device_resolver = device_resolver or OnlineMrAgentDeviceResolver(paths)
        self.import_status_resolver = import_status_resolver or OnlineMrAgentImportStatusResolver(paths)

    def list_profiles(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._profiles().list_agents())

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        return self._profiles().get_agent(profile_id)

    async def test_connection(self, profile_id: str = "") -> OnlineMrAgentConnectionResult:
        client = self._client(profile_id)
        ping, status, tools = await asyncio.gather(
            client.ping(), client.get_status(), client.get_tools_status()
        )
        return OnlineMrAgentConnectionResult(
            profile_id=profile_id,
            ping=ping,
            agent_status=status,
            tools=tools,
        )

    async def ping_agent(self, profile_id: str = "") -> OnlineMrAgentPingResponse:
        return await self._client(profile_id).ping()

    async def get_agent_status(self, profile_id: str = "") -> OnlineMrAgentSystemStatus:
        return await self._client(profile_id).get_status()

    async def get_agent_tools(self, profile_id: str = "") -> OnlineMrAgentToolsStatus:
        return await self._client(profile_id).get_tools_status()

    async def start_collection(
        self, profile_id: str, request: OnlineMrAgentStartRequest
    ) -> OnlineMrAgentTaskStatusResponse:
        return await self._client(profile_id).start_collection(request)

    async def get_task(
        self, profile_id: str, task_id: str
    ) -> OnlineMrAgentTaskStatusResponse:
        return await self._client(profile_id).get_task(task_id)

    async def stop_collection(
        self, profile_id: str, task_id: str
    ) -> OnlineMrAgentTaskStatusResponse:
        return await self._client(profile_id).stop_collection(task_id)

    async def list_agent_packages(self, profile_id: str = "") -> tuple[OnlineMrAgentPackageInfo, ...]:
        return await self._client(profile_id).list_packages()

    async def list_remote_packages(
        self, *, site_id: str, profile_id: str = ""
    ) -> tuple[OnlineMrAgentSyncedPackage, ...]:
        return (await self.sync_agent_packages(site_id=site_id, profile_id=profile_id)).packages

    async def sync_agent_packages(
        self, *, site_id: str, profile_id: str = ""
    ) -> OnlineMrAgentPackageSyncResult:
        client = self._client(profile_id)
        ping, status, tools, packages = await asyncio.gather(
            client.ping(),
            client.get_status(),
            client.get_tools_status(),
            client.list_packages(),
        )
        synced: list[OnlineMrAgentSyncedPackage] = []
        for package in packages:
            task = None
            if package.task_type == "mr_realtime_collect" and package.task_id:
                try:
                    task = await client.get_task(package.task_id)
                except OnlineMrAgentClientError:
                    task = None
            params = task.params if task is not None else {}
            target = _mapping(params.get("target"))
            session = _mapping(params.get("session"))
            source_host = _text(target.get("host"))
            session_id = package.session_id or (task.task_id if task else package.task_id)
            resolution = await asyncio.to_thread(
                self.device_resolver.resolve_device_by_ip, site_id, source_host
            )
            selected_package = package.model_copy(update={"session_id": session_id})
            imported = await asyncio.to_thread(
                self.import_status_resolver.resolve,
                site_id,
                selected_package,
                session_id=session_id,
                agent_id=status.agent_id,
            )
            candidate = resolution.candidate
            synced.append(
                OnlineMrAgentSyncedPackage(
                    package_id=package.package_id,
                    file_name=package.file_name or (f"{package.package_id}.zip" if package.package_id else ""),
                    task_id=package.task_id,
                    session_id=session_id,
                    task_type=package.task_type,
                    status=package.status or (task.status.value if task else ""),
                    size=package.size,
                    created_at=package.created_at or package.end_time or package.start_time,
                    start_time=package.start_time,
                    end_time=package.end_time,
                    source_device_id=_text(session.get("device_id") or target.get("id")),
                    source_device_name=_text(session.get("device_name") or target.get("name")),
                    source_host=source_host,
                    candidate_local_device=candidate,
                    candidate_local_devices=resolution.candidates,
                    candidate_match_method=(
                        "ip_match"
                        if resolution.status is OnlineMrAgentDeviceMatchStatus.MATCHED
                        else resolution.status.value
                    ),
                    import_status=imported.status,
                    resolution_code=resolution.error_code,
                    resolution_message=resolution.message,
                )
            )
        return OnlineMrAgentPackageSyncResult(
            profile_id=profile_id,
            ping=ping,
            agent_status=status,
            tools=tools,
            packages=tuple(synced),
        )

    async def download_import_agent_package(
        self,
        package_id: str,
        *,
        site_id: str,
        site_name: str = "",
        profile_id: str = "",
        device_id: int | str = "",
        device_name: str = "",
        mr_id: str = "",
        mr_name: str = "",
        owner: str = "agent_package_sync",
        identity_match_policy: str = "strict",
        expected_host: str = "",
        allow_identity_override: bool = False,
        auto_resolve_by_ip: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> OnlineMrAgentDownloadImportResult:
        synchronized = await self.sync_agent_packages(site_id=site_id, profile_id=profile_id)
        package = next((item for item in synchronized.packages if item.package_id == package_id), None)
        if package is None:
            return OnlineMrAgentDownloadImportResult(
                False,
                error_code=str(OnlineMrApplicationErrorCode.AGENT_PACKAGE_NOT_READY),
                errors=("Agent 包列表中不存在指定 package_id",),
            )
        if auto_resolve_by_ip:
            candidate = package.candidate_local_device
            if candidate is None:
                code = package.resolution_code or str(
                    OnlineMrApplicationErrorCode.AGENT_IMPORT_NEEDS_MANUAL_RESOLUTION
                )
                return OnlineMrAgentDownloadImportResult(
                    False,
                    error_code=code,
                    errors=(package.resolution_message or "需要手工指定本地设备身份",),
                )
            device_id = candidate.device_id
            device_name = candidate.device_name
            mr_id = candidate.mr_id
            mr_name = candidate.mr_name
            expected_host = candidate.host
            identity_match_policy = "ip_match"
        if not all((_text(device_id), _text(device_name), _text(mr_name))):
            return OnlineMrAgentDownloadImportResult(
                False,
                error_code=str(OnlineMrApplicationErrorCode.AGENT_IMPORT_NEEDS_MANUAL_RESOLUTION),
                errors=("需要手工指定本地设备身份",),
            )
        return await self.download_import_package(
            package_id,
            site_id=site_id,
            site_name=site_name or site_id,
            device_id=device_id,
            device_name=device_name,
            mr_id=mr_id,
            mr_name=mr_name,
            owner=owner,
            expected_session_id=package.session_id or None,
            agent_task_id=package.task_id or None,
            agent_id=synchronized.agent_status.agent_id,
            identity_match_policy=identity_match_policy,
            expected_host=expected_host,
            allow_identity_override=allow_identity_override,
            source_package_id=package.package_id,
            profile_id=profile_id,
            cancel_check=cancel_check,
        )

    async def download_import_package(
        self,
        package_id: str,
        *,
        site_id: str,
        site_name: str = "",
        device_id: int | str,
        device_name: str,
        mr_id: str = "",
        mr_name: str,
        owner: str = "manual_agent_import",
        expected_session_id: str | None = None,
        controller_task_id: str | None = None,
        agent_task_id: str | None = None,
        agent_id: str = "",
        identity_match_policy: str = "strict",
        expected_host: str = "",
        allow_identity_override: bool = False,
        source_package_id: str = "",
        profile_id: str = "",
        cancel_check: Callable[[], bool] | None = None,
    ) -> OnlineMrAgentDownloadImportResult:
        client = self._client(profile_id)
        download_service = self._download_service(client)
        return await download_service.download_and_import_package(
            package_id,
            site_id=site_id,
            site_name=site_name,
            device_id=device_id,
            device_name=device_name,
            mr_id=mr_id,
            mr_name=mr_name,
            owner=owner,
            expected_session_id=expected_session_id,
            controller_task_id=controller_task_id,
            agent_task_id=agent_task_id,
            agent_id=agent_id,
            identity_match_policy=identity_match_policy,
            expected_host=expected_host,
            allow_identity_override=allow_identity_override,
            source_package_id=source_package_id or package_id,
            cancel_check=cancel_check,
        )

    def _download_service(self, client: OnlineMrAgentHttpClient) -> OnlineMrAgentDownloadService:
        if self.download_service is not None and client is self.client:
            return self.download_service
        return OnlineMrAgentDownloadService(self.paths, client)

    def _client(self, profile_id: str) -> OnlineMrAgentHttpClient:
        if not profile_id:
            if self.client is None:
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.AGENT_UNREACHABLE,
                    "未指定 Agent Profile",
                )
            return self.client
        controller = self._profiles()
        config = controller.repository.get(profile_id)
        if config is None:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_UNREACHABLE,
                "Agent Profile 不存在",
            )
        if not config.enabled:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_UNREACHABLE,
                "Agent Profile 已禁用",
            )
        token = ""
        if config.authentication_type is AgentAuthenticationType.TOKEN:
            token = controller.credentials.get(config.credential_reference) or ""
            if not token:
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.AGENT_AUTH_FAILED,
                    "Agent Token 未加载，请重新编辑认证配置",
                )
        return OnlineMrAgentHttpClient(
            OnlineMrAgentConnectionConfig(
                base_url=config.base_url,
                token=SecretStr(token),
            )
        )

    def _profiles(self) -> AgentControllerService:
        if self.profile_controller is None:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_UNREACHABLE,
                "未配置 Agent Profile Controller",
            )
        return self.profile_controller


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


__all__ = ["OnlineMrAgentControllerService"]
