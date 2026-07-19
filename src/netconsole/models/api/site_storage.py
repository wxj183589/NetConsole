from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class SiteCreateRequest(ApiModel):
    site_id: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=128)
    remark: str = Field(default="", max_length=500)
    activate: bool = False


class SiteActivateRequest(ApiModel):
    confirmed: bool = True


class SiteMigrateRequest(ApiModel):
    destination_root: str = Field(min_length=1, max_length=32_767)


class SiteExportRequest(ApiModel):
    destination_path: str = Field(default="", max_length=32_767)


class SiteImportInspectRequest(ApiModel):
    package_path: str = Field(min_length=1, max_length=32_767)


class SiteImportRequest(ApiModel):
    package_path: str = Field(min_length=1, max_length=32_767)
    site_id: str = Field(default="", max_length=63)
    display_name: str = Field(default="", max_length=128)
    replace_site_id: str = Field(default="", max_length=63)
    activate: bool = False


class DataRootPathRequest(ApiModel):
    path: str = Field(min_length=1, max_length=32_767)


class SiteTaskResponse(ApiModel):
    task_id: str
    task_type: str


__all__ = [
    "DataRootPathRequest", "SiteActivateRequest", "SiteCreateRequest", "SiteExportRequest",
    "SiteImportInspectRequest", "SiteImportRequest", "SiteMigrateRequest", "SiteTaskResponse",
]
