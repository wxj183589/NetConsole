from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.agent import AgentAuthenticationType
from netconsole.models.device import Device
from netconsole.models.online_mr_agent import (
    OnlineMrAgentConnectionConfig,
    OnlineMrAgentImportStatus,
    OnlineMrAgentPackageInfo,
    OnlineMrAgentPingResponse,
    OnlineMrAgentSystemStatus,
    OnlineMrAgentTaskStatusResponse,
    OnlineMrAgentToolsStatus,
    OnlineMrAgentToolStatus,
)
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrTaskSessionMapping,
)
from netconsole.models.task_snapshot import TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.agent.controller import (
    AgentControllerService,
    AgentControllerSettings,
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


class _SyncClient(_Client):
    def __init__(self, *, host: str = "192.0.2.12", source_hash: str = "") -> None:
        self.host = host
        self.source_hash = source_hash

    async def list_packages(self) -> tuple[OnlineMrAgentPackageInfo, ...]:
        return (
            OnlineMrAgentPackageInfo(
                package_id="package-1",
                task_id="agent-session-1",
                task_type="mr_realtime_collect",
                size=128,
                source_zip_sha256=self.source_hash,
            ),
        )

    async def get_task(self, task_id: str) -> OnlineMrAgentTaskStatusResponse:
        return OnlineMrAgentTaskStatusResponse(
            task_id=task_id,
            task_type="mr_realtime_collect",
            status="stopped",
            params={
                "target": {"id": "temporary-12", "name": "12-MR-CT", "host": self.host},
                "session": {"device_id": "temporary-12", "device_name": "12-MR-CT"},
            },
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


def _create_device(paths: PathResolver, *, name: str, host: str) -> Device:
    database = Database(paths.site_db_path("site-a"))
    database.initialize()
    return DeviceRepository(database).create(
        Device(name=name, device_type="Cloud-AP", primary_address=host)
    )


def _register_imported_package(paths: PathResolver, *, source_hash: str) -> None:
    session_id = "agent-session-1"
    task_id = "controller-task-1"
    now = utc_now_iso()
    session_dir = paths.online_mr_session_dir("site-a", "MR-12__12", session_id)
    (session_dir / "outputs").mkdir(parents=True)
    (session_dir / "outputs" / f"{session_id}.zip").write_bytes(b"zip")
    (session_dir / "import_manifest.json").write_text(
        json.dumps(
            {
                "source_package_id": "package-1",
                "source_zip_sha256": source_hash,
                "package_relative_path": f"outputs/{session_id}.zip",
                "agent_id": "agent-a",
                "agent_task_id": session_id,
                "controller_task_id": task_id,
                "session_id": session_id,
            }
        ),
        encoding="utf-8",
    )
    TaskRepository(paths.site_tasks_db_path("site-a")).save(
        TaskSnapshot(
            task_id=task_id,
            task_type="online_mr_collect",
            task_name="MR-12",
            status=TaskState.COMPLETED,
            created_time=now,
            updated_time=now,
            source="agent",
            site_name="site-a",
        )
    )
    OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path("site-a"), site_id="site-a"
    ).create(
        OnlineMrTaskSessionMapping(
            controller_task_id=task_id,
            session_id=session_id,
            site_id="site-a",
            device_id="12",
            device_name="MR-12",
            mr_id="12",
            mr_name="MR-12",
            executor_kind=OnlineMrExecutorKind.AGENT,
            agent_id="agent-a",
            phase=OnlineMrPhase.TERMINAL,
            mapping_state=OnlineMrMappingState.TERMINAL,
            created_at=now,
            updated_at=now,
            terminal_at=now,
        )
    )


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


def test_controller_reuses_existing_agent_profile_repository(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    profiles = AgentControllerService(
        paths=paths,
        site_name="site-a",
        settings=AgentControllerSettings(health_check_enabled=False),
    )
    created = profiles.create_agent(
        name="Agent A",
        base_url="http://127.0.0.1:18080",
        enabled=True,
        authentication_type=AgentAuthenticationType.NONE,
    )
    service = OnlineMrAgentControllerService(paths, profile_controller=profiles)

    assert service.list_profiles()[0]["agent_id"] == created["agent_id"]
    assert service.get_profile(created["agent_id"])["base_url"] == "http://127.0.0.1:18080"
    assert paths.site_agents_db_path("site-a").is_file()
    assert not (paths.site_dir("site-a") / "db" / "online_mr_agents.db").exists()


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
            identity_match_policy="manual_override",
            expected_host="192.0.2.12",
            allow_identity_override=True,
        )
    )

    assert getattr(actual, attribute)
    assert download.calls[0][0] == "package-1"
    assert download.calls[0][1]["site_id"] == "site-a"
    assert download.calls[0][1]["identity_match_policy"] == "manual_override"
    assert download.calls[0][1]["expected_host"] == "192.0.2.12"
    assert download.calls[0][1]["allow_identity_override"] is True


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
    assert (
        result.error_code == OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED
    )
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


def test_sync_packages_resolves_unique_static_device_by_ip(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    device = _create_device(paths, name="列车12-MR-CT", host="192.0.2.12")
    service = OnlineMrAgentControllerService(paths, _SyncClient())  # type: ignore[arg-type]

    result = asyncio.run(service.sync_agent_packages(site_id="site-a"))

    package = result.packages[0]
    assert package.source_device_id == "temporary-12"
    assert package.source_host == "192.0.2.12"
    assert package.candidate_local_device is not None
    assert package.candidate_local_device.device_id == device.id
    assert package.candidate_match_method == "ip_match"
    assert package.import_status is OnlineMrAgentImportStatus.NOT_IMPORTED


def test_sync_packages_requires_manual_resolution_when_ip_is_unknown(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _create_device(paths, name="列车12-MR-CT", host="192.0.2.12")
    service = OnlineMrAgentControllerService(
        paths, _SyncClient(host="192.0.2.99")  # type: ignore[arg-type]
    )

    package = asyncio.run(service.sync_agent_packages(site_id="site-a")).packages[0]

    assert package.candidate_local_device is None
    assert package.candidate_match_method == "not_found"
    assert package.resolution_code == OnlineMrApplicationErrorCode.AGENT_DEVICE_MATCH_NOT_FOUND


def test_sync_packages_reports_duplicate_static_ip_as_conflict(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _create_device(paths, name="MR-A", host="192.0.2.12")
    duplicate = _create_device(paths, name="MR-B", host="192.0.2.13")
    # 模拟地址唯一约束上线前遗留的重复主地址数据。
    with Database(paths.site_db_path("site-a")).connect() as conn:
        conn.execute("DROP INDEX uq_devices_normalized_primary_address")
        conn.execute(
            "UPDATE devices SET primary_address = ?, normalized_primary_address = ? WHERE id = ?",
            ("192.0.2.12", "192.0.2.12", duplicate.id),
        )
        conn.commit()
    service = OnlineMrAgentControllerService(paths, _SyncClient())  # type: ignore[arg-type]

    package = asyncio.run(service.sync_agent_packages(site_id="site-a")).packages[0]

    assert package.candidate_local_device is None
    assert len(package.candidate_local_devices) == 2
    assert package.candidate_match_method == "conflict"
    assert package.resolution_code == OnlineMrApplicationErrorCode.AGENT_DEVICE_MATCH_CONFLICT


def test_auto_resolve_by_ip_passes_formal_identity_to_importer(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    device = _create_device(paths, name="列车12-MR-CT", host="192.0.2.12")
    download = _DownloadService(OnlineMrAgentDownloadImportResult(True, imported=True))
    service = OnlineMrAgentControllerService(
        paths,
        _SyncClient(),  # type: ignore[arg-type]
        download_service=download,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.download_import_agent_package(
            "package-1",
            site_id="site-a",
            identity_match_policy="ip_match",
            auto_resolve_by_ip=True,
        )
    )

    assert result.success
    options = download.calls[0][1]
    assert options["device_id"] == device.id
    assert options["device_name"] == "列车12-MR-CT"
    assert options["expected_host"] == "192.0.2.12"
    assert options["identity_match_policy"] == "ip_match"
    assert options["source_package_id"] == "package-1"


def test_auto_resolve_by_ip_does_not_download_when_device_is_missing(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    download = _DownloadService(OnlineMrAgentDownloadImportResult(True, imported=True))
    service = OnlineMrAgentControllerService(
        paths,
        _SyncClient(),  # type: ignore[arg-type]
        download_service=download,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.download_import_agent_package(
            "package-1",
            site_id="site-a",
            identity_match_policy="ip_match",
            auto_resolve_by_ip=True,
        )
    )

    assert not result.success
    assert result.error_code == OnlineMrApplicationErrorCode.AGENT_DEVICE_MATCH_NOT_FOUND
    assert download.calls == []


@pytest.mark.parametrize(
    ("remote_hash", "expected"),
    [
        ("same-hash", OnlineMrAgentImportStatus.ALREADY_IMPORTED),
        ("different-hash", OnlineMrAgentImportStatus.CONFLICT),
    ],
)
def test_sync_package_import_status_uses_manifest_task_and_mapping(
    tmp_path: Path, remote_hash: str, expected: OnlineMrAgentImportStatus
) -> None:
    paths = _paths(tmp_path)
    _create_device(paths, name="列车12-MR-CT", host="192.0.2.12")
    _register_imported_package(paths, source_hash="same-hash")
    service = OnlineMrAgentControllerService(
        paths, _SyncClient(source_hash=remote_hash)  # type: ignore[arg-type]
    )

    package = asyncio.run(service.sync_agent_packages(site_id="site-a")).packages[0]

    assert package.import_status is expected
