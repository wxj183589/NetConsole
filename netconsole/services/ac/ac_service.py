from __future__ import annotations

from netconsole.services.ac.ac_models import AcResourceRefreshRequest, AcResourceRefreshResult
from netconsole.services.ac.ac_resource_service import AcResourceService, CancelCallback, ProgressCallback


class AcService:
    def __init__(self, resource_service: AcResourceService) -> None:
        self.resource_service = resource_service

    def refresh_ap_resources(
        self,
        request: AcResourceRefreshRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcResourceRefreshResult:
        return self.resource_service.refresh(
            request,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    def refresh_radio_resources(
        self,
        request: AcResourceRefreshRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcResourceRefreshResult:
        return self.refresh_ap_resources(
            request,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
