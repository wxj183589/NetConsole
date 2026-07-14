from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_agent import (
    ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES,
    OnlineMrAgentConnectionConfig,
    OnlineMrAgentStartRequest,
    OnlineMrAgentStatus,
)
from netconsole.services.online_mr.agent_download_service import (
    OnlineMrAgentDownloadService,
)
from netconsole.services.online_mr.agent_http_client import (
    OnlineMrAgentClientError,
    OnlineMrAgentHttpClient,
)
from netconsole.services.online_mr.errors import OnlineMrApplicationErrorCode


BASE_URL = "http://127.0.0.1:18080"
TOKEN = "top-secret-token"
SITE = "site-a"


def _config(**changes: object) -> OnlineMrAgentConnectionConfig:
    values: dict[str, object] = {
        "base_url": BASE_URL,
        "token": SecretStr(TOKEN),
        "timeout_sec": 2.0,
        "max_download_bytes": 1024 * 1024,
        "download_chunk_size": 64 * 1024,
    }
    values.update(changes)
    return OnlineMrAgentConnectionConfig(**values)


def _response(data: object, *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"ok": status < 400, "data": data})


def _error(status: int, message: str = "request failed") -> httpx.Response:
    return httpx.Response(status, json={"ok": False, "error": {"message": message}})


def _client(handler, **config: object) -> OnlineMrAgentHttpClient:
    return OnlineMrAgentHttpClient(
        _config(**config),
        transport=httpx.MockTransport(handler),
    )


def _package_bytes(
    *,
    marker: str = "raw evidence\n",
    session_id: str = "session-1",
    session_meta_overrides: dict[str, object] | None = None,
) -> bytes:
    root = f"{session_id}_MR-07_agent/"
    documents: dict[str, dict[str, object]] = {
        "session_meta.json": {
            "session_id": session_id,
            "site": SITE,
            "device_id": "7",
            "device_name": "MR-07",
            "mr_id": "7",
            "mr_name": "MR-07",
            "status": "COMPLETED",
            "started_at": "2026-07-13T10:00:00Z",
            "ended_at": "2026-07-13T10:02:00Z",
            "duration_minutes": 2.0,
            "data_integrity": "complete",
        },
        "task.json": {
            "task_id": "agent-task-1",
            "task_type": "mr_realtime_collect",
            "status": "completed",
            "start_time": "2026-07-13T10:00:00Z",
            "end_time": "2026-07-13T10:02:00Z",
        },
        "manifest.json": {
            "package_type": "netconsole_agent_collect_package",
            "package_version": 1,
            "task_type": "mr_realtime_collect",
            "task_id": "agent-task-1",
            "agent_id": "agent-a",
            "status": "completed",
        },
        "agent_info.json": {"agent_id": "agent-a", "agent_name": "Agent A"},
        "system_info.json": {"os": "windows", "arch": "amd64"},
        "stop_reason.json": {"reason": "completed"},
    }
    documents["session_meta.json"].update(session_meta_overrides or {})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES):
            if name in documents:
                content = json.dumps(documents[name], ensure_ascii=False)
            elif name == "raw/collector_output_raw.log":
                content = marker
            elif name.endswith(".json"):
                content = "{}"
            else:
                content = ""
            archive.writestr(root + name, content)
    return output.getvalue()


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs(SITE)
    return paths


def test_fixed_start_and_task_stop_routes_send_secret_only_in_start_body() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        seen.append((request.url.path, body))
        assert request.headers["x-agent-token"] == TOKEN
        status = "running" if request.url.path.endswith("/start") else "stopping"
        return _response(
            {
                "task_id": "agent-task-1",
                "task_type": "mr_realtime_collect",
                "status": status,
            }
        )

    request = OnlineMrAgentStartRequest.model_validate(
        {
            "agent_id": "agent-a",
            "site_id": SITE,
            "device_id": 7,
            "device_name": "MR-07",
            "mr_name": "MR-07",
            "target": {
                "name": "MR-07",
                "host": "192.0.2.7",
                "username": "operator",
                "password": "device-secret",
            },
            "items": {},
            "intervals": {},
            "radio": {},
        }
    )
    client = _client(handler)
    started = asyncio.run(client.start_collection(request))
    stopped = asyncio.run(client.stop_collection(started.task_id))

    assert started.status is OnlineMrAgentStatus.RUNNING
    assert stopped.status is OnlineMrAgentStatus.STOPPING
    assert seen[0][0] == "/api/v1/mr/collect/start"
    assert dict(seen[0][1]["target"])["password"] == "device-secret"
    assert seen[1] == ("/api/v1/tasks/agent-task-1/stop", {})


def _import_kwargs() -> dict[str, object]:
    return {
        "site_id": SITE,
        "site_name": SITE,
        "device_id": 7,
        "device_name": "MR-07",
        "mr_id": "7",
        "mr_name": "MR-07",
        "agent_id": "agent-a",
    }


def test_ping_sends_token_and_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Agent-Token"] == TOKEN
        assert request.headers["User-Agent"] == "NetConsole-OnlineMR"
        return _response({"status": "ok", "time": "2026-07-13T10:00:00Z"})

    result = asyncio.run(_client(handler).ping())

    assert result.status == "ok"


def test_ping_timeout_maps_to_online_mr_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(_client(handler).ping())

    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_TIMEOUT


def test_connect_failure_maps_to_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(_client(handler).ping())

    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_UNREACHABLE


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failure_has_stable_error(status: int) -> None:
    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(_client(lambda _request: _error(status)).ping())

    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_AUTH_FAILED


def test_status_missing_required_field_is_invalid() -> None:
    payload = {"agent_id": "agent-a", "version": "v1.0", "os": "windows"}

    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(_client(lambda _request: _response(payload)).get_status())

    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_RESPONSE_INVALID


def test_status_accepts_actual_agent_release_version() -> None:
    payload = {
        "agent_id": "agent-a",
        "agent_name": "Agent A",
        "version": "0.2.0-win-agent",
        "os": "windows",
        "arch": "amd64",
    }

    result = asyncio.run(_client(lambda _request: _response(payload)).get_status())

    assert result.version == "0.2.0-win-agent"


def test_get_task_parses_online_mr_task() -> None:
    payload = {
        "task_id": "task-1",
        "task_type": "mr_realtime_collect",
        "status": "completed",
        "created_at": "2026-07-13T10:00:00Z",
        "start_time": "2026-07-13T10:00:01Z",
        "end_time": "2026-07-13T10:02:00Z",
        "package_id": "package-1",
        "package_download_url": "/api/v1/packages/package-1/download",
        "params": {"ignored": True},
    }

    result = asyncio.run(
        _client(lambda _request: _response(payload)).get_task("task-1")
    )

    assert result.status is OnlineMrAgentStatus.COMPLETED
    assert result.package_id == "package-1"


def test_get_task_not_found_maps_to_task_not_found() -> None:
    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(_client(lambda _request: _error(404)).get_task("missing"))

    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_TASK_NOT_FOUND


def test_list_packages_and_tools_status_are_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/packages"):
            return _response(
                [
                    {
                        "session_id": "session-1",
                        "created_at": "created",
                        "end_time": "end",
                        "status": "completed",
                        "file_name": "package-1.zip",
                        "package_download_url": "/api/v1/packages/package-1/download",
                    }
                ]
            )
        return _response(
            {
                "tools": {
                    "mr_collector": {"exists": True, "ready": True, "path": "private"},
                    "fping": {"exists": True, "ready": True},
                    "iperf3": {"exists": False, "ready": False, "warning": "missing"},
                }
            }
        )

    client = _client(handler)
    packages = asyncio.run(client.list_packages())
    tools = asyncio.run(client.get_tools_status())

    assert packages[0].package_id == "package-1"
    assert packages[0].task_id == ""
    assert packages[0].session_id == "session-1"
    assert packages[0].status == "completed"
    assert tools.mr_collector.ready and not tools.iperf3.ready
    assert "private" not in tools.model_dump_json()


def test_download_package_writes_final_zip_and_sha256(tmp_path: Path) -> None:
    content = _package_bytes()
    result = asyncio.run(
        _client(
            lambda _request: httpx.Response(
                200,
                content=content,
                headers={"Content-Type": "application/zip"},
            )
        ).download_package("package-1", tmp_path)
    )

    assert result.path.read_bytes() == content
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.size == len(content)
    assert result.content_type == "application/zip"
    assert not list(tmp_path.glob("*.part"))


def test_package_not_ready_cleans_partial_file(tmp_path: Path) -> None:
    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(
            _client(lambda _request: _error(404)).download_package(
                "package-1", tmp_path
            )
        )

    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_PACKAGE_NOT_READY
    assert not list(tmp_path.iterdir())


class _BrokenStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"partial"
        raise httpx.ReadError("connection closed")


def test_download_interruption_removes_partial_file(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_BrokenStream())

    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(_client(handler).download_package("package-1", tmp_path))

    assert (
        exc_info.value.code
        == OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED
    )
    assert not list(tmp_path.iterdir())


def test_download_size_limit_removes_partial_file(tmp_path: Path) -> None:
    client = _client(
        lambda _request: httpx.Response(200, content=b"12345"),
        max_download_bytes=4,
    )

    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(client.download_package("package-1", tmp_path))

    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_PACKAGE_TOO_LARGE
    assert not list(tmp_path.iterdir())


def test_download_cancellation_removes_partial_file(tmp_path: Path) -> None:
    client = _client(lambda _request: httpx.Response(200, content=b"content"))

    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(
            client.download_package(
                "package-1",
                tmp_path,
                cancel_check=lambda: True,
            )
        )

    assert (
        exc_info.value.code
        == OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED
    )
    assert not list(tmp_path.iterdir())


def test_token_never_appears_in_error_text() -> None:
    with pytest.raises(OnlineMrAgentClientError) as exc_info:
        asyncio.run(_client(lambda _request: _error(500, TOKEN)).get_status())

    assert TOKEN not in str(exc_info.value)
    assert TOKEN not in exc_info.value.message


def test_download_service_imports_package_and_cleans_download(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    content = _package_bytes()
    client = _client(lambda _request: httpx.Response(200, content=content))
    service = OnlineMrAgentDownloadService(paths, client)

    result = asyncio.run(
        service.download_and_import_package("package-1", **_import_kwargs())
    )

    assert result.success and result.downloaded and result.imported
    assert result.downloaded_path is None
    assert result.session_dir is not None
    assert (result.session_dir / "raw" / "collector_output_raw.log").is_file()
    assert (result.session_dir / "outputs" / "session-1.zip").is_file()


def test_download_service_forwards_manual_identity_override(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    content = _package_bytes(
        session_meta_overrides={
            "device_id": "agent-device-12",
            "device_name": "12-MR-CT",
            "mr_id": "agent-mr-12",
            "mr_name": "12-MR-CT",
        }
    )
    service = OnlineMrAgentDownloadService(
        paths, _client(lambda _request: httpx.Response(200, content=content))
    )

    result = asyncio.run(
        service.download_and_import_package(
            "package-1",
            **_import_kwargs(),
            identity_match_policy="manual_override",
            allow_identity_override=True,
        )
    )

    assert result.success and result.session_dir is not None
    manifest = json.loads(
        (result.session_dir / "import_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["identity"]["match_method"] == "manual_override"
    assert manifest["identity"]["source"]["device_id"] == "agent-device-12"
    assert manifest["identity"]["source"]["mr_id"] == "agent-mr-12"


def test_download_service_is_idempotent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    content = _package_bytes()
    service = OnlineMrAgentDownloadService(
        paths,
        _client(lambda _request: httpx.Response(200, content=content)),
    )

    first = asyncio.run(
        service.download_and_import_package("package-1", **_import_kwargs())
    )
    second = asyncio.run(
        service.download_and_import_package("package-1", **_import_kwargs())
    )

    assert first.imported
    assert second.success and second.already_imported and not second.imported


def test_download_service_preserves_conflicting_zip(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = OnlineMrAgentDownloadService(
        paths,
        _client(
            lambda _request: httpx.Response(200, content=_package_bytes(marker="first"))
        ),
    )
    second = OnlineMrAgentDownloadService(
        paths,
        _client(
            lambda _request: httpx.Response(
                200, content=_package_bytes(marker="second")
            )
        ),
    )
    asyncio.run(first.download_and_import_package("package-1", **_import_kwargs()))

    result = asyncio.run(
        second.download_and_import_package("package-1", **_import_kwargs())
    )

    assert not result.success and result.conflict
    assert result.error_code == OnlineMrApplicationErrorCode.AGENT_PACKAGE_CONFLICT
    assert result.downloaded_path is not None and result.downloaded_path.is_file()


def test_download_service_keeps_invalid_zip_without_polluting_session(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    service = OnlineMrAgentDownloadService(
        paths,
        _client(lambda _request: httpx.Response(200, content=b"not-a-zip")),
    )

    result = asyncio.run(
        service.download_and_import_package("package-1", **_import_kwargs())
    )

    assert not result.success and result.downloaded
    assert result.error_code == OnlineMrApplicationErrorCode.AGENT_PACKAGE_INVALID
    assert result.downloaded_path is not None and result.downloaded_path.is_file()
    assert not paths.online_mr_root(SITE).exists()


def test_download_service_reports_session_id_mismatch(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = OnlineMrAgentDownloadService(
        paths,
        _client(lambda _request: httpx.Response(200, content=_package_bytes())),
    )

    result = asyncio.run(
        service.download_and_import_package(
            "package-1",
            expected_session_id="different-session",
            **_import_kwargs(),
        )
    )

    assert not result.success
    assert result.error_code == OnlineMrApplicationErrorCode.AGENT_SESSION_ID_MISMATCH


def test_download_failure_does_not_call_importer(tmp_path: Path) -> None:
    class Importer:
        def import_package(self, *_args, **_kwargs):
            raise AssertionError("importer must not be called")

    paths = _paths(tmp_path)
    service = OnlineMrAgentDownloadService(
        paths,
        _client(lambda _request: _error(500)),
        importer=Importer(),  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.download_and_import_package("package-1", **_import_kwargs())
    )

    assert not result.success and not result.downloaded
    assert (
        result.error_code == OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED
    )
