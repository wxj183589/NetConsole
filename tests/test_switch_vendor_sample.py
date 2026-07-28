from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.job_center.job_context import (
    BackgroundTaskCancelled,
    JobContext,
)
from netconsole.services.netmiko_connection import CommandCancelled
from netconsole.services.rail_transit import switch_vendor_sample_job
from netconsole.services.rail_transit.switch_vendor_sample import (
    SAMPLE_ARCHIVE_FILES,
    collect_switch_vendor_sample,
)


FIXTURES = Path(__file__).parent / "fixtures" / "zte"


class _FakeConnection:
    def __init__(self, outputs: dict[str, str | Exception]) -> None:
        self.outputs = outputs
        self.commands: list[str] = []
        self.disconnected = False

    def send_command_timing(self, command: str, **_kwargs) -> str:
        self.commands.append(command)
        output = self.outputs.get(command, "Invalid command")
        if isinstance(output, Exception):
            raise output
        return output

    def find_prompt(self) -> str:
        return "ZXR10#"

    def disconnect(self) -> None:
        self.disconnected = True


def _device() -> Device:
    return Device(
        device_uuid="11111111-1111-4111-8111-111111111111",
        name="ZTE-SW-01",
        device_vendor="ZTE",
        device_type="SW",
        primary_address="192.0.2.10",
        ssh_enabled=1,
        ssh_username="collector",
        ssh_password="fixture-secret",
    )


def test_switch_vendor_sample_writes_fixed_archive_and_redacts_credentials(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "zte-adapter-sample.zip"
    version = (FIXTURES / "zte_5960x_show_version.txt").read_text(
        encoding="utf-8"
    )
    connection = _FakeConnection(
        {
            "show version": f"{version}\nfixture-secret",
            "show lldp entry": "Invalid command",
            "show lldp neighbor": "No neighbor",
            "show lldp neighbors": "No neighbor",
            "show lldp config": "LLDP is enabled",
        }
    )

    result = collect_switch_vendor_sample(
        _device(),
        connection,
        output_path=output_path,
        vendor="ZTE",
        command_profile="zte_zxr10_5960x_es_v2",
        requested_commands=("device_version", "lldp_global"),
    )

    assert result.status == "PARTIAL_SUCCESS"
    assert result.unsupported_count == 1
    assert output_path.is_file()
    with ZipFile(output_path) as archive:
        assert tuple(archive.namelist()) == SAMPLE_ARCHIVE_FILES
        payload = {
            name: archive.read(name).decode("utf-8")
            for name in archive.namelist()
        }
    combined = "\n".join(payload.values())
    assert "fixture-secret" not in combined
    assert "***" in payload["version.txt"]
    manifest = json.loads(payload["manifest.json"])
    statuses = json.loads(payload["command-status.json"])
    assert manifest["vendor"] == "ZTE"
    assert manifest["verification_status"] == "DOCUMENT_SAMPLE_ONLY"
    assert manifest["parser_version"]
    assert any(item["unsupported"] for item in statuses)
    assert any(item["success"] for item in statuses)


def test_switch_vendor_sample_records_timeout_without_losing_other_outputs(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "timeout.zip"
    version = (FIXTURES / "zte_5960x_show_version.txt").read_text(
        encoding="utf-8"
    )
    result = collect_switch_vendor_sample(
        _device(),
        _FakeConnection(
            {
                "show version": version,
                "show interface brief": TimeoutError("fixture timeout"),
            }
        ),
        output_path=output_path,
        vendor="ZTE",
        command_profile="zte_zxr10_5960x_es_v2",
        requested_commands=("device_version", "interface_brief"),
    )

    assert result.status == "PARTIAL_SUCCESS"
    assert result.success_count == 1
    assert result.timeout_count == 1
    with ZipFile(output_path) as archive:
        statuses = json.loads(archive.read("command-status.json"))
    assert statuses[1]["timeout"] is True
    assert statuses[1]["error_message"] == "命令执行超时"


def test_switch_vendor_sample_rejects_non_zte_adapter(tmp_path: Path) -> None:
    device = Device(
        device_uuid="33333333-3333-4333-8333-333333333333",
        name="H3C-SW-01",
        device_vendor="H3C",
        device_type="SW",
    )

    with pytest.raises(ValueError, match="仅支持 ZTE"):
        collect_switch_vendor_sample(
            device,
            _FakeConnection({}),
            output_path=tmp_path / "h3c.zip",
            vendor="H3C",
            command_profile="h3c_comware_trackside_v1",
        )


def test_switch_vendor_sample_cancellation_removes_partial_archive(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "cancelled.zip"

    with pytest.raises(CommandCancelled):
        collect_switch_vendor_sample(
            _device(),
            _FakeConnection({"show version": "unused"}),
            output_path=output_path,
            vendor="ZTE",
            command_profile="zte_zxr10_5960x_es_v2",
            requested_commands=("device_version",),
            cancel_check=lambda: True,
        )

    assert not output_path.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_switch_vendor_sample_job_disconnects_when_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(_device())
    output_path = (
        paths.trackside_ap_outputs_dir("demo")
        / "vendor_samples"
        / "cancelled.zip"
    )
    connection = _FakeConnection({})

    monkeypatch.setattr(
        switch_vendor_sample_job,
        "choose_connection_target",
        lambda _device: object(),
    )

    @contextmanager
    def prepared(_target):
        yield object()

    monkeypatch.setattr(
        switch_vendor_sample_job,
        "prepared_connection_target",
        prepared,
    )
    monkeypatch.setattr(
        switch_vendor_sample_job,
        "build_netmiko_params",
        lambda _target: {},
    )
    monkeypatch.setattr(
        switch_vendor_sample_job.netmiko_connection,
        "ConnectHandler",
        lambda **_params: connection,
    )
    cancel_checks = iter((False, True, True))
    context = JobContext(
        job_id="sample-job",
        task_type="switch_vendor_sample_collect",
        params={
            "site_name": "demo",
            "device_uuid": device.device_uuid,
            "artifact_output_path": str(output_path),
            "vendor": "ZTE",
            "command_profile": "zte_zxr10_5960x_es_v2",
            "requested_commands": ["device_version"],
        },
        progress_callback=None,
        should_cancel=lambda: next(cancel_checks, True),
        paths=paths,
    )

    with pytest.raises(BackgroundTaskCancelled):
        switch_vendor_sample_job.run_switch_vendor_sample_collect(context)

    assert connection.disconnected is True
    assert not output_path.exists()
