from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
from netconsole.services import command_guard
from netconsole.services.config_lifecycle_service import (
    BatchConfigItemResult,
    ConfigLifecycleService,
    ConfigOperationResult,
    compare_config_text,
    clean_config_for_diff,
    device_config_dir_name,
    extract_h3c_configuration_body,
    run_batch_config_download,
    safe_device_name,
)
from netconsole.services.netmiko_connection import ConnectionTarget


def test_config_snapshot_storage_uses_required_site_device_structure(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = ConfigSnapshotRepository(db)
    service = ConfigLifecycleService("demo", db, paths, repository)
    device_uuid = "123e4567-e89b-42d3-a456-426614174000"
    device = Device(id=7, device_uuid=device_uuid, name="核心交换机 1", ip_address="192.0.2.10")

    snapshot = service._write_snapshot(
        device,
        "running",
        "20260618_101200",
        "line 1\n",
        raw_log_path=f"files/config_center/raw_logs/20260618/核心交换机_1__{device_uuid}/run.log",
    )

    assert snapshot.type == "running"
    assert snapshot.timestamp == "20260618_101200"
    assert snapshot.file_path == f"files/config_center/snapshots/核心交换机_1__{device_uuid}/running/20260618_101200.txt"
    assert (paths.site_dir("demo") / snapshot.file_path).read_text(encoding="utf-8") == "line 1\n"
    assert len(snapshot.hash) == 64


def test_device_config_dir_name_uses_safe_device_name_and_unique_id():
    device = Device(id=7, device_uuid="123e4567-e89b-42d3-a456-426614174000", name='核心 交换机/1:*?"<>|')

    assert safe_device_name(device.name) == "核心_交换机_1"
    assert device_config_dir_name(device) == "核心_交换机_1__123e4567-e89b-42d3-a456-426614174000"


def test_config_snapshot_storage_never_overwrites_existing_timestamp(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    service = ConfigLifecycleService("demo", db, paths)
    device = Device(id=7, device_uuid=Device.new_uuid(), name="SW01", ip_address="192.0.2.10")

    first = service._write_snapshot(device, "saved", "20260618_101200", "first")
    second = service._write_snapshot(device, "saved", "20260618_101200", "second")

    assert first.file_path.endswith("saved/20260618_101200.txt")
    assert second.file_path.endswith("saved/20260618_101200_001.txt")
    assert (paths.site_dir("demo") / first.file_path).read_text(encoding="utf-8") == "first"
    assert (paths.site_dir("demo") / second.file_path).read_text(encoding="utf-8") == "second"


def test_config_snapshot_listing_filters_missing_files_as_source_of_truth(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    service = ConfigLifecycleService("demo", db, paths)
    device = Device(id=7, device_uuid=Device.new_uuid(), name="SW01", ip_address="192.0.2.10")
    snapshot = service._write_snapshot(device, "running", "20260618_101200", "line 1")

    assert service.list_device_snapshots(device) == [snapshot]

    (paths.site_dir("demo") / snapshot.file_path).unlink()

    assert service.list_device_snapshots(device) == []


def test_delete_snapshot_deletes_record_and_ignores_missing_or_zero_byte_files(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = ConfigSnapshotRepository(db)
    service = ConfigLifecycleService("demo", db, paths, repository)
    device = Device(id=7, device_uuid=Device.new_uuid(), name="SW01", ip_address="192.0.2.10")
    raw_log_path = "files/config_center/raw_logs/20260618/SW01/run.log"
    snapshot = service._write_snapshot(device, "diff", "20260618_101200", "", raw_log_path=raw_log_path)
    snapshot_path = paths.site_dir("demo") / snapshot.file_path
    raw_log = paths.site_dir("demo") / raw_log_path
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    raw_log.write_text("", encoding="utf-8")
    raw_log.with_suffix(".jsonl").write_text("", encoding="utf-8")

    service.delete_snapshot(snapshot)

    import pytest

    with pytest.raises(KeyError):
        repository.get(int(snapshot.id or 0))
    assert not snapshot_path.exists()
    assert not raw_log.exists()
    assert not raw_log.with_suffix(".jsonl").exists()

    missing_snapshot = service._write_snapshot(device, "diff", "20260618_101201", "")
    (paths.site_dir("demo") / missing_snapshot.file_path).unlink()

    service.delete_snapshot(missing_snapshot)

    with pytest.raises(KeyError):
        repository.get(int(missing_snapshot.id or 0))


def test_extract_h3c_configuration_body_trims_command_echo_and_prompt():
    raw = """display current-configuration
#
 version 9.1.081, Release 1608P01
#
 sysname NBDT12HX-WX3540X-AC1
#
return
<NBDT12HX-WX3540X-AC1>
"""

    assert extract_h3c_configuration_body(raw) == """#
 version 9.1.081, Release 1608P01
#
 sysname NBDT12HX-WX3540X-AC1
#
return"""


def test_extract_h3c_saved_configuration_body_trims_saved_echo_and_prompt():
    raw = """display saved-configuration
#
 version 9.1.081, Release 1608P01
#
return
<NBDT12HX-WX3540X-AC1>
"""

    result = extract_h3c_configuration_body(raw)

    assert result.splitlines()[0] == "#"
    assert result.splitlines()[-1] == "return"
    assert "display saved-configuration" not in result
    assert "<NBDT12HX-WX3540X-AC1>" not in result


def test_snapshot_text_cleans_legacy_running_snapshot_on_read(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    service = ConfigLifecycleService("demo", db, paths)
    device = Device(id=7, device_uuid=Device.new_uuid(), name="SW01", ip_address="192.0.2.10")
    snapshot = service._write_snapshot(device, "running", "20260618_101200", "display current-configuration\n#\nsysname SW01\n#\nreturn\n<SW01>\n")

    text = service.snapshot_text(snapshot)

    assert text == "#\nsysname SW01\n#\nreturn"
    assert "display current-configuration" not in text
    assert "<SW01>" not in text


def test_copy_snapshot_exports_clean_running_text_for_legacy_snapshot(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    service = ConfigLifecycleService("demo", db, paths)
    device = Device(id=7, device_uuid=Device.new_uuid(), name="SW01", ip_address="192.0.2.10")
    snapshot = service._write_snapshot(device, "running", "20260618_101200", "display current-configuration\n#\nsysname SW01\n#\nreturn\n<SW01>\n")
    target = tmp_path / "exported.txt"

    service.copy_snapshot(snapshot, target)

    assert target.read_text(encoding="utf-8") == "#\nsysname SW01\n#\nreturn"


def test_compare_config_text_reports_unified_diff_added_and_removed_lines():
    result = compare_config_text(
        "display current-configuration\nsysname SW01\ninterface GigabitEthernet1/0/1\ndescription uplink\n",
        "display saved-configuration\nsysname SW01\ninterface GigabitEthernet1/0/1\n",
    )

    assert result.added == ["description uplink"]
    assert result.removed == []
    assert result.modified == []
    assert "--- saved" in result.raw_diff
    assert "+++ running" in result.raw_diff
    assert "display current-configuration" not in result.raw_diff
    assert "display saved-configuration" not in result.raw_diff


def test_clean_config_for_diff_trims_cli_noise_and_tail():
    raw = """
<SW01>
display current-configuration
Current configuration is 1234 bytes
#
version 7.1.070
sysname SW01
interface GigabitEthernet1/0/1
 description uplink
return
<SW01>
display saved-configuration
"""

    assert clean_config_for_diff(raw) == "#\nversion 7.1.070\nsysname SW01\ninterface GigabitEthernet1/0/1\n description uplink\nreturn"


def test_save_force_only_executes_save_force_and_writes_saved_status_snapshot(tmp_path, monkeypatch):
    import netconsole.services.config_lifecycle_service as service_module

    commands: list[str] = []
    class FakeConnection:
        pass

    def fake_send(_connection, command, **_kwargs):
        commands.append(command)
        return "Save the current configuration successfully."

    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    monkeypatch.setattr(service_module.netmiko_connection, "run_netmiko_with_retry", lambda device, operation: operation(FakeConnection(), ConnectionTarget("SSH", "hp_comware", "192.0.2.10", 22, "u", "p")))
    monkeypatch.setattr(service_module, "safe_send_command", fake_send)

    device = Device(id=1, device_uuid=Device.new_uuid(), name="SW01", ip_address="192.0.2.10")
    result = ConfigLifecycleService("demo", db, paths).save_force(device)

    assert result.success is True
    assert commands == ["save force"]
    assert [snapshot.type for snapshot in result.snapshots] == ["saved"]
    text = (paths.site_dir("demo") / result.snapshots[0].file_path).read_text(encoding="utf-8")
    assert "save_force_status: success" in text


def test_fetch_configs_is_read_only_and_never_runs_save_force(tmp_path, monkeypatch):
    import netconsole.services.config_lifecycle_service as service_module

    commands: list[str] = []

    class FakeConnection:
        pass

    def fake_send(_connection, command, **_kwargs):
        commands.append(command)
        if command == "display current-configuration":
            return "#\nsysname running\nreturn\n"
        if command == "display saved-configuration":
            return "#\nsysname saved\nreturn\n"
        return ""

    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    monkeypatch.setattr(service_module.netmiko_connection, "run_netmiko_with_retry", lambda device, operation: operation(FakeConnection(), ConnectionTarget("SSH", "hp_comware", "192.0.2.10", 22, "u", "p")))
    monkeypatch.setattr(service_module, "safe_send_command", fake_send)

    device = Device(id=1, device_uuid=Device.new_uuid(), name="SW01", ip_address="192.0.2.10")
    result = ConfigLifecycleService("demo", db, paths).fetch_configs(device)

    assert result.success is True
    assert commands == ["screen-length disable", "display current-configuration", "display saved-configuration"]
    assert "save force" not in commands
    assert [snapshot.type for snapshot in result.snapshots] == ["running", "saved", "diff"]
    running_text = (paths.site_dir("demo") / result.snapshots[0].file_path).read_text(encoding="utf-8")
    saved_text = (paths.site_dir("demo") / result.snapshots[1].file_path).read_text(encoding="utf-8")
    assert running_text.splitlines()[0] == "#"
    assert running_text.splitlines()[-1] == "return"
    assert saved_text.splitlines()[0] == "#"
    assert saved_text.splitlines()[-1] == "return"


def test_compare_latest_running_between_devices_uses_snapshot_files(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    service = ConfigLifecycleService("demo", db, paths)
    device_a = Device(id=1, device_uuid="123e4567-e89b-42d3-a456-426614174001", name="SW-A")
    device_b = Device(id=2, device_uuid="123e4567-e89b-42d3-a456-426614174002", name="SW-B")
    service._write_snapshot(device_a, "running", "20260618_101200", "sysname SW-A\nvlan 10\n")
    service._write_snapshot(device_b, "running", "20260618_101200", "sysname SW-B\nvlan 20\n")

    result = service.compare_latest_running_between_devices(device_a, device_b)

    assert result.device_a == "SW-A"
    assert result.device_b == "SW-B"
    assert "-vlan 10" in result.diff.raw_diff
    assert "+vlan 20" in result.diff.raw_diff
    assert "vlan 10" in result.structure_diff["only_in_a"]
    assert "vlan 20" in result.structure_diff["only_in_b"]


def test_batch_config_download_keeps_failures_isolated():
    devices = [
        Device(id=1, device_uuid="123e4567-e89b-42d3-a456-426614174001", name="SW-A"),
        Device(id=2, device_uuid="123e4567-e89b-42d3-a456-426614174002", name="SW-B"),
    ]

    class FakeService:
        def fetch_configs(self, device):
            if device.name == "SW-B":
                raise RuntimeError("boom")
            return ConfigOperationResult(True, device.device_uuid, "20260618_101200", [])

    results = run_batch_config_download(devices, FakeService)

    assert [item.success for item in sorted(results, key=lambda item: item.device_name)] == [True, False]


def test_batch_zip_export_uses_current_results_structure(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    service = ConfigLifecycleService("demo", db, paths)
    device = Device(id=1, device_uuid="123e4567-e89b-42d3-a456-426614174001", name="SW-A")
    raw_log_path = "files/config_center/raw_logs/20260618/SW-A/run.log"
    running = service._write_snapshot(device, "running", "20260618_101200", "sysname SW-A\n", raw_log_path=raw_log_path)
    diff = service._write_snapshot(device, "diff", "20260618_101200", "--- saved\n+++ running\n", raw_log_path=raw_log_path)
    raw_log = paths.site_dir("demo") / raw_log_path
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    raw_log.write_text("raw", encoding="utf-8")
    raw_log.with_suffix(".jsonl").write_text("{}", encoding="utf-8")
    target = tmp_path / "batch.zip"

    service.export_batch_zip(
        [
            BatchConfigItemResult("SW-A", str(device.device_uuid), True, "ok", "20260618_101200", 2, 10, [running, diff], str(raw_log)),
            BatchConfigItemResult("SW-B", "uuid-b", False, "failed", "", 0, 10, [], error_message="timeout"),
        ],
        target,
    )

    import zipfile

    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "SW-A/running_20260618_101200.txt" in names
        assert "SW-A/diff_20260618_101200.diff" in names
        assert "SW-A/logs/run.log" in names
        assert "SW-A/logs/run.jsonl" in names
        assert "failed_devices.txt" in names


def test_config_lifecycle_command_context_allows_only_required_commands():
    assert command_guard.is_command_allowed("screen-length disable", "config_lifecycle")
    assert command_guard.is_command_allowed("save force", "config_lifecycle")
    assert command_guard.is_command_allowed("display current-configuration", "config_lifecycle")
    assert command_guard.is_command_allowed("display saved-configuration", "config_lifecycle")
    assert not command_guard.is_command_allowed("display interface", "config_lifecycle")
