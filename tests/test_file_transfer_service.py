from contextlib import nullcontext
import io
from pathlib import Path
from types import SimpleNamespace

import paramiko
import pytest

import netconsole.services.file_transfer_service as service_module
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services import command_guard
from netconsole.services.file_transfer_service import (
    FileTransferConnectionError,
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
    assert classified.code == "DEVICE_FILE_DIRECT_UNREACHABLE"


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


def test_device_file_ssh_connect_uses_five_second_timeouts(tmp_path, monkeypatch):
    connect_kwargs: list[dict[str, object]] = []
    socket_calls: list[tuple[tuple[str, int], float]] = []

    class FakeSocket:
        def close(self):
            pass

    class FakeClient:
        def connect(self, **kwargs):
            connect_kwargs.append(kwargs)

        def close(self):
            pass

    def fake_create_connection(address, *, timeout):
        socket_calls.append((address, timeout))
        return FakeSocket()

    monkeypatch.setattr(paramiko, "SSHClient", FakeClient)
    monkeypatch.setattr(service_module, "install_managed_host_key_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service_module.socket, "create_connection", fake_create_connection)
    service = FileTransferService(
        "demo",
        PathResolver(tmp_path),
        strict_host_keys=True,
    )
    target = ConnectionTarget(
        protocol="ssh",
        device_type="hp_comware",
        host="127.0.0.1",
        port=10022,
        username="admin",
        password="secret",
        method="tunnel1_backup",
        via_tunnel=True,
        target_role="backup",
        tunnel_label="tunnel1",
    )

    service._connect_ssh_client(
        target,
        key_host="backup.internal",
        key_port=22,
    )

    assert socket_calls == [(("127.0.0.1", 10022), 5.0)]
    assert connect_kwargs[0]["timeout"] == 5.0
    assert connect_kwargs[0]["banner_timeout"] == 5.0
    assert connect_kwargs[0]["auth_timeout"] == 5.0


def test_device_file_site_relay_uses_target_channel_without_direct_socket(
    tmp_path,
    monkeypatch,
):
    connect_kwargs: list[dict[str, object]] = []
    policy_args: list[tuple[str, int, str]] = []

    class FakeChannel:
        def close(self):
            return None

    class FakeClient:
        def connect(self, **kwargs):
            connect_kwargs.append(kwargs)

        def close(self):
            return None

    class FakeRelayConfig:
        enabled = True
        host = "jump.internal"
        port = 2222

    class FakeRelayService:
        def load(self, _site):
            return FakeRelayConfig()

        def open_target_channel(self, site_id, host, port):
            assert site_id == "demo"
            assert (host, port) == ("target.internal", 22)
            return channel

    channel = FakeChannel()
    monkeypatch.setattr(paramiko, "SSHClient", FakeClient)

    def fake_install(_client, _trust, host, port, *, role, host_key_policy):
        policy_args.append((host, port, role))
        assert host_key_policy == "AUTO_REPLACE"

    monkeypatch.setattr(service_module, "install_managed_host_key_policy", fake_install)
    monkeypatch.setattr(
        service_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: pytest.fail("Relay ON must not open a direct socket"),
    )
    service = FileTransferService(
        "demo",
        PathResolver(tmp_path),
        relay_service=FakeRelayService(),
    )
    target = ConnectionTarget(
        protocol="ssh",
        device_type="hp_comware",
        host="target.internal",
        port=22,
        username="admin",
        password="secret",
        method="tunnel1_backup",
        via_tunnel=True,
        target_role="backup",
        tunnel_label="tunnel1",
    )

    service._connect_ssh_client(target, via_site_relay=True)

    assert policy_args == [("target.internal", 22, "target")]
    assert connect_kwargs[0]["hostname"] == "target.internal"
    assert connect_kwargs[0]["port"] == 22
    assert connect_kwargs[0]["sock"] is channel


def test_device_file_listing_site_relay_does_not_prepare_legacy_tunnel(
    tmp_path,
    monkeypatch,
):
    target = ConnectionTarget(
        protocol="ssh",
        device_type="hp_comware",
        host="target.internal",
        port=22,
        username="admin",
        password="secret",
        method="tunnel1_backup",
        via_tunnel=True,
        target_role="backup",
        tunnel_label="tunnel1",
    )
    captured: list[dict[str, object]] = []

    class FakeRelayConfig:
        enabled = True
        host = "jump.internal"
        port = 2222

    class FakeRelayService:
        def load(self, _site):
            return FakeRelayConfig()

    class FakeConnection:
        def disconnect(self):
            return None

    service = FileTransferService(
        "demo",
        PathResolver(tmp_path),
        relay_service=FakeRelayService(),
    )
    device = Device(name="SW", primary_address="target.internal", ssh_enabled=1)
    monkeypatch.setattr(service_module, "connection_targets", lambda _device: [target])
    monkeypatch.setattr(
        service_module.netmiko_connection,
        "ConnectHandler",
        lambda **params: (captured.append(params) or FakeConnection()),
    )
    monkeypatch.setattr(
        service_module.netmiko_connection,
        "ssh_connection_context",
        lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        service_module,
        "safe_send_command",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        service_module,
        "_file_netmiko_params",
        lambda *_args, **_kwargs: pytest.fail("Relay ON must not prepare a legacy tunnel"),
    )

    assert service.list_files(device) == []
    assert captured[0]["host"] == "target.internal"
    assert "sock" not in captured[0]


@pytest.mark.parametrize(
    ("successful_method", "expected_methods"),
    (
        (
            "tunnel1_backup",
            [
                "primary_direct",
                "backup_direct",
                "tunnel1_primary",
                "tunnel1_backup",
            ],
        ),
        (
            "tunnel2_backup",
            [
                "primary_direct",
                "backup_direct",
                "tunnel1_primary",
                "tunnel1_backup",
                "tunnel2_primary",
                "tunnel2_backup",
            ],
        ),
    ),
)
def test_file_transfer_falls_back_across_target_and_tunnel_combinations(
    tmp_path,
    monkeypatch,
    successful_method,
    expected_methods,
):
    attempts: list[str] = []

    class FakeSftp:
        def listdir_attr(self, path):
            if path == "flash:/":
                return []
            raise RuntimeError("missing root")

        def close(self):
            pass

    class FakeClient:
        def open_sftp(self):
            return FakeSftp()

        def close(self):
            pass

    class FakeTunnelSession:
        local_host = "127.0.0.1"
        local_port = 10022
        forward_error = None

        def close(self):
            pass

    tunnel_timeouts: list[float] = []

    class FakeTunnelManager:
        def __init__(self, **kwargs):
            tunnel_timeouts.append(kwargs["connect_timeout_seconds"])

        @staticmethod
        def open_tunnel(*_args, **_kwargs):
            return FakeTunnelSession()

    service = FileTransferService(
        "demo",
        PathResolver(tmp_path),
        strict_host_keys=True,
    )

    def fake_connect(target, **_kwargs):
        attempts.append(target.method)
        if target.method != successful_method:
            raise OSError("unreachable")
        return FakeClient()

    monkeypatch.setattr(service, "_connect_ssh_client", fake_connect)
    monkeypatch.setattr(service_module, "TunnelManager", FakeTunnelManager)
    device = Device(
        name="MR",
        primary_address="primary.internal",
        backup_address="backup.internal",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="device-password",
        tunnel1_host="jump1",
        tunnel1_username="jump",
        tunnel1_password="jump-password",
        tunnel2_host="jump2",
        tunnel2_username="jump",
        tunnel2_password="jump-password",
    )

    assert service.connect(device) == "flash:/"
    assert attempts == expected_methods
    assert service.successful_target is not None
    assert service.successful_target.method == successful_method
    assert tunnel_timeouts
    assert set(tunnel_timeouts) == {5.0}


def test_file_transfer_reports_all_failed_connection_paths_without_secrets(
    tmp_path,
    monkeypatch,
):
    class FakeTunnelSession:
        local_host = "127.0.0.1"
        local_port = 10022
        forward_error = None

        def close(self):
            pass

    service = FileTransferService(
        "demo",
        PathResolver(tmp_path),
        strict_host_keys=True,
    )
    monkeypatch.setattr(
        service,
        "_connect_ssh_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unreachable")),
    )
    monkeypatch.setattr(
        "netconsole.services.file_transfer_service.TunnelManager.open_tunnel",
        lambda *_args, **_kwargs: FakeTunnelSession(),
    )
    device = Device(
        name="MR",
        primary_address="primary.internal",
        backup_address="backup.internal",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="device-password",
        tunnel1_host="jump1",
        tunnel1_username="jump",
        tunnel1_password="jump-password",
        tunnel2_host="jump2",
        tunnel2_username="jump",
        tunnel2_password="jump-password",
    )

    with pytest.raises(FileTransferConnectionError) as excinfo:
        service.connect(device)

    attempts = excinfo.value.details["attempts"]
    assert [item["connection_method"] for item in attempts] == [
        "primary_direct",
        "backup_direct",
        "tunnel1_primary",
        "tunnel1_backup",
        "tunnel2_primary",
        "tunnel2_backup",
    ]
    assert all(item["success"] is False for item in attempts)
    assert "device-password" not in str(attempts)
    assert "jump-password" not in str(attempts)
    public_attempts = service.attempt_summaries
    public_attempts[0]["message"] = "changed"
    assert service.attempt_summaries[0]["message"] != "changed"


def test_download_failure_has_stable_code_and_cleans_partial_file(
    tmp_path,
    monkeypatch,
):
    class FakeSftp:
        @staticmethod
        def stat(_path):
            raise RuntimeError("read failed device-password")

    events: list[tuple[str, str]] = []
    service = FileTransferService("demo", PathResolver(tmp_path))
    service._sftp = FakeSftp()
    service._root_path = "flash:/"
    service._current_path = "flash:/"
    service._device = Device(
        id=1,
        device_uuid=Device.new_uuid(),
        name="MR",
        ssh_password="device-password",
    )
    service._successful_target = ConnectionTarget(
        protocol="ssh",
        device_type="hp_comware",
        host="backup.internal",
        port=22,
        username="admin",
        password="device-password",
        method="tunnel1_backup",
        via_tunnel=True,
        target_role="backup",
        tunnel_label="tunnel1",
    )
    monkeypatch.setattr(
        "netconsole.services.file_transfer_service.DOWNLOAD_STABLE_WAIT_SECONDS",
        0,
    )
    monkeypatch.setattr(
        "netconsole.services.file_transfer_service.app_logger.log_error",
        lambda event, message: events.append((event, message)),
    )
    destination = tmp_path / "download.bin"

    with pytest.raises(FileTransferConnectionError) as excinfo:
        service.download("flash:/download.bin", destination)

    assert excinfo.value.code == "DEVICE_FILE_DOWNLOAD_FAILED"
    assert excinfo.value.details["failure_stage"] == "download"
    assert not destination.exists()
    assert not destination.with_name("download.bin.part").exists()
    assert events[0][0] == "DEVICE_FILE_DOWNLOAD_FAILED"
    assert "connection_method=tunnel1_backup" in events[0][1]
    assert "target_role=backup" in events[0][1]
    assert "failure_stage=download" in events[0][1]
    assert "device-password" not in events[0][1]


def test_download_hashes_complete_part_before_atomic_publish(tmp_path, monkeypatch):
    payload = b"verified device file"
    target = tmp_path / "download.bin"
    target.write_bytes(b"previous file")
    observed: list[tuple[str, bytes]] = []
    service = FileTransferService("demo", PathResolver(tmp_path))

    class FakeSftp:
        @staticmethod
        def stat(_path):
            return SimpleNamespace(st_size=len(payload))

        @staticmethod
        def open(_path, _mode):
            return io.BytesIO(payload)

    def record_hash(path: Path) -> str:
        observed.append((path.name, target.read_bytes()))
        return "verified"

    service._sftp = FakeSftp()
    service._root_path = "flash:/"
    service._current_path = "flash:/"
    monkeypatch.setattr(service_module, "DOWNLOAD_STABLE_WAIT_SECONDS", 0)
    monkeypatch.setattr(service_module, "file_sha256", record_hash)

    service.download("flash:/download.bin", target)

    assert observed == [("download.bin.part", b"previous file"), ("download.bin", payload)]
    assert target.read_bytes() == payload
    assert not target.with_name("download.bin.part").exists()


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

    def fake_scp(_target, _remote_path, local_path, *, device_uuid=""):
        calls.append("scp")
        local_path.write_text("downloaded", encoding="utf-8")

    monkeypatch.setattr(service, "_download_sftp", fake_sftp)
    monkeypatch.setattr(service, "_download_scp", fake_scp)

    result = service.download_file(device, remote)

    assert calls == ["sftp", "scp"]
    assert result.success is True
    assert result.local_path == f"files/file_manager/downloads/SW-A__{device.device_uuid}/bin/SW-A_boot.bin"
    assert paths_from_result(tmp_path, "demo", result.local_path).read_text(encoding="utf-8") == "downloaded"


def test_scp_fallback_keeps_site_relay_route_and_canonical_identity(tmp_path, monkeypatch):
    import netmiko

    captured: dict[str, object] = {}
    logs: list[tuple[str, str]] = []
    destination = tmp_path / "relay-scp.bin"
    service = FileTransferService(
        "physical-site",
        PathResolver(tmp_path),
        relay_site_id="stable-site",
        route_source="download_worker",
    )
    target = ConnectionTarget(
        "SSH",
        "hp_comware",
        "target.internal",
        2222,
        "device",
        "device-password",
        method="backup_direct",
        via_tunnel=True,
        tunnel=SimpleNamespace(host="wrong-device-tunnel", port=2200),
        target_role="backup",
        tunnel_label="tunnel1",
    )

    class FakeConnection:
        def disconnect(self):
            pass

    def fake_connect(**params):
        captured.update(params)
        return FakeConnection()

    def fake_file_transfer(_connection, *, dest_file, **_kwargs):
        captured["dest_file"] = str(dest_file)
        Path(dest_file).write_text("relay-scp", encoding="utf-8")

    monkeypatch.setattr(service, "_site_relay_enabled", lambda: True)
    monkeypatch.setattr(service, "_relay_jump_label", lambda: "relay.internal:22")
    monkeypatch.setattr(service_module.netmiko_connection, "ConnectHandler", fake_connect)
    monkeypatch.setattr(netmiko, "file_transfer", fake_file_transfer)
    monkeypatch.setattr(
        service_module.app_logger,
        "log_info",
        lambda event, detail="", **_kwargs: logs.append((event, detail)),
    )

    service._download_scp(target, "flash:/boot.bin", destination, device_uuid="device-1")

    assert destination.read_text(encoding="utf-8") == "relay-scp"
    assert Path(str(captured["dest_file"])).name == "relay-scp.bin.part"
    assert not destination.with_name("relay-scp.bin.part").exists()
    assert captured["host"] == "target.internal"
    assert captured["port"] == 2222
    assert captured["_netconsole_site_id"] == "stable-site"
    assert "sock" not in captured
    route_log = next(detail for event, detail in logs if event == "FILE_TRANSFER_ROUTE_SELECTED")
    assert "route_mode=site_relay" in route_log
    assert "jump=relay.internal:22" in route_log
    assert "source=download_worker" in route_log


def test_download_retries_keep_the_same_site_relay_identity(tmp_path, monkeypatch):
    device = Device(id=1, device_uuid=Device.new_uuid(), name="SW-A", ip_address="192.0.2.10")
    remote = RemoteDeviceFile("boot.bin", "flash:/boot.bin", 1, None, "bin")
    service = FileTransferService(
        "physical-site",
        PathResolver(tmp_path),
        relay_site_id="stable-site",
        route_source="download_worker",
    )
    seen: list[str] = []
    scp_attempts = 0

    def fake_sftp(_target, _remote_path, _local_path):
        seen.append(service.relay_site_id)
        raise RuntimeError("relay target temporarily unavailable")

    def fake_scp(_target, _remote_path, local_path, *, device_uuid=""):
        nonlocal scp_attempts
        seen.append(service.relay_site_id)
        scp_attempts += 1
        if scp_attempts < 3:
            raise RuntimeError("relay retry")
        local_path.write_text("downloaded", encoding="utf-8")

    monkeypatch.setattr(service, "_download_sftp", fake_sftp)
    monkeypatch.setattr(service, "_download_scp", fake_scp)
    monkeypatch.setattr(service_module, "DOWNLOAD_STABLE_WAIT_SECONDS", 0)

    result = service.download_file(device, remote)

    assert result.success is True
    assert scp_attempts == 3
    assert seen == ["stable-site"] * 6


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
