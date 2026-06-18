import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from netconsole.models.device import Device
from netconsole.core.i18n import I18n
from netconsole.services.h3c_collect_service import CollectDeviceResult
from netconsole.ui.batch_collect_worker import BATCH_CONCURRENCY, BatchCollectWorker, run_batch_collect
from netconsole.ui.dialogs.batch_collect_progress_dialog import BatchCollectProgressDialog
from PySide6.QtWidgets import QApplication


def app():
    return QApplication.instance() or QApplication([])


def test_batch_collect_calls_collector_once_per_device_and_keeps_raw_logs_independent():
    devices = [Device(id=1, name="A", ip_address="10.0.0.1"), Device(id=2, name="B", ip_address="10.0.0.2")]
    calls = []

    def collector(device, site_name):
        calls.append((device.name, site_name))
        return CollectDeviceResult(True, str(device.id), f"run-{device.id}", f"raw/{device.id}.log", True, 1, 1, 1, None, [])

    results = run_batch_collect(devices, "demo", collector=collector, max_workers=2)

    assert sorted(calls) == [("A", "demo"), ("B", "demo")]
    assert {item.raw_log_path for item in results} == {"raw/1.log", "raw/2.log"}
    assert all(item.success for item in results)


def test_batch_collect_single_device_failure_does_not_stop_others():
    devices = [Device(id=1, name="A", ip_address="10.0.0.1"), Device(id=2, name="B", ip_address="10.0.0.2")]

    def collector(device, site_name):
        if device.name == "A":
            raise RuntimeError("connect failed")
        return CollectDeviceResult(True, str(device.id), f"run-{device.id}", f"raw/{device.id}.log", True, 1, 1, 1, None, [])

    results = run_batch_collect(devices, "demo", collector=collector, max_workers=2)

    by_name = {item.device_name: item for item in results}
    assert by_name["A"].success is False
    assert by_name["B"].success is True
    assert by_name["B"].raw_log_path == "raw/2.log"


def test_batch_collect_concurrency_defaults_to_fixed_50():
    app()
    dialog = BatchCollectProgressDialog(I18n("en_US"), 1)
    options = [dialog.concurrency_combo.itemData(index) for index in range(dialog.concurrency_combo.count())]

    assert options == [5, 10, 20, 50, 100]
    assert dialog.concurrency_combo.currentData() == BATCH_CONCURRENCY


def test_batch_collect_concurrency_combo_is_disabled_while_running():
    app()
    dialog = BatchCollectProgressDialog(I18n("en_US"), 1)

    dialog.set_running(True)

    assert dialog.concurrency_combo.isEnabled() is False


def test_batch_collect_worker_uses_start_time_concurrency_only():
    worker = BatchCollectWorker([], "demo", max_workers=50)

    worker.concurrency = 5

    assert worker.max_workers == 50


def test_batch_collect_worker_accepts_max_concurrency_100():
    worker = BatchCollectWorker([], "demo", max_workers=100)

    assert worker.max_workers == 100


def test_batch_collect_worker_accepts_parent_last_concurrency():
    worker = BatchCollectWorker([], "demo", 50, None)

    assert worker.concurrency == 50
