from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.support.web_parity_test_support import FakeExportProcessAdapter
from netconsole.application.web_artifacts import WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.backend.api.main import create_app
from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services import command_reference_application_service
from netconsole.services.command_reference_application_service import CommandReferenceApplicationService
from netconsole.services.command_reference_service import load_command_references
from netconsole.services.job_center.local_process_adapter import LocalProcessCompletion


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_NAME = "NetConsole_软件使用命令清单.md"


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _client(tmp_path: Path) -> tuple[TestClient, FakeExportProcessAdapter, WebArtifactStore, PathResolver]:
    paths = PathResolver(ROOT, tmp_path)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    production_service = app.state.command_reference_application_service
    assert type(production_service.export_adapter) is WebExportProcessAdapter
    assert type(production_service.artifact_store) is WebArtifactStore
    assert production_service.artifact_store is app.state.web_artifact_store
    app.state.feature_gate.features["module.command_reference"].update(visible=True, enabled=True)

    adapter = FakeExportProcessAdapter(app.state.task_service)
    app.state.command_reference_application_service = CommandReferenceApplicationService(
        paths,
        app.state.task_service,
        adapter,  # type: ignore[arg-type]
        app.state.web_artifact_store,
    )
    return TestClient(app), adapter, app.state.web_artifact_store, paths


def _complete(adapter: FakeExportProcessAdapter, task_id: str, artifact_id: str, content: bytes) -> None:
    job = adapter.jobs[task_id]
    output = Path(job.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    event = {
        "type": "finished",
        "job_id": task_id,
        "message": "fixture export completed",
        "result": {
            "artifact_id": artifact_id,
            "artifact_name": output.name,
            "artifact_source": "command_reference_export",
            "artifact_type": "md",
            "artifact_pending": True,
            "row_count": 1,
        },
    }
    adapter.tasks.feed_stdout(task_id, (json.dumps(event) + "\n").encode("utf-8"))
    payload = adapter.tasks.complete(task_id, 0)
    callback = adapter.callbacks.pop(task_id)
    adapter.jobs.pop(task_id)
    callback(
        LocalProcessCompletion(
            job_id=task_id,
            task_type=f"web_export_{job.job_type}",
            exit_code=0,
            payload=payload,
            cancelled=False,
            forced=False,
        )
    )


def test_command_reference_query_matches_qt_filters_and_resource_count(tmp_path: Path) -> None:
    client, _adapter, _artifacts, paths = _client(tmp_path)
    references = load_command_references(paths)
    expected_switches = sum(item.device_scope.startswith("交换机") for item in references)
    expected_non_cli = sum(not item.is_cli for item in references)
    with client:
        response = client.get(
            "/api/command-reference",
            params={"query": "save force", "category": "配置保存"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "total": len(references),
        "shown": 1,
        "switch_count": expected_switches,
        "non_cli_count": expected_non_cli,
    }
    item = payload["items"][0]
    assert item["command_template"] == "save force"
    assert item["risk_level"] == "config_write"
    assert item["read_only"] is False
    assert item["modifies_device_config"] is True
    assert item["requires_interactive_confirmation"] is item["interactive_input"]
    assert "categories" in payload["filters"]


def test_command_reference_export_uses_public_store_and_safe_download_name(tmp_path: Path) -> None:
    client, adapter, artifacts, _paths = _client(tmp_path)
    with client:
        started = client.post("/api/command-reference/exports", json={"selected_ids": ["switch_display_version"]})
        assert started.status_code == 202
        task_id = started.json()["id"]
        assert "artifact_name" not in started.json()["result"]

        metadata = artifacts.task_metadata(
            "demo",
            task_id,
            owner="web_command_reference",
            source_task_types={"command_reference_export": "web_export_command_reference_markdown"},
        )
        assert metadata is not None
        physical_name = str(metadata["file_name"])
        artifact_id = str(metadata["artifact_id"])
        assert physical_name != ARTIFACT_NAME
        assert artifact_id[:12] in physical_name
        assert physical_name not in started.text

        _complete(adapter, task_id, artifact_id, b"# command reference\n")
        recovered = client.get(f"/api/command-reference/exports/{task_id}")
        downloaded = client.get(f"/api/command-reference/artifacts/{artifact_id}/download")

    result = recovered.json()["result"]
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "COMPLETED"
    assert result["artifact_name"] == ARTIFACT_NAME
    assert artifact_id not in result["artifact_name"]
    assert physical_name not in recovered.text
    assert downloaded.status_code == 200
    assert downloaded.content == b"# command reference\n"
    assert downloaded.headers["content-type"].startswith("text/markdown")
    disposition = downloaded.headers["content-disposition"]
    assert "NetConsole_" in disposition
    assert artifact_id not in disposition
    assert physical_name not in disposition


def test_command_reference_export_validates_selection_and_supports_cancel(tmp_path: Path) -> None:
    client, _adapter, _artifacts, _paths = _client(tmp_path)
    with client:
        invalid = client.post("/api/command-reference/exports", json={"selected_ids": ["missing"]})
        started = client.post("/api/command-reference/exports", json={"selected_ids": []})
        cancelled = client.post(f"/api/command-reference/exports/{started.json()['id']}/cancel")

    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "INVALID_EXPORT_SELECTION"
    assert started.status_code == 202
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "STOPPING"


@pytest.mark.parametrize("private_path", [r"C:\secret\command_reference.json", r"\\server\share\commands.json"])
def test_command_reference_resource_error_never_exposes_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    private_path: str,
) -> None:
    def fail(_paths: PathResolver):
        raise OSError(private_path)

    monkeypatch.setattr(command_reference_application_service, "load_command_references", fail)
    client, _adapter, _artifacts, _paths = _client(tmp_path)
    logged: list[str] = []
    monkeypatch.setattr(app_logger, "log_error", lambda code, message: logged.append(f"{code} {message}"))
    with client:
        response = client.get("/api/command-reference")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "COMMAND_REFERENCE_RESOURCE_UNAVAILABLE",
        "message": "命令说明资源暂时不可用",
    }
    assert private_path not in response.text
    assert logged == [
        "COMMAND_REFERENCE_RESOURCE_FAILED code=COMMAND_REFERENCE_RESOURCE_UNAVAILABLE type=OSError"
    ]
