from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from netconsole.services import h3c_ac_collect_service


_AP_OPTICAL_FIELDS = (
    "rx_power",
    "tx_power",
    "temperature",
    "voltage",
    "module_model",
    "module_serial_number",
    "module_vendor",
    "wavelength",
    "transmission_distance",
    "connector_type",
)
_PATCH_MARKER = "__netconsole_fit_ap_partial_success__"


def has_valid_ap_optical_measurement(row: dict[str, object | None]) -> bool:
    return any(not _is_empty(row.get(field)) for field in _AP_OPTICAL_FIELDS)


def preserve_valid_ap_optical_result(
    row: dict[str, object | None],
) -> dict[str, object | None]:
    """Promote a row when AP-side optical data was parsed despite an auxiliary command failure."""

    result = dict(row)
    if str(result.get("status") or "").strip().casefold() == "success":
        return result
    if not has_valid_ap_optical_measurement(result):
        return result

    result["status"] = "success"
    return result


def install_fit_ap_optical_partial_success() -> None:
    current = h3c_ac_collect_service._collect_single_fit_ap_optical
    if bool(getattr(current, _PATCH_MARKER, False)):
        return

    original: Callable[..., dict[str, object | None]] = current

    @wraps(original)
    def wrapped(*args: Any, **kwargs: Any) -> dict[str, object | None]:
        row = original(*args, **kwargs)
        result = preserve_valid_ap_optical_result(row)
        if str(row.get("status") or "").strip().casefold() != "success" and str(result.get("status") or "").strip().casefold() == "success":
            _log_partial_success(args, kwargs, row)
        return result

    setattr(wrapped, _PATCH_MARKER, True)
    h3c_ac_collect_service._collect_single_fit_ap_optical = wrapped


def _log_partial_success(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    row: dict[str, object | None],
) -> None:
    try:
        ac_device = args[0] if args else kwargs.get("ac_device")
        ap_row = args[1] if len(args) > 1 else kwargs.get("ap_row") or {}
        collect_run_uuid = args[3] if len(args) > 3 else kwargs.get("collect_run_uuid") or ""
        ap_name = str(dict(ap_row).get("ap_name") or dict(ap_row).get("ap_ip") or "FIT-AP")
        h3c_ac_collect_service._safe_log_warning(
            "FIT_AP_OPTICAL_AP_PARTIAL_SUCCESS",
            h3c_ac_collect_service._detail(
                ac_device,
                str(collect_run_uuid),
                ap=ap_name,
                error=(
                    "usable AP optical measurement preserved despite auxiliary command failure; "
                    f"command_error={row.get('error_message') or ''}"
                ),
            ),
        )
    except Exception:
        return


def _is_empty(value: object) -> bool:
    text = str(value or "").strip()
    return not text or text in {"-", "N/A", "n/a"}


__all__ = [
    "has_valid_ap_optical_measurement",
    "install_fit_ap_optical_partial_success",
    "preserve_valid_ap_optical_result",
]
