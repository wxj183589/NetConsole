from netconsole.models.device import Device
from netconsole.services.netmiko_connection import ConnectionTestResult
from netconsole.ui.batch_connection_worker import run_batch_connection_tests


def test_batch_connection_tests_call_tester_once_per_device():
    devices = [Device(id=1, name="A", ip_address="10.0.0.1"), Device(id=2, name="B", ip_address="10.0.0.2")]
    calls = []

    def tester(device):
        calls.append(device.name)
        return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", "<SW>", 12)

    results = run_batch_connection_tests(devices, tester=tester, max_workers=2)

    assert sorted(calls) == ["A", "B"]
    assert all(item.success for item in results)
    assert {item.prompt for item in results} == {"<SW>"}


def test_batch_connection_tests_single_failure_does_not_stop_others():
    devices = [Device(id=1, name="A", ip_address="10.0.0.1"), Device(id=2, name="B", ip_address="10.0.0.2")]

    def tester(device):
        if device.name == "A":
            raise RuntimeError("failed")
        return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", "<B>", 10)

    results = run_batch_connection_tests(devices, tester=tester, max_workers=2)
    by_name = {item.device_name: item for item in results}

    assert by_name["A"].success is False
    assert by_name["A"].error_message == "failed"
    assert by_name["B"].success is True
