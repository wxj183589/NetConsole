from __future__ import annotations

from collections.abc import Iterable


FIT_AP_OPTICAL_TASK_TYPES = frozenset(
    {
        "ac_fit_ap_optical_refresh",
        "trackside_ap_optical_update",
    }
)


def fit_ap_optical_resource_key(site_name: str, ac_device_uuid: str) -> str:
    site = str(site_name or "demo").strip().casefold() or "demo"
    ac_uuid = str(ac_device_uuid or "").strip().casefold()
    if not ac_uuid:
        return ""
    return f"site:{site}|ac:{ac_uuid}|fit_ap_optical"


def fit_ap_optical_resource_keys(site_name: str, ac_device_uuids: Iterable[object]) -> list[str]:
    keys = [
        fit_ap_optical_resource_key(site_name, str(ac_uuid or ""))
        for ac_uuid in ac_device_uuids
    ]
    return list(dict.fromkeys(key for key in keys if key))


__all__ = [
    "FIT_AP_OPTICAL_TASK_TYPES",
    "fit_ap_optical_resource_key",
    "fit_ap_optical_resource_keys",
]
