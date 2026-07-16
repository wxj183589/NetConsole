from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from web_parity_test_support import FakeExportProcessAdapter
from netconsole.application.web_artifacts import WebArtifactStore
from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services.command_reference_application_service import CommandReferenceApplicationService
from netconsole.services.job_center.local_process_adapter import LocalProcessCompletion


ROOT = Path(__file__).resolve().parents[1]


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _CommandReferenceArtifactStore(WebArtifactStore):
    def _source_root(self, site_id: str, source: str) -> Path:
        if source == "command_reference_export":
            return self.paths.site_files_dir(site_id) / "command_reference"
        return super()._source_root(site_id, source)

def _client(tmp_path: Path) -> tuple[TestClient, FakeExportProcessAdapter, _CommandReferenceArtifactStore]:
    paths = PathResolver(ROOT, tmp_path)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    adapter = FakeExportProcessAdapter(app.state.task_service)
    artifacts = _CommandReferenceArtifactStore(paths, app.state.task_service)
    app.state.command_reference_application_service = CommandReferenceApplicationService(
        paths,
        app.state.task_service,
        adapter,  # type: ignore[arg-type]
        artifacts,
    )
    return TestClient(app), adapter, artifacts


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


def test_command_reference_query_matches_qt_filters_and_strict_dto(tmp_path: Path) -> None:
    client, _adapter, _artifacts = _client(tmp_path)
    with client:
        response = client.get(
            "/api/command-reference",
            params={"query": "save force", "category": "配置保存"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {"total": 77, "shown": 1, "switch_count": 29, "non_cli_count": 23}
    assert payload["items"][0]["command_template"] == "save force"
    assert payload["items"][0]["risk_level"] == "config_write"
    assert "categories" in payload["filters"]
    assert set(payload["items"][0]) == {
        "id", "module", "device_scope", "vendor", "protocol", "category", "command_template",
        "parameters", "pre_commands", "purpose", "output_log", "parser", "consumer", "risk_level",
        "interactive_input", "is_cli", "source_locations", "zte_adaptation_status", "comware_command",
        "zte_command", "parser_status", "notes",
    }


def test_command_reference_export_is_persistent_task_and_controlled_artifact(tmp_path: Path) -> None:
    client, adapter, artifacts = _client(tmp_path)
    with client:
        started = client.post("/api/command-reference/exports", json={"selected_ids": ["switch_display_version"]})
        assert started.status_code == 202
        task_id = started.json()["id"]
        assert started.json()["status"] == "RUNNING"
        assert "output_path" not in started.text

        metadata = artifacts.task_metadata(
            "demo",
            task_id,
            owner="web_command_reference",
            source_task_types={"command_reference_export": "web_export_command_reference_markdown"},
        )
        _complete(adapter, task_id, str(metadata["artifact_id"]), b"# command reference\n")
        recovered = client.get(f"/api/command-reference/exports/{task_id}")
        artifact_id = recovered.json()["result"]["artifact_id"]
        downloaded = client.get(f"/api/command-reference/artifacts/{artifact_id}/download")

    assert recovered.status_code == 200
    assert recovered.json()["status"] == "COMPLETED"
    assert len(recovered.json()["result"]["sha256"]) == 64
    assert downloaded.status_code == 200
    assert downloaded.content == b"# command reference\n"


def test_command_reference_export_validates_selection_and_supports_cancel(tmp_path: Path) -> None:
    client, _adapter, _artifacts = _client(tmp_path)
    with client:
        invalid = client.post("/api/command-reference/exports", json={"selected_ids": ["missing"]})
        started = client.post("/api/command-reference/exports", json={"selected_ids": []})
        cancelled = client.post(f"/api/command-reference/exports/{started.json()['id']}/cancel")

    assert invalid.status_code == 422
    assert started.status_code == 202
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "STOPPING"
