from netconsole.models.device import Device
from netconsole.ui import collect_worker
from netconsole.ui.collect_worker import DeviceCollectThread
from netconsole.ui import optical_refresh_worker
from netconsole.ui.optical_refresh_worker import OpticalRefreshThread


def test_collect_worker_uses_collect_service(monkeypatch):
    calls = []

    def fake_collect(device, site_name):
        calls.append((device.name, site_name))
        return "done"

    monkeypatch.setattr(collect_worker, "collect_h3c_device_details", fake_collect)
    thread = DeviceCollectThread(Device(name="SW01"), "demo")
    results = []
    thread.collect_finished.connect(lambda result: results.append(result))

    thread.run()

    assert calls == [("SW01", "demo")]
    assert results == ["done"]


def test_optical_refresh_worker_uses_optical_refresh_service(monkeypatch):
    calls = []

    def fake_refresh(device, site_name):
        calls.append((device.name, site_name))
        return "optical-done"

    monkeypatch.setattr(optical_refresh_worker, "refresh_h3c_device_optical", fake_refresh)
    thread = OpticalRefreshThread(Device(name="SW01"), "demo")
    results = []
    thread.refresh_finished.connect(lambda result: results.append(result))

    thread.run()

    assert calls == [("SW01", "demo")]
    assert results == ["optical-done"]
