from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RuntimeMode(StrEnum):
    DESKTOP = "desktop"
    SERVER = "server"
    TEST = "test"


class DataEnvironmentMode(StrEnum):
    """运行时所连接的数据环境，与进程宿主模式分离。"""

    PRODUCTION = "production"
    DEVELOPMENT = "development"
    TEST = "test"


@dataclass(frozen=True)
class DataEnvironmentInfo:
    mode: DataEnvironmentMode
    created_from: str = ""
    created_time: str = ""
    readonly_warning: bool = False

    @property
    def label(self) -> str:
        return {
            DataEnvironmentMode.PRODUCTION: "PRODUCTION",
            DataEnvironmentMode.DEVELOPMENT: "DEVELOPMENT",
            DataEnvironmentMode.TEST: "TEST",
        }[self.mode]

    @property
    def is_production(self) -> bool:
        return self.mode is DataEnvironmentMode.PRODUCTION


__all__ = ["DataEnvironmentInfo", "DataEnvironmentMode", "RuntimeMode"]
