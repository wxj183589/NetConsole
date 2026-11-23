"""Shared creation policy; every caller owns a fresh, independent SFTP client."""
from __future__ import annotations

from collections.abc import Callable

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.file_transfer_service import FileTransferService
from netconsole.services.host_key_trust_service import HostKeyTrustService


class SftpConnectionService:
    def __init__(self, paths: PathResolver, factory: Callable = FileTransferService) -> None:
        self.paths = paths
        self.factory = factory

    def device(self, site: str, device_uuid: str) -> Device:
        device = DeviceRepository(Database(self.paths.site_db_path(site))).get_by_uuid(device_uuid)
        if device is None:
            raise KeyError("设备不存在或不属于当前局点")
        return device

    def create(self, site: str, *, relay_site_id: str, source: str,
               writable: bool = False) -> FileTransferService:
        options = dict(strict_host_keys=True, host_key_trust=HostKeyTrustService(self.paths),
                       relay_site_id=relay_site_id, route_source=source)
        if writable:
            options["allow_device_writes"] = True
        return self.factory(site, self.paths, **options)
