from __future__ import annotations

from base64 import b64decode, b64encode
from datetime import datetime
import json

from netconsole.core.database import Database
from netconsole.models.cloud_sync_models import CloudSyncProfile, CloudSyncRun


class SecretStore:
    """Small boundary for local secret storage; replace with OS vault when available."""

    PREFIX = "local:v1:"

    def encrypt(self, value: str | None) -> str:
        text = value or ""
        if not text:
            return ""
        return self.PREFIX + b64encode(text.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str:
        text = value or ""
        if not text:
            return ""
        if not text.startswith(self.PREFIX):
            return text
        try:
            return b64decode(text[len(self.PREFIX) :].encode("ascii")).decode("utf-8")
        except Exception:
            return ""


class CloudSyncRepository:
    def __init__(self, database: Database, secret_store: SecretStore | None = None) -> None:
        self.database = database
        self.secret_store = secret_store or SecretStore()

    def get_profile(
        self,
        site_id: str,
        provider: str = "wps",
        profile_name: str = "trackside_ap_business",
    ) -> CloudSyncProfile | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM cloud_sync_profiles
                WHERE site_id = ? AND provider = ? AND profile_name = ?
                """,
                (site_id, provider, profile_name),
            ).fetchone()
        return self._profile_from_row(dict(row)) if row else None

    def get_or_create_profile(
        self,
        site_id: str,
        provider: str = "wps",
        profile_name: str = "trackside_ap_business",
    ) -> CloudSyncProfile:
        profile = self.get_profile(site_id, provider, profile_name)
        if profile is not None:
            return profile
        profile = CloudSyncProfile(
            site_id=site_id,
            provider=provider,
            profile_name=profile_name,
            target_name=f"{site_id}_轨旁AP业务",
        )
        self.save_profile(profile)
        return self.get_profile(site_id, provider, profile_name) or profile

    def save_profile(self, profile: CloudSyncProfile) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        values = self._profile_to_db_values(profile, now)
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO cloud_sync_profiles (
                    site_id, provider, profile_name, enabled, auto_sync_after_export,
                    sync_mode, auth_type, access_token_encrypted, refresh_token_encrypted,
                    token_expires_at, app_id, tenant_id, target_type, target_name,
                    file_token, remote_url, permission_mode, readonly_members_json,
                    readonly_link_enabled, readonly_link_url, last_sync_at,
                    last_sync_status, last_error_message, created_at, updated_at
                )
                VALUES (
                    :site_id, :provider, :profile_name, :enabled, :auto_sync_after_export,
                    :sync_mode, :auth_type, :access_token_encrypted, :refresh_token_encrypted,
                    :token_expires_at, :app_id, :tenant_id, :target_type, :target_name,
                    :file_token, :remote_url, :permission_mode, :readonly_members_json,
                    :readonly_link_enabled, :readonly_link_url, :last_sync_at,
                    :last_sync_status, :last_error_message, :created_at, :updated_at
                )
                ON CONFLICT(site_id, provider, profile_name) DO UPDATE SET
                    enabled = excluded.enabled,
                    auto_sync_after_export = excluded.auto_sync_after_export,
                    sync_mode = excluded.sync_mode,
                    auth_type = excluded.auth_type,
                    access_token_encrypted = excluded.access_token_encrypted,
                    refresh_token_encrypted = excluded.refresh_token_encrypted,
                    token_expires_at = excluded.token_expires_at,
                    app_id = excluded.app_id,
                    tenant_id = excluded.tenant_id,
                    target_type = excluded.target_type,
                    target_name = excluded.target_name,
                    file_token = excluded.file_token,
                    remote_url = excluded.remote_url,
                    permission_mode = excluded.permission_mode,
                    readonly_members_json = excluded.readonly_members_json,
                    readonly_link_enabled = excluded.readonly_link_enabled,
                    readonly_link_url = excluded.readonly_link_url,
                    last_sync_at = excluded.last_sync_at,
                    last_sync_status = excluded.last_sync_status,
                    last_error_message = excluded.last_error_message,
                    updated_at = excluded.updated_at
                """,
                values,
            )
            conn.commit()

    def update_profile_sync_state(
        self,
        site_id: str,
        provider: str,
        profile_name: str,
        *,
        file_token: str = "",
        remote_url: str = "",
        readonly_link_url: str = "",
        status: str,
        error_message: str = "",
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        assignments = [
            "last_sync_at = ?",
            "last_sync_status = ?",
            "last_error_message = ?",
            "updated_at = ?",
        ]
        params: list[object] = [now, status, error_message, now]
        if file_token:
            assignments.append("file_token = ?")
            params.append(file_token)
        if remote_url:
            assignments.append("remote_url = ?")
            params.append(remote_url)
        if readonly_link_url:
            assignments.append("readonly_link_url = ?")
            params.append(readonly_link_url)
        params.extend([site_id, provider, profile_name])
        with self.database.connect() as conn:
            conn.execute(
                f"""
                UPDATE cloud_sync_profiles
                SET {", ".join(assignments)}
                WHERE site_id = ? AND provider = ? AND profile_name = ?
                """,
                params,
            )
            conn.commit()

    def upsert_document(
        self,
        site_id: str,
        provider: str,
        report_type: str,
        profile_name: str,
        *,
        file_token: str,
        remote_url: str = "",
        remote_name: str = "",
        schema_hash: str = "",
        last_data_hash: str = "",
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO cloud_sync_documents (
                    site_id, provider, report_type, profile_name, file_token, remote_url,
                    remote_name, schema_hash, last_data_hash, last_sync_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, provider, report_type, profile_name) DO UPDATE SET
                    file_token = excluded.file_token,
                    remote_url = excluded.remote_url,
                    remote_name = excluded.remote_name,
                    schema_hash = excluded.schema_hash,
                    last_data_hash = excluded.last_data_hash,
                    last_sync_at = excluded.last_sync_at,
                    updated_at = excluded.updated_at
                """,
                (site_id, provider, report_type, profile_name, file_token, remote_url, remote_name, schema_hash, last_data_hash, now, now, now),
            )
            conn.commit()

    def get_document_hash(self, site_id: str, provider: str, report_type: str, profile_name: str) -> str:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT last_data_hash FROM cloud_sync_documents
                WHERE site_id = ? AND provider = ? AND report_type = ? AND profile_name = ?
                """,
                (site_id, provider, report_type, profile_name),
            ).fetchone()
        return str(row["last_data_hash"] or "") if row else ""

    def add_run(self, run: CloudSyncRun) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO cloud_sync_runs (
                    site_id, provider, report_type, profile_name, file_token, action, status,
                    rows_total, sheets_total, started_at, ended_at, elapsed_ms, error_message,
                    local_export_path, remote_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.site_id,
                    run.provider,
                    run.report_type,
                    run.profile_name,
                    run.file_token,
                    run.action,
                    run.status,
                    run.rows_total,
                    run.sheets_total,
                    run.started_at,
                    run.ended_at,
                    run.elapsed_ms,
                    run.error_message,
                    run.local_export_path,
                    run.remote_url,
                ),
            )
            conn.commit()

    def list_runs(self, site_id: str, provider: str = "wps", profile_name: str = "trackside_ap_business", limit: int = 50) -> list[dict[str, object]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM cloud_sync_runs
                WHERE site_id = ? AND provider = ? AND profile_name = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (site_id, provider, profile_name, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def _profile_to_db_values(self, profile: CloudSyncProfile, now: str) -> dict[str, object]:
        return {
            "site_id": profile.site_id,
            "provider": profile.provider,
            "profile_name": profile.profile_name,
            "enabled": int(profile.enabled),
            "auto_sync_after_export": int(profile.auto_sync_after_export),
            "sync_mode": profile.sync_mode,
            "auth_type": profile.auth_type,
            "access_token_encrypted": self.secret_store.encrypt(profile.access_token),
            "refresh_token_encrypted": self.secret_store.encrypt(profile.refresh_token),
            "token_expires_at": profile.token_expires_at,
            "app_id": profile.app_id,
            "tenant_id": profile.tenant_id,
            "target_type": profile.target_type,
            "target_name": profile.target_name,
            "file_token": profile.file_token,
            "remote_url": profile.remote_url,
            "permission_mode": profile.permission_mode,
            "readonly_members_json": json.dumps(profile.readonly_members, ensure_ascii=False),
            "readonly_link_enabled": int(profile.readonly_link_enabled),
            "readonly_link_url": profile.readonly_link_url,
            "last_sync_at": profile.last_sync_at,
            "last_sync_status": profile.last_sync_status,
            "last_error_message": profile.last_error_message,
            "created_at": now,
            "updated_at": now,
        }

    def _profile_from_row(self, row: dict[str, object]) -> CloudSyncProfile:
        try:
            members = json.loads(str(row.get("readonly_members_json") or "[]"))
        except json.JSONDecodeError:
            members = []
        return CloudSyncProfile(
            id=int(row["id"]) if row.get("id") is not None else None,
            site_id=str(row.get("site_id") or ""),
            provider=str(row.get("provider") or "wps"),
            profile_name=str(row.get("profile_name") or "trackside_ap_business"),
            enabled=bool(row.get("enabled")),
            auto_sync_after_export=bool(row.get("auto_sync_after_export")),
            sync_mode=str(row.get("sync_mode") or "manual"),
            auth_type=str(row.get("auth_type") or "bearer"),
            access_token=self.secret_store.decrypt(str(row.get("access_token_encrypted") or "")),
            refresh_token=self.secret_store.decrypt(str(row.get("refresh_token_encrypted") or "")),
            token_expires_at=str(row.get("token_expires_at") or ""),
            app_id=str(row.get("app_id") or ""),
            tenant_id=str(row.get("tenant_id") or ""),
            target_type=str(row.get("target_type") or "ksheet"),
            target_name=str(row.get("target_name") or ""),
            file_token=str(row.get("file_token") or ""),
            remote_url=str(row.get("remote_url") or ""),
            permission_mode=str(row.get("permission_mode") or "readonly_members"),
            readonly_members=members if isinstance(members, list) else [],
            readonly_link_enabled=bool(row.get("readonly_link_enabled")),
            readonly_link_url=str(row.get("readonly_link_url") or ""),
            last_sync_at=str(row.get("last_sync_at") or ""),
            last_sync_status=str(row.get("last_sync_status") or ""),
            last_error_message=str(row.get("last_error_message") or ""),
        )

