from netconsole.models.device import Device
from netconsole.ui import collect_worker
from netconsole.ui.collect_worker import DeviceCollectThread


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
