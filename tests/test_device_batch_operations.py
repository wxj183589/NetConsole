from __future__ import annotations

from netconsole.models.device import Device
from netconsole.services.device_batch_operations import (
    BATCH_COLLECT_DEFAULT_CONCURRENCY,
    BATCH_COLLECT_MAX_CONCURRENCY,
    BATCH_CONNECTION_DEFAULT_CONCURRENCY,
    BATCH_CONNECTION_MAX_CONCURRENCY,
    device_key,
    run_batch_collect,
    run_batch_connection_tests,
)
from netconsole.services.h3c_collect_service import CollectDeviceResult
from netconsole.services.netmiko_connection import ConnectionTestResult


def _devices() -> list[Device]:
    return [
        Device(id=1, name="A", ip_address="10.0.0.1"),
        Device(id=2, name="B", ip_address="10.0.0.2"),
    ]


def test_batch_connection_calls_each_device_and_normalizes_prompt() -> None:
    calls: list[str] = []

    def tester(device: Device) -> ConnectionTestResult:
        calls.append(device.name)
        return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", "screen-length disable\n<SW>", 12, "primary_direct")

    results = run_batch_connection_tests(_devices(), tester=tester, max_workers=2)

    assert sorted(calls) == ["A", "B"]
    assert {item.prompt for item in results} == {"<SW>"}
    assert {item.method for item in results} == {"primary_direct"}


def test_batch_connection_failure_is_isolated() -> None:
    def tester(device: Device) -> ConnectionTestResult:
        if device.name == "A":
            raise RuntimeError("failed")
        return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", "<B>", 10, "backup_direct")

    by_name = {item.device_name: item for item in run_batch_connection_tests(_devices(), tester=tester, max_workers=2)}

    assert by_name["A"].success is False
    assert by_name["A"].error_message == "failed"
    assert by_name["B"].success is True
    assert by_name["B"].method == "backup_direct"


def test_batch_connection_drops_command_echo_prompt() -> None:
    def tester(device: Device) -> ConnectionTestResult:
        prompt = "sc d" if device.name == "A" else "screen-length disable\n<B>"
        return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", prompt, 12, "primary_direct")

    by_name = {item.device_name: item for item in run_batch_connection_tests(_devices(), tester=tester, max_workers=300)}

    assert by_name["A"].prompt is None
    assert by_name["B"].prompt == "<B>"
    assert BATCH_CONNECTION_DEFAULT_CONCURRENCY == 50
    assert BATCH_CONNECTION_MAX_CONCURRENCY == 200


def test_batch_collect_keeps_results_and_failures_independent() -> None:
    def collector(device: Device, site_name: str) -> CollectDeviceResult:
        assert site_name == "demo"
        if device.name == "A":
            raise RuntimeError("connect failed")
        return CollectDeviceResult(True, str(device.id), f"run-{device.id}", f"raw/{device.id}.log", True, 1, 1, 1, None, [])

    by_name = {item.device_name: item for item in run_batch_collect(_devices(), "demo", collector=collector, max_workers=2)}

    assert by_name["A"].success is False
    assert by_name["A"].result_text == "connect failed"
    assert by_name["B"].success is True
    assert by_name["B"].raw_log_path == "raw/2.log"
    assert BATCH_COLLECT_DEFAULT_CONCURRENCY == 20
    assert BATCH_COLLECT_MAX_CONCURRENCY == 50


def test_batch_collect_progress_uses_persistent_device_key() -> None:
    devices = [
        Device(id=1, name="同名设备", ip_address="10.0.0.1"),
        Device(id=2, name="同名设备", ip_address="10.0.0.2"),
    ]
    updates = []

    def collector(device: Device, _site_name: str, progress_callback) -> CollectDeviceResult:
        progress_callback(5, "batch_collect.stage.connecting")
        progress_callback(80, "batch_collect.stage.collecting_command|1|1", "display version")
        return CollectDeviceResult(True, str(device.id), f"run-{device.id}", f"raw/{device.id}.log", True, 1, 1, 1, None, [])

    run_batch_collect(devices, "demo", collector=collector, max_workers=2, progress_callback=updates.append)

    assert {update.device_key for update in updates} == {"1", "2"}
    assert any(update.percent == 5 and update.stage == "batch_collect.stage.connecting" for update in updates)
    assert any(update.command == "display version" for update in updates)
    assert device_key(Device(device_uuid="device-uuid", name="同名", primary_address="10.0.0.1")) == "device-uuid"
