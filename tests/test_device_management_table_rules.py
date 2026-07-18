from pathlib import Path


from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.services.external_terminal import (
    ExternalTerminalConfig,
    TERMINAL_LABELS,
    TERMINAL_SETTING_KEYS,
    _safe_command,
    available_external_terminal_configs,
    build_external_terminal_command,
    build_winscp_command,
    find_winscp_exe,
    launch_external_terminal,
    launch_winscp,
)
from netconsole.services.netmiko_connection import (
    ConnectionTarget,
    choose_connection_target,
)
from netconsole.services.securecrt_session_export import export_securecrt_sessions


def test_securecrt_command_uses_ssh_without_password_by_default():
    device = Device(
        name="SW1",
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        telnet_enabled=0,
    )
    target = choose_connection_target(device)
    args = build_external_terminal_command(
        device, target, "securecrt", r"C:\Tools\SecureCRT.exe"
    )

    assert args == [
        r"C:\Tools\SecureCRT.exe",
        "/SSH2",
        "/P",
        "22",
        "/L",
        "admin",
        "10.0.0.1",
    ]
    assert "secret" not in args


def test_securecrt_command_includes_password_only_when_enabled():
    # Updated behavior: SecureCRT can receive the password when explicitly enabled.
    device = Device(
        name="SW1",
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        telnet_enabled=0,
    )
    target = choose_connection_target(device)
    args = build_external_terminal_command(
        device, target, "securecrt", r"C:\Tools\SecureCRT.exe", include_password=True
    )

    assert "/PASSWORD" in args
    assert "secret" in args
    assert "secret" not in _safe_command(args, device)


def test_external_terminal_missing_exe_returns_failure():
    device = Device(
        name="SW1",
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        telnet_enabled=0,
    )

    result = launch_external_terminal(
        device, ExternalTerminalConfig(exe_path=r"Z:\missing\SecureCRT.exe")
    )

    assert result.success is False
    assert "SecureCRT" in result.message


def test_external_terminal_launch_registers_as_ignored_external_tool(monkeypatch):
    device = Device(
        name="SW1",
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        telnet_enabled=0,
    )
    calls: list[dict[str, object]] = []

    class FakeProcess:
        pid = 1234

    monkeypatch.setattr(
        "netconsole.services.external_terminal.Path.is_file", lambda _self: True
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.shutdown_manager.register_process",
        lambda process, name="", **kwargs: calls.append(
            {"process": process, "name": name, **kwargs}
        ),
    )

    result = launch_external_terminal(
        device, ExternalTerminalConfig(exe_path=r"C:\Tools\SecureCRT.exe")
    )

    assert result.success is True
    assert calls == [
        {
            "process": calls[0]["process"],
            "name": "SecureCRT",
            "kind": "external_tool",
            "shutdown_policy": "ignore",
        }
    ]


def test_securecrt_command_passes_password_and_masks_safe_command():
    device = Device(
        name="SW1",
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        telnet_enabled=0,
    )
    target = choose_connection_target(device)

    args = build_external_terminal_command(
        device, target, "securecrt", r"C:\Tools\SecureCRT.exe", include_password=True
    )

    assert args == [
        r"C:\Tools\SecureCRT.exe",
        "/SSH2",
        "/P",
        "22",
        "/L",
        "admin",
        "10.0.0.1",
        "/PASSWORD",
        "secret",
    ]
    assert "secret" not in _safe_command(args, device)


def test_putty_command_passes_password_and_masks_safe_command():
    device = Device(
        name="SW1",
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        telnet_enabled=0,
    )
    target = choose_connection_target(device)

    args = build_external_terminal_command(
        device, target, "putty", r"C:\Tools\putty.exe", include_password=True
    )

    assert args == [
        r"C:\Tools\putty.exe",
        "-ssh",
        "admin@10.0.0.1",
        "-P",
        "22",
        "-pw",
        "secret",
    ]
    assert "secret" not in _safe_command(args, device)


def test_winscp_command_uses_sftp_and_masks_password():
    device = Device(
        name="SW1",
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="sec ret",
        telnet_enabled=0,
    )
    target = choose_connection_target(device)

    args = build_winscp_command(device, target, r"C:\Tools\WinSCP.exe")

    assert args == [
        r"C:\Tools\WinSCP.exe",
        "sftp://admin:sec%20ret@10.0.0.1:22/",
        "/newinstance",
    ]
    assert "sec ret" not in _safe_command(args, device)
    assert "sec%20ret" not in _safe_command(args, device)

    desktop_args = build_winscp_command(
        device,
        target,
        r"C:\Tools\WinSCP.exe",
        include_password=False,
    )
    assert desktop_args == [
        r"C:\Tools\WinSCP.exe",
        "sftp://admin@10.0.0.1:22/",
        "/newinstance",
    ]


def test_winscp_tunnel_target_uses_localhost_port():
    device = Device(name="SW1", ssh_password="secret")
    target = ConnectionTarget(
        "SSH", "hp_comware", "127.0.0.1", 32022, "admin", "secret", via_tunnel=True
    )

    args = build_winscp_command(device, target, r"C:\Tools\WinSCP.exe")

    assert args[1] == "sftp://admin:secret@127.0.0.1:32022/"


def test_find_winscp_exe_rejects_other_existing_programs(tmp_path, monkeypatch):
    configured = tmp_path / "powershell.exe"
    configured.touch()
    settings = FakeSettings()
    settings.values["external_terminal/winscp_path"] = str(configured)
    monkeypatch.setattr(
        "netconsole.services.external_terminal.shutil.which", lambda _name: None
    )
    monkeypatch.setattr("netconsole.services.external_terminal.WINSCP_COMMON_PATHS", ())

    assert find_winscp_exe(settings) == ""

    winscp = tmp_path / "WinSCP.exe"
    winscp.touch()
    settings.values["external_terminal/winscp_path"] = str(winscp)
    assert find_winscp_exe(settings) == str(winscp)


def test_winscp_tunnel_reports_start_failure_before_return(monkeypatch):
    device = Device(name="SW1", ssh_password="secret")
    target = ConnectionTarget(
        "SSH", "hp_comware", "10.0.0.1", 22, "admin", "secret", via_tunnel=True
    )
    closed: list[bool] = []

    class FakeTunnel:
        def __enter__(self):
            return ConnectionTarget(
                "SSH",
                "hp_comware",
                "127.0.0.1",
                32022,
                "admin",
                "secret",
                via_tunnel=True,
            )

        def __exit__(self, *_args):
            closed.append(True)

    monkeypatch.setattr(
        "netconsole.services.external_terminal.find_winscp_exe",
        lambda _settings: r"C:\Tools\WinSCP.exe",
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.connection_targets",
        lambda _device: [target],
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.prepared_connection_target",
        lambda _target: FakeTunnel(),
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("WinSCP 启动失败")),
    )

    result = launch_winscp(device)

    assert result.success is False
    assert result.message == "WinSCP 启动失败"
    assert closed == [True]


def test_winscp_tunnel_starts_process_before_success(monkeypatch):
    device = Device(name="SW1", ssh_password="secret")
    target = ConnectionTarget(
        "SSH", "hp_comware", "10.0.0.1", 22, "admin", "secret", via_tunnel=True
    )
    calls: list[str] = []

    class FakeTunnel:
        def __enter__(self):
            calls.append("tunnel")
            return ConnectionTarget(
                "SSH",
                "hp_comware",
                "127.0.0.1",
                32022,
                "admin",
                "secret",
                via_tunnel=True,
            )

        def __exit__(self, *_args):
            calls.append("closed")

    class FakeProcess:
        def wait(self):
            calls.append("waited")

    def fake_popen(*_args, **_kwargs):
        calls.append("popen")
        return FakeProcess()

    monkeypatch.setattr(
        "netconsole.services.external_terminal.find_winscp_exe",
        lambda _settings: r"C:\Tools\WinSCP.exe",
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.connection_targets",
        lambda _device: [target],
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.prepared_connection_target",
        lambda _target: FakeTunnel(),
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.subprocess.Popen", fake_popen
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.shutdown_manager.register_process",
        lambda *_args, **_kwargs: calls.append("registered"),
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.shutdown_manager.unregister_process",
        lambda *_args, **_kwargs: calls.append("unregistered"),
    )
    sessions: list[object] = []

    result = launch_winscp(device, sessions=sessions)
    sessions[-1].join(timeout=1)

    assert result.success is True
    assert calls[:3] == ["tunnel", "popen", "registered"]
    assert calls[-3:] == ["waited", "unregistered", "closed"]


def test_external_terminal_configs_ignore_mobaxterm_and_cmd_paths(monkeypatch):
    settings = FakeSettings()
    settings.values.update(
        {
            "external_terminal/securecrt_path": r"C:\Tools\SecureCRT.exe",
            "external_terminal/mobaxterm_path": r"C:\Tools\MobaXterm.exe",
            "external_terminal/cmd_path": r"C:\Windows\System32\cmd.exe",
            "external_terminal/powershell_path": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "external_terminal/legacy_ssh_compatibility": True,
            "external_terminal/legacy_ssh_extended_compatibility": True,
        }
    )
    monkeypatch.setattr(
        "netconsole.services.external_terminal.Path.is_file",
        lambda self: str(self).endswith("SecureCRT.exe"),
    )

    configs = available_external_terminal_configs(settings)

    assert [config.terminal_type for config in configs] == ["securecrt"]
    assert "mobaxterm" not in TERMINAL_LABELS
    assert "cmd" not in TERMINAL_LABELS
    assert "powershell" not in TERMINAL_LABELS
    assert "mobaxterm" not in TERMINAL_SETTING_KEYS
    assert "cmd" not in TERMINAL_SETTING_KEYS
    assert "powershell" not in TERMINAL_SETTING_KEYS


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get_value(self, key, default=None):
        return self.values.get(key, default)

    def set_value(self, key, value):
        self.values[key] = value


def test_securecrt_session_export_creates_group_station_tree(tmp_path):
    device = Device(
        name="SW:1",
        ip_address="10.0.0.1",
        station="Station/A",
        group_id=7,
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        telnet_enabled=0,
    )

    result = export_securecrt_sessions(
        [device], "Site:Demo", tmp_path, group_names={7: "Group*One"}
    )

    assert result.generated == 1
    assert result.skipped == 0
    ini_files = list(result.output_dir.rglob("*.ini"))
    assert len(ini_files) == 1
    assert "Site_Demo" in str(ini_files[0])
    assert "Group_One" in str(ini_files[0])
    assert "Station_A" in str(ini_files[0])
    text = ini_files[0].read_text(encoding="utf-8")
    assert 'S:"Hostname"=10.0.0.1' in text
    assert 'S:"Protocol Name"=SSH2' in text
    assert "secret" not in text


def test_user_visible_i18n_and_ui_text_do_not_contain_question_mark_mojibake():
    root = Path(__file__).parents[1] / "src" / "netconsole"
    checked_files = [
        path
        for path in root.rglob("*.py")
        if path.relative_to(root).parts[:1] in {("core",), ("ui",), ("services",)}
        and path.name not in {"text_encoding.py"}
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in checked_files)

    assert "?????" not in text
    assert "�" not in text
    assert "站点/位置" not in text


class PageRepository:
    def __init__(self):
        self.database = Database(":memory:")
        self.devices = [
            Device(id=1, name="A", primary_address="10.0.0.1"),
            Device(id=2, name="B", primary_address="10.0.0.2"),
        ]

    def list(self, **_kwargs):
        return list(self.devices)

    def get(self, device_id):
        return next(device for device in self.devices if device.id == device_id)

    def delete(self, device_id):
        self.devices = [device for device in self.devices if device.id != device_id]
