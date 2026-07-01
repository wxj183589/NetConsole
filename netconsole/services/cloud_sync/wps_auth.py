from __future__ import annotations

from dataclasses import dataclass

from netconsole.models.cloud_sync_models import CloudSyncProfile


@dataclass(frozen=True)
class WpsAuthContext:
    access_token: str
    refresh_token: str = ""
    token_expires_at: str = ""
    app_id: str = ""
    tenant_id: str = ""

    @classmethod
    def from_profile(cls, profile: CloudSyncProfile) -> "WpsAuthContext":
        return cls(
            access_token=profile.access_token,
            refresh_token=profile.refresh_token,
            token_expires_at=profile.token_expires_at,
            app_id=profile.app_id,
            tenant_id=profile.tenant_id,
        )

    def require_token(self) -> str:
        token = self.access_token.strip()
        if not token:
            raise ValueError("WPS access_token 未配置")
        return token

