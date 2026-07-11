import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.services.h3c_collect_service import CollectDeviceResult
from netconsole.ui.batch_collect_worker import (
    BATCH_COLLECT_DEFAULT_CONCURRENCY,
    BATCH_COLLECT_MAX_CONCURRENCY,
    BatchCollectItemResult,
    BatchCollectProgressUpdate,
    BatchCollectWorker,
    device_key,
    run_batch_collect,
)
from netconsole.ui.dialogs.batch_collect_progress_dialog import BatchCollectProgressDialog
from PySide6.QtWidgets import QApplication, QProgressBar


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
    assert {item.device_key for item in results} == {"1", "2"}
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


def test_batch_collect_progress_uses_device_key_and_service_callback():
    devices = [Device(id=1, name="同名设备", ip_address="10.0.0.1"), Device(id=2, name="同名设备", ip_address="10.0.0.2")]
    updates = []

    def collector(device, site_name, progress_callback):
        progress_callback(5, "batch_collect.stage.connecting")
        progress_callback(80, "batch_collect.stage.collecting_command|1|1", "display version")
        return CollectDeviceResult(True, str(device.id), f"run-{device.id}", f"raw/{device.id}.log", True, 1, 1, 1, None, [])

    run_batch_collect(devices, "demo", collector=collector, max_workers=2, progress_callback=updates.append)

    assert {update.device_key for update in updates} == {"1", "2"}
    assert any(update.percent == 5 and update.stage == "batch_collect.stage.connecting" for update in updates)
    assert any(update.command == "display version" for update in updates)


def test_batch_collect_worker_defaults_to_safe_concurrency_and_caps_at_maximum():
    worker = BatchCollectWorker([], "demo")

    assert worker.max_workers == BATCH_COLLECT_DEFAULT_CONCURRENCY == 20
    assert BATCH_COLLECT_MAX_CONCURRENCY == 50
    assert run_batch_collect([], "demo", max_workers=100) == []


def test_batch_collect_dialog_removes_concurrency_control_and_tracks_duplicate_names_by_key():
    app()
    dialog = BatchCollectProgressDialog(I18n("en_US"), 2)
    dialog.mark_waiting(0, "1", "Same", "10.0.0.1")
    dialog.mark_waiting(1, "2", "Same", "10.0.0.2")
    dialog.resize_columns()

    assert not hasattr(dialog, "concurrency_combo")
    assert isinstance(dialog.table.cellWidget(0, 3), QProgressBar)
    assert dialog.table.columnCount() == 8
    assert dialog.table.horizontalHeaderItem(3).text() == "Progress"

    dialog.update_device_progress(
        BatchCollectProgressUpdate(
            device_key="2",
            device_name="Same",
            primary_address="10.0.0.2",
            percent=55,
            status_text="batch_collect.status.running",
            stage="batch_collect.stage.collecting_command|4|11",
            command="display interface",
            elapsed_ms=2300,
        )
    )

    assert dialog.table.cellWidget(0, 3).value() == 0
    assert dialog.table.cellWidget(1, 3).value() == 55
    assert dialog.table.item(1, 4).text() == "Collecting command 4/11"
    assert dialog.table.item(1, 5).text() == "display interface"

    dialog.add_result(
        BatchCollectItemResult(
            device_name="Same",
            primary_address="10.0.0.2",
            success=False,
            result_text="connect failed",
            collect_run_uuid=None,
            raw_log_path=None,
            elapsed_ms=2500,
            device_key="2",
        )
    )

    assert dialog.table.cellWidget(1, 3).value() == 100
    assert dialog.table.item(1, 2).text() == "Failed"
    assert dialog.table.item(1, 7).text() == "connect failed"

    dialog.update_device_progress(
        BatchCollectProgressUpdate(
            device_key="2",
            device_name="Same",
            primary_address="10.0.0.2",
            percent=80,
            status_text="batch_collect.status.running",
            stage="batch_collect.stage.collecting_command|8|11",
            command="display version",
            elapsed_ms=2400,
        )
    )
    assert dialog.table.item(1, 2).text() == "Failed"
    assert dialog.table.item(1, 7).text() == "connect failed"


def test_device_key_prefers_persistent_identity_over_duplicate_name():
    assert device_key(Device(id=12, name="同名", primary_address="10.0.0.1")) == "12"
    assert device_key(Device(device_uuid="device-uuid", name="同名", primary_address="10.0.0.1")) == "device-uuid"
