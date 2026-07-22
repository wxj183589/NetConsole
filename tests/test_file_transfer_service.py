import paramiko
import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services import command_guard
from netconsole.services.file_transfer_service import (
    FileTransferService,
    RemoteDeviceFile,
    auto_rename_path,
    device_file_dir_name,
    join_remote_path,
    normalize_remote_path,
    parent_remote_path,
    parse_dir_output,
    run_batch_file_download,
    safe_device_name,
)
from netconsole.services.netmiko_connection import ConnectionTarget


@pytest.mark.parametrize(
    "error",
    (
        RuntimeError("Channel closed."),
        EOFError(),
        paramiko.SSHException("EOF during negotiation"),
        paramiko.SSHException("Server connection dropped"),
        paramiko.ChannelException(1, "Administratively prohibited"),
        RuntimeError("The SFTP server is disabled or the SFTP service type is not supported."),
    ),
    ids=(
        "channel-closed",
        "eof",
        "ssh-eof",
        "server-dropped",
        "channel-prohibited",
        "h3c-disabled-message",
    ),
)
def test_open_sftp_failures_are_unavailable_after_auth_even_when_transport_is_inactive(error):
    assert FileTransferService._is_sftp_subsystem_unavailable(
        error,
        failure_stage="open_sftp",
        ssh_authenticated=True,
        transport_active=False,
    )


def test_connect_stage_eof_never_triggers_sftp_auto_enable():
    error = EOFError()

    assert not FileTransferService._is_sftp_subsystem_unavailable(
        error,
        failure_stage="connect_ssh",
        ssh_authenticated=False,
        transport_active=False,
    )
    classified = FileTransferService._classify_connection_error(error, failure_stage="connect_ssh")
    assert classified.code == "DEVICE_FILE_NETWORK_UNREACHABLE"


def test_ambiguous_open_sftp_failure_has_dedicated_negotiation_error():
    error = RuntimeError("unexpected packet type")

    assert not FileTransferService._is_sftp_subsystem_unavailable(
        error,
        failure_stage="open_sftp",
        ssh_authenticated=True,
        transport_active=False,
    )
    classified = FileTransferService._classify_connection_error(error, failure_stage="open_sftp")
    assert classified.code == "DEVICE_FILE_SFTP_NEGOTIATION_FAILED"
    assert str(classified) == "SSH 登录成功，但建立 SFTP 子系统失败。"


def test_file_management_command_context_allows_only_dir_commands():
    assert command_guard.is_command_allowed("dir flash:/", "file_management")
    assert command_guard.is_command_allowed("dir flash:/diagfile/", "file_management")
    assert not command_guard.is_command_allowed("save force", "file_management")
    assert not command_guard.is_command_allowed("delete flash:/a.bin", "file_management")


def test_parse_h3c_dir_output_keeps_supported_files_only():
    output = """
Directory of flash:
   0  -rw-     123456  Jun 01 2026 17:23:05   boot.bin
   1  -rw-        555  Jun 02 2026 08:00:00   config.zip
   2  -rw-       9999  Jun 03 2026 09:00:00   pack.tar.gz
   3  drw-          -  Jun 04 2026 10:00:00   logfile
"""

    files = parse_dir_output(output, "flash:/")

    assert [(item.name, item.size, item.category, item.remote_path) for item in files] == [
        ("boot.bin", 123456, "bin", "flash:/boot.bin"),
        ("config.zip", 555, "zip", "flash:/config.zip"),
        ("pack.tar.gz", 9999, "zip", "flash:/pack.tar.gz"),
    ]
    assert files[0].modified_time == "Jun 01 2026 17:23:05"


def test_parse_diagfile_output_maps_diag_category():
    output = "   0  -rw-     8888  Jun 01 2026 17:23:05   diag_NBDT12HX-WX3540X-AC1_20260601-172305.tar.gz"

    files = parse_dir_output(output, "flash:/diagfile/")

    assert len(files) == 1
    assert files[0].category == "diag"
    assert files[0].remote_path == "flash:/diagfile/diag_NBDT12HX-WX3540X-AC1_20260601-172305.tar.gz"


def test_local_path_uses_device_name_and_uuid_and_avoids_overwrite(tmp_path):
    paths = PathResolver(tmp_path)
    service = FileTransferService("demo", paths)
    uuid = Device.new_uuid()
    device = Device(id=7, device_uuid=uuid, name='核心 交换机1:*?"<>|')
    remote = RemoteDeviceFile("diag_test.tar.gz", "flash:/diagfile/diag_test.tar.gz", 1, None, "diag")

    first = service.local_path_for(device, remote)
    first.write_text("existing", encoding="utf-8")
    second = service.local_path_for(device, remote)

    safe_name = safe_device_name(device.name)
    assert "?" not in safe_name
    assert device_file_dir_name(device) == f"{safe_name}__{uuid}"
    relative_path = first.relative_to(paths.site_dir("demo")).as_posix()
    assert relative_path == f"files/file_manager/downloads/{safe_name}__{uuid}/diag/{safe_name}_diag_test.tar.gz"
    assert "/raw/" not in f"/{relative_path}"
    assert second.name == f"{safe_name}_diag_test_001.tar.gz"


def test_list_files_executes_required_dir_commands(tmp_path, monkeypatch):
    import netconsole.services.file_transfer_service as service_module

    commands: list[str] = []
    disconnected = []

    class FakeConnection:
        def disconnect(self):
            disconnected.append(True)

    def fake_send(_connection, command, **_kwargs):
        commands.append(command)
        if command == "dir flash:/diagfile/":
            return "0 -rw- 10 Jun 01 2026 17:23:05 diag_a.tar.gz"
        return "0 -rw- 20 Jun 01 2026 17:23:05 boot.bin"

    monkeypatch.setattr(service_module, "choose_connection_target", lambda _device: ConnectionTarget("SSH", "hp_comware", "192.0.2.10", 22, "u", "p"))
    monkeypatch.setattr(service_module.netmiko_connection, "ConnectHandler", lambda **_kwargs: FakeConnection())
    monkeypatch.setattr(service_module, "safe_send_command", fake_send)

    files = FileTransferService("demo", PathResolver(tmp_path)).list_files(Device(id=1, device_uuid=Device.new_uuid(), name="SW-A", ip_address="192.0.2.10"))

    assert commands == ["dir flash:/", "dir flash:/diagfile/"]
    assert disconnected == [True]
    assert [item.remote_path for item in files] == ["flash:/boot.bin", "flash:/diagfile/diag_a.tar.gz"]


def test_download_file_prefers_sftp_and_falls_back_to_scp(tmp_path, monkeypatch):
    import netconsole.services.file_transfer_service as service_module

    calls: list[str] = []
    device = Device(id=1, device_uuid=Device.new_uuid(), name="SW-A", ip_address="192.0.2.10")
    remote = RemoteDeviceFile("boot.bin", "flash:/boot.bin", 1, None, "bin")
    service = FileTransferService("demo", PathResolver(tmp_path))

    monkeypatch.setattr(service_module, "choose_connection_target", lambda _device: ConnectionTarget("SSH", "hp_comware", "192.0.2.10", 22, "u", "p"))

    def fake_sftp(_target, _remote_path, _local_path):
        calls.append("sftp")
        raise RuntimeError("sftp failed")

    def fake_scp(_target, _remote_path, local_path):
        calls.append("scp")
        local_path.write_text("downloaded", encoding="utf-8")

    monkeypatch.setattr(service, "_download_sftp", fake_sftp)
    monkeypatch.setattr(service, "_download_scp", fake_scp)

    result = service.download_file(device, remote)

    assert calls == ["sftp", "scp"]
    assert result.success is True
    assert result.local_path == f"files/file_manager/downloads/SW-A__{device.device_uuid}/bin/SW-A_boot.bin"
    assert paths_from_result(tmp_path, "demo", result.local_path).read_text(encoding="utf-8") == "downloaded"


def test_batch_file_download_keeps_failures_isolated():
    devices = [
        Device(id=1, device_uuid=Device.new_uuid(), name="SW-A"),
        Device(id=2, device_uuid=Device.new_uuid(), name="SW-B"),
    ]
    remote = RemoteDeviceFile("boot.bin", "flash:/boot.bin", 1, None, "bin")

    class FakeService:
        def download_file(self, device, remote_file):
            if device.name == "SW-B":
                raise RuntimeError("boom")
            from netconsole.services.file_transfer_service import FileDownloadResult

            return FileDownloadResult(device.id, device.name, remote_file.remote_path, "files/file_manager/downloads/a.bin", "success")

    results = run_batch_file_download([(device, remote) for device in devices], FakeService)

    assert [item.success for item in sorted(results, key=lambda item: item.device_name)] == [True, False]


def test_remote_path_normalization_handles_h3c_paths():
    assert normalize_remote_path("flash:/diagfile/../startup.cfg") == "flash:/startup.cfg"
    assert normalize_remote_path("diagfile/a.tar.gz", current_path="flash:/", root_path="flash:/") == "flash:/diagfile/a.tar.gz"
    assert normalize_remote_path("../x.bin", current_path="flash:/diagfile/", root_path="flash:/") == "flash:/x.bin"
    assert normalize_remote_path("../../x.bin", current_path="flash:/diagfile/", root_path="flash:/") == "flash:/x.bin"
    assert join_remote_path("/flash/", "diagfile/a.tar.gz", "/flash/") == "/flash/diagfile/a.tar.gz"
    assert parent_remote_path("flash:/diagfile/", "flash:/") == "flash:/"
    assert parent_remote_path("flash:/", "flash:/") == "flash:/"


def test_auto_rename_path_uses_single_numeric_suffix_and_preserves_tar_gz(tmp_path):
    target = tmp_path / "diag_NBDT.tar.gz"
    target.write_bytes(b"old")

    renamed = auto_rename_path(target)

    assert renamed.name == "diag_NBDT_1.tar.gz"


def paths_from_result(tmp_path, site_name, local_path):
    return PathResolver(tmp_path).site_dir(site_name) / local_path
