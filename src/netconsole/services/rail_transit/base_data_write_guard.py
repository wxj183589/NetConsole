from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import desktop_storage_mode
from netconsole.core.sites import SiteManager


WRITE_FEATURE_ID = "web.rail_transit_base_data_write"
WRITE_ENABLED_ENV = "RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED"
COPY_WRITE_ENABLED_ENV = "NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE"
REAL_WRITE_ENABLED_ENV = "NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE"
ROLLBACK_ENABLED_ENV = "RAIL_TRANSIT_BASE_DATA_ROLLBACK_ENABLED"
COPY_SCOPE = "copy_validation"


class BaseDataWriteGuardError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BaseDataWriteStatus:
    feature_enabled: bool
    write_enabled: bool
    copy_write_authorized: bool
    real_write_authorized: bool
    rollback_enabled: bool
    scope: str
    storage_mode: str


class BaseDataWriteGuard:
    """集中保护正式资料写入；默认拒绝，副本必须有标记和双开关。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        feature_enabled: bool = False,
        write_enabled: bool | None = None,
        copy_write_enabled: bool | None = None,
        real_write_enabled: bool | None = None,
        desktop_session_write_enabled: bool = False,
        rollback_enabled: bool | None = None,
    ) -> None:
        self.paths = paths
        self.storage_mode = desktop_storage_mode()
        self.feature_enabled = bool(feature_enabled)
        self.write_enabled = _env_enabled(WRITE_ENABLED_ENV) if write_enabled is None else bool(write_enabled)
        self.copy_write_enabled = (
            _env_enabled(COPY_WRITE_ENABLED_ENV) if copy_write_enabled is None else bool(copy_write_enabled)
        )
        self.real_write_enabled = (
            _env_enabled(REAL_WRITE_ENABLED_ENV) if real_write_enabled is None else bool(real_write_enabled)
        )
        self.desktop_session_write_enabled = bool(desktop_session_write_enabled)
        self.rollback_enabled = (
            _env_enabled(ROLLBACK_ENABLED_ENV) if rollback_enabled is None else bool(rollback_enabled)
        )

    def status(self, site_id: str) -> BaseDataWriteStatus:
        scope = self._scope(site_id)
        write_enabled = self.storage_mode == "persistent" and (
            self.write_enabled or (scope != COPY_SCOPE and self.desktop_session_write_enabled)
        )
        base = self.feature_enabled and write_enabled
        return BaseDataWriteStatus(
            feature_enabled=self.feature_enabled,
            write_enabled=write_enabled,
            copy_write_authorized=base and scope == COPY_SCOPE and self.copy_write_enabled,
            real_write_authorized=base
            and scope != COPY_SCOPE
            and (self.real_write_enabled or self.desktop_session_write_enabled),
            rollback_enabled=self.rollback_enabled,
            scope=scope,
            storage_mode=self.storage_mode,
        )

    @staticmethod
    def write_denial(status: BaseDataWriteStatus) -> tuple[str, str]:
        if status.storage_mode == "isolated_test":
            return "ISOLATED_TEST_READONLY", "隔离测试模式下禁止修改正式局点数据。"
        if not status.write_enabled:
            return "BASE_DATA_WRITE_DISABLED", "轨道交通基础资料正式写入未启用"
        if not status.feature_enabled:
            return "BASE_DATA_WRITE_DISABLED", "轨道交通基础资料写入 Feature 未启用"
        if status.scope == COPY_SCOPE and not status.copy_write_authorized:
            return "BASE_DATA_COPY_WRITE_NOT_AUTHORIZED", "基础资料副本写入未授权"
        if status.scope != COPY_SCOPE and not status.real_write_authorized:
            return "BASE_DATA_REAL_WRITE_NOT_AUTHORIZED", "真实局点基础资料写入未授权"
        return "", ""

    def authorize_apply(self, site_id: str, *, explicit_confirmation: bool) -> BaseDataWriteStatus:
        status = self.status(site_id)
        denial_code, denial_reason = self.write_denial(status)
        if denial_code:
            raise BaseDataWriteGuardError(denial_code, denial_reason)
        if not explicit_confirmation:
            raise BaseDataWriteGuardError("BASE_DATA_IMPORT_CONFLICT", "正式写入需要明确确认")
        self._validated_database_path(site_id)
        return status

    def authorize_rollback(self, site_id: str, *, explicit_confirmation: bool) -> BaseDataWriteStatus:
        status = self.authorize_apply(site_id, explicit_confirmation=explicit_confirmation)
        if not status.rollback_enabled:
            raise BaseDataWriteGuardError("BASE_DATA_ROLLBACK_DISABLED", "基础资料回滚未启用")
        return status

    def _scope(self, site_id: str) -> str:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        metadata_path = self.paths.site_dir(site_id) / "site_meta.json"
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "real"
        if not isinstance(payload, dict):
            return "real"
        scope = str(payload.get("base_data_write_scope") or "").strip()
        source_hash = str(payload.get("base_data_source_sha256") or "").strip().casefold()
        return COPY_SCOPE if scope == COPY_SCOPE and len(source_hash) == 64 else "real"

    def _validated_database_path(self, site_id: str) -> Path:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        database = self.paths.site_db_path(site_id).resolve()
        site_root = self.paths.site_dir(site_id).resolve()
        data_root = self.paths.data_root.resolve()
        if not database.is_file() or site_root not in database.parents or data_root not in database.parents:
            raise BaseDataWriteGuardError("BASE_DATA_SOURCE_INVALID", "基础资料数据库路径不在受控局点目录")
        return database


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "0").strip() == "1"


__all__ = [
    "BaseDataWriteGuard",
    "BaseDataWriteGuardError",
    "BaseDataWriteStatus",
    "COPY_SCOPE",
    "COPY_WRITE_ENABLED_ENV",
    "REAL_WRITE_ENABLED_ENV",
    "ROLLBACK_ENABLED_ENV",
    "WRITE_ENABLED_ENV",
    "WRITE_FEATURE_ID",
]
