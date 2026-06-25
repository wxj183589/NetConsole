import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from netconsole.models.device import Device
from netconsole.services.netmiko_connection import ConnectionTestResult
from netconsole.core.i18n import I18n
from netconsole.ui.batch_connection_worker import (
    BATCH_CONNECTION_DEFAULT_CONCURRENCY,
    BATCH_CONNECTION_MAX_CONCURRENCY,
    BatchConnectionTestWorker,
    run_batch_connection_tests,
)
from netconsole.ui.dialogs.batch_connection_test_progress_dialog import BatchConnectionTestProgressDialog
from PySide6.QtWidgets import QApplication


def app():
    return QApplication.instance() or QApplication([])


def test_batch_connection_tests_call_tester_once_per_device():
    devices = [Device(id=1, name="A", ip_address="10.0.0.1"), Device(id=2, name="B", ip_address="10.0.0.2")]
    calls = []

    def tester(device):
        calls.append(device.name)
        return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", "<SW>", 12, "primary_direct")

    results = run_batch_connection_tests(devices, tester=tester, max_workers=2)

    assert sorted(calls) == ["A", "B"]
    assert all(item.success for item in results)
    assert {item.prompt for item in results} == {"<SW>"}
    assert {item.method for item in results} == {"primary_direct"}


def test_batch_connection_tests_single_failure_does_not_stop_others():
    devices = [Device(id=1, name="A", ip_address="10.0.0.1"), Device(id=2, name="B", ip_address="10.0.0.2")]

    def tester(device):
        if device.name == "A":
            raise RuntimeError("failed")
        return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", "<B>", 10, "backup_direct")

    results = run_batch_connection_tests(devices, tester=tester, max_workers=2)
    by_name = {item.device_name: item for item in results}

    assert by_name["A"].success is False
    assert by_name["A"].error_message == "failed"
    assert by_name["A"].method == ""
    assert by_name["B"].success is True
    assert by_name["B"].method == "backup_direct"


def test_batch_connection_concurrency_defaults_to_50_and_allows_200():
    app()
    dialog = BatchConnectionTestProgressDialog(I18n("en_US"), 1)
    options = [dialog.concurrency_combo.itemData(index) for index in range(dialog.concurrency_combo.count())]

    assert dialog.concurrency_combo.currentData() == BATCH_CONNECTION_DEFAULT_CONCURRENCY
    assert options == [10, 20, 50, 100, 200]
    assert 100 in options
    assert 200 in options


def test_batch_connection_worker_caps_concurrency_at_200():
    worker = BatchConnectionTestWorker([], max_workers=300)

    assert worker.max_workers == BATCH_CONNECTION_MAX_CONCURRENCY


def test_batch_connection_results_filter_command_echo_prompt():
    devices = [Device(id=1, name="A", ip_address="10.0.0.1"), Device(id=2, name="B", ip_address="10.0.0.2")]

    def tester(device):
        if device.name == "A":
            return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", "sc d", 12, "primary_direct")
        return ConnectionTestResult(True, "SSH", device.ip_address, 22, "ok", "screen-length disable\n<B>", 12, "primary_direct")

    results = run_batch_connection_tests(devices, tester=tester, max_workers=300)
    by_name = {item.device_name: item for item in results}

    assert by_name["A"].prompt is None
    assert by_name["B"].prompt == "<B>"
    assert all(item.prompt != "sc d" for item in results)
