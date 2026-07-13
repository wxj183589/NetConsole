from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_agent import (
    OnlineMrAgentConnectionConfig,
    OnlineMrAgentPackageInfo,
    OnlineMrAgentPingResponse,
    OnlineMrAgentSystemStatus,
    OnlineMrAgentToolsStatus,
    OnlineMrAgentToolStatus,
)
from netconsole.services.online_mr.agent_controller_service import (
    OnlineMrAgentControllerService,
)
from netconsole.services.online_mr.agent_download_service import (
    OnlineMrAgentDownloadImportResult,
    OnlineMrAgentDownloadService,
)
from netconsole.services.online_mr.agent_http_client import (
    OnlineMrAgentClientError,
    OnlineMrAgentHttpClient,
)
from netconsole.services.online_mr.errors import OnlineMrApplicationErrorCode


class _Client:
    async def ping(self) -> OnlineMrAgentPingResponse:
        return OnlineMrAgentPingResponse(status="ok")

    async def get_status(self) -> OnlineMrAgentSystemStatus:
        return OnlineMrAgentSystemStatus(
            agent_id="agent-a",
            version="v1.0.0",
            os="windows",
            arch="amd64",
        )

    async def get_tools_status(self) -> OnlineMrAgentToolsStatus:
        ready = OnlineMrAgentToolStatus(exists=True, ready=True)
        return OnlineMrAgentToolsStatus(
            mr_collector=ready,
            fping=ready,
            iperf3=ready,
        )

    async def list_packages(self) -> tuple[OnlineMrAgentPackageInfo, ...]:
        return (
            OnlineMrAgentPackageInfo(
                package_id="package-1",
                task_id="task-1",
                task_type="mr_realtime_collect",
            ),
        )


class _DownloadService:
    def __init__(self, result: OnlineMrAgentDownloadImportResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def download_and_import_package(
        self, package_id: str, **options: object
    ) -> OnlineMrAgentDownloadImportResult:
        self.calls.append((package_id, options))
        return self.result


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("site-a")
    return paths


def _service(
    tmp_path: Path,
    result: OnlineMrAgentDownloadImportResult | None = None,
) -> tuple[OnlineMrAgentControllerService, _DownloadService]:
    download = _DownloadService(result or OnlineMrAgentDownloadImportResult(True))
    service = OnlineMrAgentControllerService(
        _paths(tmp_path),
        _Client(),  # type: ignore[arg-type]
        download_service=download,  # type: ignore[arg-type]
    )
    return service, download


def test_controller_queries_typed_agent_state_and_packages(tmp_path: Path) -> None:
    service, _download = _service(tmp_path)

    ping = asyncio.run(service.ping_agent())
    status = asyncio.run(service.get_agent_status())
    tools = asyncio.run(service.get_agent_tools())
    packages = asyncio.run(service.list_agent_packages())

    assert ping.status == "ok"
    assert status.agent_id == "agent-a"
    assert tools.mr_collector.ready
    assert packages[0].package_id == "package-1"


@pytest.mark.parametrize(
    ("result", "attribute"),
    [
        (OnlineMrAgentDownloadImportResult(True, imported=True), "imported"),
        (
            OnlineMrAgentDownloadImportResult(True, already_imported=True),
            "already_imported",
        ),
        (
            OnlineMrAgentDownloadImportResult(
                False,
                conflict=True,
                error_code=OnlineMrApplicationErrorCode.AGENT_PACKAGE_CONFLICT,
            ),
            "conflict",
        ),
    ],
)
def test_download_import_result_is_forwarded(
    tmp_path: Path,
    result: OnlineMrAgentDownloadImportResult,
    attribute: str,
) -> None:
    service, download = _service(tmp_path, result)

    actual = asyncio.run(
        service.download_import_package(
            "package-1",
            site_id="site-a",
            device_id="7",
            device_name="MR-07",
            mr_name="MR-07",
        )
    )

    assert getattr(actual, attribute)
    assert download.calls[0][0] == "package-1"
    assert download.calls[0][1]["site_id"] == "site-a"


def test_download_failure_does_not_call_importer(tmp_path: Path) -> None:
    token = "controller-secret-token"

    class Importer:
        def import_package(self, *_args, **_kwargs):
            raise AssertionError("下载失败时不能调用 importer")

    client = OnlineMrAgentHttpClient(
        OnlineMrAgentConnectionConfig(
            base_url="http://127.0.0.1:18080",
            token=SecretStr(token),
        ),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                json={"ok": False, "error": {"message": token}},
            )
        ),
    )
    paths = _paths(tmp_path)
    service = OnlineMrAgentControllerService(
        paths,
        client,
        download_service=OnlineMrAgentDownloadService(
            paths,
            client,
            importer=Importer(),  # type: ignore[arg-type]
        ),
    )

    result = asyncio.run(
        service.download_import_package(
            "package-1",
            site_id="site-a",
            device_id="7",
            device_name="MR-07",
            mr_name="MR-07",
        )
    )

    assert not result.success and not result.downloaded
    assert result.error_code == OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED
    assert token not in " ".join(result.errors)


def test_controller_does_not_hide_typed_client_error_or_token(tmp_path: Path) -> None:
    token = "controller-secret-token"
    client = OnlineMrAgentHttpClient(
        OnlineMrAgentConnectionConfig(
            base_url="http://127.0.0.1:18080",
            token=SecretStr(token),
        ),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                401,
                json={"ok": False, "error": {"message": token}},
            )
        ),
    )
    service = OnlineMrAgentControllerService(_paths(tmp_path), client)

    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(service.ping_agent())

    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_AUTH_FAILED
    assert token not in str(exc_info.value)
