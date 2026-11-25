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


def test_task_scope_limits_and_settings(runtime, monkeypatch):
    client, adapter, sw_a, sw_b = runtime
    service = client.app.state.device_task_application_service
    monkeypatch.setattr(device_task_service, "RailInfrastructureRepository", lambda database: SimpleNamespace(
        read=lambda: SimpleNamespace(organization_initialized=True, nodes=[
            {"uid": "root", "name": "Root", "kind": "line"},
            {"uid": "child", "name": "Child", "kind": "station", "parent_uid": "root"},
        ]),
        organization_catalog=lambda site: SimpleNamespace(devices=[
            SimpleNamespace(device_uuid=sw_a.device_uuid, node_uids=["child"]),
            SimpleNamespace(device_uuid=sw_b.device_uuid, node_uids=["elsewhere"]),
        ]),
    ))
    reference = service.start("demo", device_task_service.DeviceTaskRequest(
        kind="version", organization_uid="root", concurrency=1, command_timeout=15,
    ))
    job = adapter.jobs[reference.task_id]
    assert job.params["device_uuids"] == [sw_a.device_uuid]
    assert job.params["concurrency"] == 1
    assert job.params["command_timeout"] == 15
    with pytest.raises(ValueError, match="其中一项"):
        service.start("demo", device_task_service.DeviceTaskRequest(
            kind="version", device_uuids=[sw_a.device_uuid], group_id="all",
        ))
    with pytest.raises(ValueError, match="结束后"):
        service.retry("demo", reference.task_id)
    assert client.post("/device-operations/tasks", json={
        "kind": "version", "device_uuids": [sw_a.device_uuid], "concurrency": 9,
    }).status_code == 422


def test_task_result_export_uses_worker_and_preserves_long_output(runtime):
    import json
    from openpyxl import load_workbook
    from netconsole.services.device_task_export_service import DeviceTaskExportService
    from netconsole.services.export.export_handlers import run_generic_export_handler
    from netconsole.services.web_artifacts import WebArtifactStore

    client, adapter, sw_a, _ = runtime
    devices = client.app.state.device_task_application_service
    reference = devices.start("demo", device_task_service.DeviceTaskRequest(
        kind="version", device_uuids=[sw_a.device_uuid],
    ))
    exports = []
    service = DeviceTaskExportService(
        devices, SimpleNamespace(start_export=lambda job, **kwargs: exports.append(job)),
        WebArtifactStore(devices.paths, devices.task_service),
    )
    with pytest.raises(ValueError, match="结束后"):
        service.start("demo", reference.task_id)
    item = {"device_uuid": sw_a.device_uuid, "status": "success", "output": "数据" * 20000}
    adapter.complete(reference.task_id, {"kind": "version", "items": [item]})
    service.start("demo", reference.task_id)
    job = exports[0]
    assert job.site_name == "demo"
    from dataclasses import replace
    job = replace(job, tmp_path=job.output_path + ".tmp")
    run_generic_export_handler(job)
    sheet = load_workbook(job.output_path)["设备任务结果"]
    header_row = next(row for row in range(1, 6) if sheet.cell(row, 1).value == "任务 ID")
    assert sheet.cell(header_row + 1, 1).value == reference.task_id
    reconstructed = "".join(sheet.cell(row, 12).value for row in range(header_row + 1, sheet.max_row + 1))
    assert json.loads(reconstructed) == item


def test_cancelled_task_does_not_contact_devices(runtime, monkeypatch):
    from netconsole.services.job_center.job_context import BackgroundTaskCancelled

    client, adapter, sw_a, _ = runtime
    service = client.app.state.device_task_application_service
    reference = service.start("demo", device_task_service.DeviceTaskRequest(
        kind="version", device_uuids=[sw_a.device_uuid], concurrency=1,
    ))
    contacted = []
    monkeypatch.setattr(device_task_service, "_collect_device", lambda *args: contacted.append(args))
    with pytest.raises(BackgroundTaskCancelled):
        get_handler(device_task_service.DEVICE_TASK_TYPE)(
            JobContext.from_job(adapter.jobs[reference.task_id], should_cancel=lambda: True),
        )
    assert contacted == []


def test_task_result_export_completes_public_artifact(runtime):
    from time import monotonic, sleep
    from netconsole.services.device_task_export_service import DeviceTaskExportService
    from netconsole.services.web_artifacts import WebArtifactStore
    from netconsole.services.web_export_process_adapter import WebExportProcessAdapter

    client, adapter, sw_a, _ = runtime
    devices = client.app.state.device_task_application_service
    reference = devices.start("demo", device_task_service.DeviceTaskRequest(
        kind="version", device_uuids=[sw_a.device_uuid],
    ))
    adapter.complete(reference.task_id, {"kind": "version", "items": [
        {"device_uuid": sw_a.device_uuid, "status": "success"},
    ]})
    artifacts = WebArtifactStore(devices.paths, devices.task_service)
    export_adapter = WebExportProcessAdapter(devices.task_service)
    service = DeviceTaskExportService(devices, export_adapter, artifacts)
    export = service.start("demo", reference.task_id)
    deadline = monotonic() + 20
    snapshot = None
    while monotonic() < deadline:
        snapshot = devices.task_service.repository("demo").get(export["task_id"])
        if snapshot and snapshot.result.get("sha256"):
            break
        sleep(0.1)
    assert snapshot.status.value == "COMPLETED", snapshot
    path, name, _ = artifacts.open_public(site_id="demo", artifact_id=snapshot.result["artifact_id"])
    assert path.is_file()
    assert name.endswith(".xlsx")


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
    from netconsole.services.command_template_library import CommandTemplateDefinition

    client, adapter, sw_a, _ = runtime
    definition = {
        "name": "写配置预览", "source": "save force", "command_type": "configuration_change",
    }
    assert client.post("/device-operations/templates", json=definition).status_code == 422
    # Historical records remain readable without going through the current save policy.
    repository = client.app.state.device_task_application_service.template_library("demo").repository
    saved = repository.save(CommandTemplateDefinition(**definition).model_dump(mode="json"),
                            template_id=None, expected_version=None)
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

    read_only = repository.save(CommandTemplateDefinition(**{
        "name": "只读预览", "source": "display version", "command_type": "configuration_change",
    }).model_dump(mode="json"), template_id=None, expected_version=None)
    mismatch = client.post("/device-operations/templates/saved-preview", json={
        "template_id": read_only["template_id"], "version": 1, "values": {},
    })
    assert mismatch.status_code == 422
    assert client.put(f"/device-operations/templates/{saved['template_id']}?expected_version=1",
                      json=definition).status_code == 422


@pytest.mark.parametrize("source", [
    "save force", "{% if enabled %}display version{% else %}save force{% endif %}",
    "{% for port in interfaces %}system-view\n{% endfor %}",
    "{{ command }}", "display {{ query }}", "{# empty #}",
])
def test_saved_template_rejects_unsafe_content_despite_readonly_declaration(runtime, source):
    client, _, _, _ = runtime
    response = client.post("/device-operations/templates", json={
        "name": "静态只读检查", "source": source, "command_type": "read_only",
    })
    assert response.status_code == 422


def test_saved_template_checks_safe_conditions_and_loops(runtime):
    client, _, _, _ = runtime
    response = client.post("/device-operations/templates", json={
        "name": "只读分支", "source": "{% if enabled %}display version\n{% else %}display cpu-usage\n{% endif %}"
        "{% for interface in interfaces %}display transceiver diagnosis interface {{ interface }}\n{% endfor %}",
        "schema_fields": {"enabled": {"type": "boolean"}, "interfaces": {"type": "list"}},
    })
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("kind", ["wireless", "mesh"])
def test_ac_task_parses_existing_formats_without_current_writes(runtime, monkeypatch, kind):
    from netconsole.services import device_task_ac_collection

    client, adapter, sw_a, _ = runtime
    service = client.app.state.device_task_application_service
    database = Database(service.paths.site_db_path("demo"))
    ac = DeviceRepository(database).create(Device(
        name="AC", primary_address="192.0.2.10", device_type="AC", device_vendor="H3C",
    ))
    fixture_root = Path(__file__).parent / "fixtures" / "h3c"
    outputs = {
        "display version": "H3C Comware Software, Version 7.1.070, Alpha 1234",
        "display clock": "12:00:00 Beijing Tue 07/14/2026",
        "display wlan mesh-link ap": "AP name: AP-Online\n"
        "MR-CT 1000-0000-0012 0000-0001-0001 Forwarding 52 120/100\n",
    }
    for command, name in (("display wlan ap all", "display_wlan_ap_all.txt"),
                          ("display wlan ap all address", "display_wlan_ap_all_address.txt"),
                          ("display wlan ap all radio", "display_wlan_ap_all_radio.txt")):
        outputs[command] = (fixture_root / name).read_text(encoding="utf-8")
    executed = []

    def send(connection, command, **kwargs):
        executed.append(command)
        assert command.startswith("display ")
        return SimpleNamespace(output=outputs[command])

    monkeypatch.setattr(device_task_ac_collection, "safe_send_command_with_paging", send)
    monkeypatch.setattr(device_task_ac_collection, "run_netmiko_with_retry",
                        lambda device, execute, **kwargs: execute(None, SimpleNamespace(encoding="utf-8")))
    with database.connect_readonly() as conn:
        before = conn.execute("SELECT COUNT(*) FROM ac_fit_ap_resources").fetchone()[0]
    response = client.post("/device-operations/tasks", json={
        "kind": kind, "device_uuids": [ac.device_uuid, sw_a.device_uuid],
    })
    assert response.status_code == 202, response.text
    job = adapter.jobs[response.json()["task_id"]]
    result = get_handler(job.task_type)(JobContext.from_job(job))
    assert result["items"][0]["status"] == "success", result
    assert result["items"][0]["record_count"] > 0
    assert result["items"][1]["status"] == "skipped"
    assert len(executed) == (4 if kind == "wireless" else 2)
    with database.connect_readonly() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ac_fit_ap_resources").fetchone()[0] == before


@pytest.mark.parametrize("output,expected", [
    ("Total records: 0", "success"), ("unrecognized output", "failed"),
    ("% Unrecognized command", "skipped"),
    ("WMESH is not configured.", "skipped"),
])
def test_mesh_task_empty_and_unparseable_results(runtime, monkeypatch, output, expected):
    from netconsole.services import device_task_ac_collection

    client, _, _, _ = runtime
    service = client.app.state.device_task_application_service
    context = JobContext("mesh", "device_maintenance_collection", {}, None, None, service.paths)
    device = Device(name="AC", device_type="AC", device_vendor="H3C")
    commands = []

    def send(connection, command, **kwargs):
        commands.append(command)
        if command == "display clock":
            return SimpleNamespace(output="12:00:00 Beijing Tue 07/14/2026")
        if command == "display wlan mesh-link ap":
            return SimpleNamespace(output="% Unrecognized command")
        return SimpleNamespace(output=output)

    monkeypatch.setattr(device_task_ac_collection, "safe_send_command_with_paging", send)
    monkeypatch.setattr(device_task_ac_collection, "run_netmiko_with_retry",
                        lambda device, execute, **kwargs: execute(None, SimpleNamespace(encoding="utf-8")))
    result = device_task_ac_collection.collect_ac_task(context, "demo", "mesh", device)
    assert result["status"] == expected
    assert commands == ["display clock", "display wlan mesh-link ap", "display wlan mesh-link ap all"]


@pytest.mark.parametrize("denied_command", ["display wlan ap all address", "display wlan ap all radio"])
def test_wireless_zero_ap_does_not_hide_permission_failure(runtime, monkeypatch, denied_command):
    from netconsole.services import device_task_ac_collection

    client, adapter, _, _ = runtime
    service = client.app.state.device_task_application_service
    ac = DeviceRepository(Database(service.paths.site_db_path("demo"))).create(Device(
        name="AC", device_type="AC", device_vendor="H3C", primary_address="192.0.2.10",
    ))
    executed = []

    def send(connection, command, **kwargs):
        executed.append(command)
        if command == "display version":
            output = "H3C Comware Software, Version 7.1.070, Release 1234"
        elif command == denied_command:
            output = "Permission denied"
        else:
            output = "Total number of APs: 0"
        return SimpleNamespace(output=output)

    monkeypatch.setattr(device_task_ac_collection, "safe_send_command_with_paging", send)
    monkeypatch.setattr(device_task_ac_collection, "run_netmiko_with_retry",
                        lambda device, execute, **kwargs: execute(None, SimpleNamespace(encoding="utf-8")))
    response = client.post("/device-operations/tasks", json={"kind": "wireless", "device_uuids": [ac.device_uuid]})
    assert response.status_code == 202
    job = adapter.jobs[response.json()["task_id"]]
    result = get_handler(job.task_type)(JobContext.from_job(job))
    assert result["business_status"] == "FAILED"
    assert result["items"][0]["status"] == "failed"
    assert denied_command in result["items"][0]["message"]
    assert executed[-1] == denied_command


@pytest.mark.parametrize("known_version", [True, False])
def test_wireless_address_fallback_and_unknown_version_skip(runtime, monkeypatch, known_version):
    from netconsole.services import device_task_ac_collection

    client, _, _, _ = runtime
    service = client.app.state.device_task_application_service
    context = JobContext("wireless", "device_maintenance_collection", {}, None, None, service.paths)
    device = Device(name="AC", device_type="AC", device_vendor="H3C")
    executed = []
    fixture_root = Path(__file__).parent / "fixtures" / "h3c"

    def send(connection, command, **kwargs):
        executed.append(command)
        if command == "display version":
            output = "H3C Comware Software, Version 7.1.070, Alpha 1234" if known_version else "Unknown OS"
        elif command == "display wlan ap all address":
            output = "% Unrecognized command"
        else:
            name = "display_wlan_ap_all_address.txt" if command == "display wlan ap address" else command.replace(" ", "_") + ".txt"
            output = (fixture_root / name).read_text(encoding="utf-8")
        return SimpleNamespace(output=output)

    monkeypatch.setattr(device_task_ac_collection, "safe_send_command_with_paging", send)
    monkeypatch.setattr(device_task_ac_collection, "run_netmiko_with_retry",
                        lambda device, execute, **kwargs: execute(None, SimpleNamespace(encoding="utf-8")))
    result = device_task_ac_collection.collect_ac_task(context, "demo", "wireless", device)
    if known_version:
        assert result["status"] == "success"
        assert executed == ["display version", "display wlan ap all", "display wlan ap all address",
                            "display wlan ap address", "display wlan ap all radio"]
    else:
        assert result["status"] == "skipped"
        assert executed == ["display version"]


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
