from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.online_mr.agent_http_client import (
    OnlineMrAgentClientError,
    OnlineMrAgentHttpClient,
)
from netconsole.services.online_mr.agent_package_importer import (
    OnlineMrAgentPackageImporter,
)
from netconsole.services.online_mr.errors import OnlineMrApplicationErrorCode


@dataclass(frozen=True)
class OnlineMrAgentDownloadImportResult:
    success: bool
    downloaded: bool = False
    imported: bool = False
    already_imported: bool = False
    conflict: bool = False
    task_id: str = ""
    session_id: str = ""
    session_dir: Path | None = None
    downloaded_path: Path | None = None
    sha256: str = ""
    error_code: str = ""
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def source_zip_sha256(self) -> str:
        return self.sha256


class OnlineMrAgentDownloadService:
    """下载 Agent ZIP 并交给 5B-7 importer；不启动或停止远端任务。"""

    def __init__(
        self,
        paths: PathResolver,
        client: OnlineMrAgentHttpClient,
        *,
        importer: OnlineMrAgentPackageImporter | None = None,
    ) -> None:
        self.paths = paths
        self.client = client
        self.importer = importer or OnlineMrAgentPackageImporter(paths)

    async def download_and_import_package(
        self,
        package_id: str,
        *,
        site_id: str,
        site_name: str = "",
        device_id: int | str,
        device_name: str,
        mr_id: str = "",
        mr_name: str,
        owner: str = "agent_download",
        expected_session_id: str | None = None,
        controller_task_id: str | None = None,
        agent_task_id: str | None = None,
        agent_id: str = "",
        import_mode: str = "strict",
        identity_match_policy: str = "strict",
        expected_host: str = "",
        allow_identity_override: bool = False,
        keep_download_on_success: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> OnlineMrAgentDownloadImportResult:
        try:
            download_dir = self._download_dir(site_id)
            downloaded = await self.client.download_package(
                package_id,
                download_dir,
                cancel_check=cancel_check,
            )
        except OnlineMrAgentClientError as exc:
            return OnlineMrAgentDownloadImportResult(
                success=False,
                error_code=exc.code,
                errors=(exc.message,),
            )
        except ValueError as exc:
            return OnlineMrAgentDownloadImportResult(
                success=False,
                error_code=str(OnlineMrApplicationErrorCode.SITE_NOT_FOUND),
                errors=(str(exc),),
            )

        imported = await asyncio.to_thread(
            self.importer.import_package,
            downloaded.path,
            site_id=site_id,
            site_name=site_name,
            device_id=device_id,
            device_name=device_name,
            mr_id=mr_id,
            mr_name=mr_name,
            owner=owner,
            controller_task_id=controller_task_id,
            agent_task_id=agent_task_id,
            expected_session_id=expected_session_id,
            import_mode=import_mode,
            identity_match_policy=identity_match_policy,
            expected_host=expected_host,
            allow_identity_override=allow_identity_override,
            agent_id=agent_id,
        )
        warnings = list(imported.warnings)
        if imported.success and not keep_download_on_success:
            try:
                downloaded.path.unlink(missing_ok=True)
            except OSError:
                warnings.append("已导入，但临时下载包清理失败")
        return OnlineMrAgentDownloadImportResult(
            success=imported.success,
            downloaded=True,
            imported=imported.imported,
            already_imported=imported.already_imported,
            conflict=imported.conflict,
            task_id=imported.task_id,
            session_id=imported.session_id,
            session_dir=imported.session_dir,
            downloaded_path=(downloaded.path if downloaded.path.exists() else None),
            sha256=downloaded.sha256,
            error_code=(
                str(OnlineMrApplicationErrorCode.AGENT_PACKAGE_CONFLICT)
                if imported.conflict
                else str(OnlineMrApplicationErrorCode.AGENT_PACKAGE_INVALID)
                if not imported.success
                else ""
            ),
            warnings=tuple(warnings),
            errors=imported.errors,
        )

    def _download_dir(self, site_id: str) -> Path:
        site = str(site_id or "").strip()
        if not site or Path(site).name != site or "/" in site or "\\" in site:
            raise ValueError("Online MR 局点标识无效")
        site_root = self.paths.site_dir(site).resolve()
        if not site_root.is_dir():
            raise ValueError("Online MR 局点不存在")
        target = (
            self.paths.site_imports_dir(site) / "online_mr" / "downloads"
        ).resolve()
        try:
            target.relative_to(site_root)
        except ValueError as exc:
            raise ValueError("Online MR 下载目录越界") from exc
        return target


__all__ = ["OnlineMrAgentDownloadImportResult", "OnlineMrAgentDownloadService"]
