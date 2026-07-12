from __future__ import annotations

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.online_mr_collection_page import OnlineMrCollectionPage


class OnlineMrCollectionAnalysisPage(OnlineMrCollectionPage):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__(repository, i18n, site_name, paths, analysis_only=True)
