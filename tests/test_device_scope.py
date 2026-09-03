from netconsole.models.device import Device
from netconsole.services.device_scope import (
    DeviceOutOfCurrentDebugScopeError,
    filter_current_debug_devices,
    require_current_debug_device,
)


def test_current_debug_scope_filters_only_excluded_devices():
    included = Device(name="included", work_scope_status="included")
    excluded = Device(name="excluded", work_scope_status="excluded")

    assert filter_current_debug_devices([included, excluded]) == [included]
    assert require_current_debug_device(included) is included
    try:
        require_current_debug_device(excluded)
    except DeviceOutOfCurrentDebugScopeError as exc:
        assert exc.code == "DEVICE_OUT_OF_CURRENT_DEBUG_SCOPE"
    else:
        raise AssertionError("excluded device must not pass current debug scope")
