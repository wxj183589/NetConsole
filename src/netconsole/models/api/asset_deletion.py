"""Read-only asset lifecycle safety contract; no deletion authorization."""

from pydantic import Field
from netconsole.models.api.common import ApiModel


class AssetDeletionPreflightRequest(ApiModel):
    device_uuid: str = Field(min_length=1, max_length=160)
    base_revision: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=128)
