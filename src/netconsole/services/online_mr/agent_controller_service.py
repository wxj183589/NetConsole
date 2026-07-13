from __future__ import annotations

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_agent import (
    OnlineMrAgentPackageInfo,
    OnlineMrAgentPingResponse,
    OnlineMrAgentSystemStatus,
    OnlineMrAgentToolsStatus,
)
from netconsole.services.online_mr.agent_download_service import (
    OnlineMrAgentDownloadImportResult,
    OnlineMrAgentDownloadService,
)
from netconsole.services.online_mr.agent_http_client import OnlineMrAgentHttpClient


class OnlineMrAgentControllerService:
    """手工查询、下载和导入 Agent 采集包；不提供远程任务控制。"""

    def __init__(
        self,
        paths: PathResolver,
        client: OnlineMrAgentHttpClient,
        *,
        download_service: OnlineMrAgentDownloadService | None = None,
    ) -> None:
        self.client = client
        self.download_service = download_service or OnlineMrAgentDownloadService(
            paths, client
        )

    async def ping_agent(self) -> OnlineMrAgentPingResponse:
        return await self.client.ping()

    async def get_agent_status(self) -> OnlineMrAgentSystemStatus:
        return await self.client.get_status()

    async def get_agent_tools(self) -> OnlineMrAgentToolsStatus:
        return await self.client.get_tools_status()

    async def list_agent_packages(self) -> tuple[OnlineMrAgentPackageInfo, ...]:
        return await self.client.list_packages()

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
    ) -> OnlineMrAgentDownloadImportResult:
        return await self.download_service.download_and_import_package(
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
        )


__all__ = ["OnlineMrAgentControllerService"]
