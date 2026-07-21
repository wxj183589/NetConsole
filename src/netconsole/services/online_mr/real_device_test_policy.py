from __future__ import annotations

import os
import re
from dataclasses import dataclass

from netconsole.services.online_mr.errors import (
    OnlineMrWebControlError,
    OnlineMrWebControlErrorCode,
)


REAL_DEVICE_TEST_ENV = "REAL_DEVICE_TEST"
REAL_DEVICE_FPING_INTERVAL_MS = 1_000
REAL_DEVICE_FPING_TIMEOUT_MS = 4_000
REAL_DEVICE_IPERF_SERVER = "127.0.0.1"
REAL_DEVICE_IPERF_BANDWIDTH = "2M"


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class OnlineMrRealDeviceTestPolicy:
    """真实设备测试的服务端强制边界，不能由 Renderer 放宽。"""

    enabled: bool = False

    @classmethod
    def from_environment(cls) -> "OnlineMrRealDeviceTestPolicy":
        return cls(enabled=_enabled(os.getenv(REAL_DEVICE_TEST_ENV)))

    @staticmethod
    def is_allowed_site(site_id: str) -> bool:
        compact = re.sub(r"\s+", "", str(site_id or ""))
        return compact in {"宁波12号线", "宁波地铁12号线"}

    @staticmethod
    def is_train_01(train_no: str) -> bool:
        compact = re.sub(r"\s+", "", str(train_no or ""))
        return bool(re.fullmatch(r"(?:列车)?0*1(?:车)?", compact))

    def require_allowed_target(self, *, site_id: str, train_no: str) -> None:
        if not self.enabled:
            return
        if not self.is_allowed_site(site_id) or not self.is_train_01(train_no):
            raise OnlineMrWebControlError(
                OnlineMrWebControlErrorCode.REAL_DEVICE_TARGET_REJECTED,
                "真实设备测试仅允许宁波12号线01车",
                status_code=403,
            )

    def constraints(self) -> dict[str, object]:
        if not self.enabled:
            return {}
        return {
            "site": "宁波12号线",
            "train": "01车",
            "fping_interval_ms": REAL_DEVICE_FPING_INTERVAL_MS,
            "fping_timeout_ms": REAL_DEVICE_FPING_TIMEOUT_MS,
            "iperf_server_ip": REAL_DEVICE_IPERF_SERVER,
            "iperf_protocol": "TCP",
            "iperf_bandwidth": REAL_DEVICE_IPERF_BANDWIDTH,
            "history_write_policy": "append_only",
        }


__all__ = [
    "OnlineMrRealDeviceTestPolicy",
    "REAL_DEVICE_FPING_INTERVAL_MS",
    "REAL_DEVICE_FPING_TIMEOUT_MS",
    "REAL_DEVICE_IPERF_BANDWIDTH",
    "REAL_DEVICE_IPERF_SERVER",
    "REAL_DEVICE_TEST_ENV",
]
