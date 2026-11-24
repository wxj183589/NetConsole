from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.device_operations_router import router
from netconsole.core.database import Database
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import device_task_service
from netconsole.services.h3c_command_template import (
    CommandTemplatePreviewRequest,
    TemplatePreviewError,
    preview_command_template,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.job_registry import get_handler
from netconsole.services.job_center.task_application_service import TaskApplicationService
from tests.support.job_process_test_support import FakeLocalProcessAdapter


def test_template_handles_comments_variables_loops_conditions_and_filters():
    request = CommandTemplatePreviewRequest(
        source="""{# 一条注释 #}
{# 多行
注释 #}
sysname {{ device_name | upper }} {# 行内注释 #}
{% for intf in interfaces %}
interface {{ intf.name }}
{% if intf.type == 'access' %}
 port access vlan {{ intf.vlan }}
{% else %}
 port trunk permit vlan {{ intf.vlans | join(',') }}
{% endif %}
 speed {{ intf.speed | default('auto') }}
quit
{% endfor %}
save force
""",
        schema_fields={"device_name": {"type": "string"}, "interfaces": {"type": "list"}},
        values={
            "device_name": "sw-1",
            "interfaces": [
                {"name": "GE1/0/1", "type": "access", "vlan": 10},
                {"name": "GE1/0/2", "type": "trunk", "vlans": [10, 20]},
            ],
        },
    )
    result = preview_command_template(request)
    assert result.risk == "configuration_change"
    assert result.commands == [
        "sysname SW-1", "interface GE1/0/1", "port access vlan 10", "speed auto", "quit",
        "interface GE1/0/2", "port trunk permit vlan 10,20", "speed auto", "quit", "save force",
    ]


@pytest.mark.parametrize("source", [
    "{{ missing }}",
    "{{ value.upper() }}",
    "{{ value.__class__ }}",
    "{% include 'other' %}",
    "{{ 'x' * 50000000 }}",
    "{{ value | replace('a', 'b') }}",
])
def test_template_fails_closed(source):
    with pytest.raises(TemplatePreviewError):
        preview_command_template(CommandTemplatePreviewRequest(
            source=source, schema_fields={"value": {"type": "string"}}, values={"value": "a"},
        ))


@pytest.fixture
def runtime(tmp_path: Path):
    paths = PathResolver(app_root=Path(__file__).resolve().parents[1], data_root=tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    devices = DeviceRepository(database)
    sw_a = devices.create(Device(name="SW A", primary_address="192.0.2.1", device_type="SW", device_vendor="H3C"))
    sw_b = devices.create(Device(name="SW B", primary_address="192.0.2.2", device_type="SW", device_vendor="H3C"))
    tasks = TaskApplicationService(paths)
    adapter = FakeLocalProcessAdapter(tasks)
    app = FastAPI()
    app.state.feature_gate = FeatureGate(paths.app_root)
    app.state.task_service = tasks
    app.state.site_process_adapter = adapter
    app.state.device_task_application_service = device_task_service.DeviceTaskApplicationService(tasks, adapter)
    app.state.device_management_service = SimpleNamespace(current_site_id=lambda: "demo")
    app.include_router(router)
    return TestClient(app), adapter, sw_a, sw_b


def test_task_executes_registered_worker_and_retries_failed_device(runtime, monkeypatch):
    client, adapter, sw_a, sw_b = runtime
    collected = []

    def fake_collect(context, site, kind, device, facts, commands):
        collected.append((site, kind, device.device_uuid, commands))
        return {"status": "failed" if device.device_uuid == sw_b.device_uuid else "success"}

    monkeypatch.setattr(device_task_service, "_collect_device", fake_collect)
    request = {"kind": "version", "device_uuids": [sw_a.device_uuid, sw_b.device_uuid]}
    response = client.post("/device-operations/tasks", json=request)
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    assert response.json()["run_id"] == task_id
    job = adapter.jobs[task_id]
    result = get_handler(job.task_type)(JobContext.from_job(job))
    assert {item[2] for item in collected} == {sw_a.device_uuid, sw_b.device_uuid}
    assert result["business_status"] == "PARTIAL_SUCCESS"
    adapter.complete(task_id, result)
    assert client.get(f"/device-operations/tasks/{task_id}/result").json()["items"] == result["items"]
    response = client.post(f"/device-operations/tasks/{task_id}/retry")
    assert response.status_code == 202, response.text
    retry = adapter.jobs[response.json()["task_id"]]
    assert retry.retry_of_task_id == task_id
    assert retry.params["device_uuids"] == [sw_b.device_uuid]


def test_task_rejects_unknown_target_and_configuration_commands(runtime):
    client, adapter, sw_a, _ = runtime
    request = {"kind": "custom", "device_uuids": [sw_a.device_uuid]}
    assert client.post("/device-operations/tasks", json={**request, "template": {"source": "save force"}}).status_code == 422
    response = client.post("/device-operations/tasks", json={
        **request, "device_uuids": ["different-site"], "template": {"source": "display version"},
    })
    assert response.status_code == 422


def test_saved_template_versions_preview_and_parameter_binding(runtime):
    client, adapter, sw_a, _ = runtime
    definition = {
        "name": "交换机接口查询",
        "category": "光模块",
        "source": "display transceiver diagnosis interface {{ interface }}",
        "schema_fields": {"interface": {"type": "interface"}},
        "device_roles": ["switch"],
    }
    saved = client.post("/device-operations/templates", json=definition)
    assert saved.status_code == 201, saved.text
    template_id = saved.json()["template_id"]
    parameters = {
        "template_id": template_id, "version": 1,
        "values": {"interface": "GigabitEthernet1/0/1"},
    }
    assert client.get("/device-operations/templates").json() == [saved.json()]
    preview = client.post("/device-operations/templates/saved-preview", json=parameters)
    assert preview.status_code == 200, preview.text
    assert preview.json()["commands"] == ["display transceiver diagnosis interface GigabitEthernet1/0/1"]
    task = {"kind": "custom", "device_uuids": [sw_a.device_uuid]}
    digest = preview.json()["preview_digest"]
    changed = {**parameters, "values": {"interface": "GigabitEthernet1/0/2"}, "preview_digest": digest}
    assert client.post("/device-operations/tasks", json={**task, "saved_template": changed}).status_code == 422
    good = {**parameters, "preview_digest": digest}
    response = client.post("/device-operations/tasks", json={**task, "saved_template": good})
    assert response.status_code == 202, response.text
    frozen = adapter.jobs[response.json()["task_id"]].params
    assert frozen["template"] == {"template_id": template_id, "version": 1, "device_roles": ["switch"]}
    assert frozen["commands"] == preview.json()["commands"]

    template_path = f"/device-operations/templates/{template_id}"
    disabled = client.put(f"{template_path}?expected_version=1", json={**definition, "enabled": False})
    assert disabled.status_code == 200, disabled.text
    assert [item["version"] for item in client.get(f"{template_path}/versions").json()] == [2, 1]
    assert client.put(f"{template_path}?expected_version=1", json=definition).status_code == 409
    assert client.post("/device-operations/templates/saved-preview", json=parameters).status_code == 409
    assert client.post("/device-operations/tasks", json={**task, "saved_template": good}).status_code == 409

    client.app.state.device_management_service = SimpleNamespace(current_site_id=lambda: "another")
    assert client.get("/device-operations/templates").json() == []
    assert client.get(f"{template_path}/versions").status_code == 404


def test_saved_template_allows_configuration_preview_only(runtime):
    client, adapter, sw_a, _ = runtime
    saved = client.post("/device-operations/templates", json={
        "name": "写配置预览", "source": "save force", "command_type": "configuration_change",
    }).json()
    selection = {"template_id": saved["template_id"], "version": saved["version"], "values": {}}
    preview = client.post("/device-operations/templates/saved-preview", json=selection)
    assert preview.status_code == 200
    assert preview.json()["risk"] == "configuration_change"
    response = client.post("/device-operations/tasks", json={
        "kind": "custom", "device_uuids": [sw_a.device_uuid],
        "saved_template": {**selection, "preview_digest": preview.json()["preview_digest"]},
    })
    assert response.status_code == 422
    assert not adapter.jobs

    read_only = client.post("/device-operations/templates", json={
        "name": "只读预览", "source": "display version", "command_type": "configuration_change",
    }).json()
    mismatch = client.post("/device-operations/templates/saved-preview", json={
        "template_id": read_only["template_id"], "version": 1, "values": {},
    })
    assert mismatch.status_code == 422


def test_saved_template_accepts_standard_h3c_ten_gigabit_interface(runtime):
    client, adapter, _sw_a, _sw_b = runtime
    response = client.post("/device-operations/templates/preview", json={
        "source": "display transceiver diagnosis interface {{ interface }}",
        "schema_fields": {"interface": {"type": "interface"}},
        "values": {"interface": "Ten-GigabitEthernet1/0/1"},
    })
    assert response.status_code == 200
    assert response.json()["risk"] == "read_only"
    assert not adapter.jobs
    assert not adapter.jobs
    response = client.post("/device-operations/templates/preview", json={
        "source": "display transceiver diagnosis interface {{ interface }}",
        "schema_fields": {"interface": {"type": "interface"}},
        "values": {"interface": "GigabitEthernet1/0/1\nsave force"},
    })
    assert response.status_code == 422
