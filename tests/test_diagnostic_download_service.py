from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services import command_guard
from netconsole.services.diagnostic_download_service import DiagnosticDownloadService, run_batch_diagnostic_download, safe_device_name
from netconsole.services.netmiko_connection import ConnectionTarget


def test_diagnostic_command_context_allows_only_required_commands():
    assert command_guard.is_command_allowed("screen-length disable", "diagnostic_download")
    assert command_guard.is_command_allowed("display diagnostic-information", "diagnostic_download")
    assert command_guard.is_command_allowed("n", "diagnostic_download")
    assert not command_guard.is_command_allowed("save force", "diagnostic_download")
    assert not command_guard.is_command_allowed("display current-configuration", "diagnostic_download")


def test_diagnostic_download_writes_file_and_records_result(tmp_path, monkeypatch):
    import netconsole.services.diagnostic_download_service as service_module

    commands: list[str] = []

    class FakeConnection:
        pass

    def fake_send(_connection, command, **_kwargs):
        commands.append(command)
        return f"output:{command}"

    paths = PathResolver(tmp_path)
    monkeypatch.setattr(service_module.netmiko_connection, "run_netmiko_with_retry", lambda device, operation: operation(FakeConnection(), ConnectionTarget("SSH", "hp_comware", "192.0.2.10", 22, "u", "p")))
    monkeypatch.setattr(service_module, "safe_send_command", fake_send)
    monkeypatch.setattr(service_module, "diagnostic_timestamp", lambda: "20260618_203010")

    device = Device(id=7, device_uuid=Device.new_uuid(), name="核心交换机1", ip_address="192.0.2.10")
    result = DiagnosticDownloadService("demo", paths).download(device)

    assert result.success is True
    assert result.device_id == 7
    assert result.device_name == "核心交换机1"
    assert result.timestamp == "20260618_203010"
    assert result.status == "success"
    assert result.file_path == "raw/diagnostic/核心交换机1_diag_20260618_203010.txt"
    assert commands == ["screen-length disable", "display diagnostic-information", "n"]
    text = (paths.site_dir("demo") / result.file_path).read_text(encoding="utf-8")
    assert "output:display diagnostic-information" in text


def test_diagnostic_download_sanitizes_device_name_and_avoids_overwrite(tmp_path):
    paths = PathResolver(tmp_path)
    service = DiagnosticDownloadService("demo", paths)
    device = Device(name='核心 交换机/1:*?"<>|')

    first = service._write_diagnostic_file(device, "20260618_203010", "first")
    second = service._write_diagnostic_file(device, "20260618_203010", "second")

    assert safe_device_name(device.name) == "核心_交换机_1"
    assert first.name == "核心_交换机_1_diag_20260618_203010.txt"
    assert second.name == "核心_交换机_1_diag_20260618_203010_001.txt"
    assert first.read_text(encoding="utf-8") == "first"
    assert second.read_text(encoding="utf-8") == "second"


def test_batch_diagnostic_download_keeps_failures_isolated():
    devices = [
        Device(id=1, device_uuid=Device.new_uuid(), name="SW-A"),
        Device(id=2, device_uuid=Device.new_uuid(), name="SW-B"),
    ]

    class FakeService:
        def download(self, device):
            if device.name == "SW-B":
                raise RuntimeError("boom")
            from netconsole.services.diagnostic_download_service import DiagnosticDownloadResult

            return DiagnosticDownloadResult(device.id, device.name, "20260618_203010", "raw/diagnostic/a.txt", "success")

    results = run_batch_diagnostic_download(devices, FakeService)

    assert [item.success for item in sorted(results, key=lambda item: item.device_name)] == [True, False]
