from hashlib import sha256

import pytest

from tests.support.device_upgrade_lab import SimulatedDevice, simulate_upgrade


@pytest.mark.parametrize(("fail_boot", "status", "final_version"), [
    (False, "verified", "2.0"),
    (True, "rolled_back", "1.0"),
])
def test_simulated_upgrade_verifies_or_restores_version(fail_boot, status, final_version):
    image = b"synthetic firmware fixture"
    device = SimulatedDevice("lab-device", "1.0", fail_boot=fail_boot)
    result = simulate_upgrade(device, target_version="2.0", image=image, expected_sha256=sha256(image).hexdigest())
    assert result.device_uuid == "lab-device"
    assert result.previous_version == "1.0"
    assert result.status == status
    assert device.version == result.current_version == final_version
    assert not device.staged_version


def test_simulated_upgrade_rejects_corrupt_image_before_device_change():
    device = SimulatedDevice("lab-device", "1.0")
    with pytest.raises(ValueError, match="digest mismatch"):
        simulate_upgrade(device, target_version="2.0", image=b"synthetic firmware fixture", expected_sha256="0" * 64)
    assert device.version == "1.0"
    assert not device.staged_version
