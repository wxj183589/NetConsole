from __future__ import annotations

from fastapi import APIRouter, Depends

from netconsole.backend.api.ac_mesh_link_router import router as ac_mesh_link_router
from netconsole.backend.api.ac_management_router import router as ac_management_router
from netconsole.backend.api.agent_router import router as agent_router
from netconsole.backend.api.agent_router import ws_router as agent_ws_router
from netconsole.backend.api.config_collection_router import router as config_collection_router
from netconsole.backend.api.command_reference_router import router as command_reference_router
from netconsole.backend.api.device_compatibility_router import router as device_compatibility_router
from netconsole.backend.api.device_management_router import router as device_management_router
from netconsole.backend.api.file_management_router import router as file_management_router
from netconsole.backend.api.feature_access import require_feature
from netconsole.backend.api.feature_router import router as feature_router
from netconsole.backend.api.health import router as health_router
from netconsole.backend.api.job_center_router import router as job_center_router
from netconsole.backend.api.mesh_analysis_router import router as mesh_analysis_router
from netconsole.backend.api.network_tools_router import router as network_tools_router
from netconsole.backend.api.online_mr_router import router as online_mr_router
from netconsole.backend.api.online_mr_control_router import router as online_mr_control_router
from netconsole.backend.api.online_mr_agent_control_router import router as online_mr_agent_control_router
from netconsole.backend.api.rail_transit_base_data_router import router as rail_transit_base_data_router
from netconsole.backend.api.task_router import router as task_router
from netconsole.backend.api.task_router import ws_router as task_ws_router
from netconsole.backend.api.system_maintenance_router import router as system_maintenance_router
from netconsole.backend.api.train_communication_router import router as train_communication_router
from netconsole.backend.api.trackside_ap_business_router import router as trackside_ap_business_router
from netconsole.backend.api.wps_sync_router import router as wps_sync_router
from netconsole.backend.api.vehicle_mr_online_router import router as vehicle_mr_online_router
from netconsole.backend.api.ground_unattended_router import router as ground_unattended_router
from netconsole.backend.api.wireless_dashboard_router import router as wireless_dashboard_router
from netconsole.backend.api.traffic_router import router as traffic_router
from netconsole.backend.api.system_settings_router import router as system_settings_router
from netconsole.backend.api.system_network_router import router as system_network_router
from netconsole.backend.api.site_storage_router import router as site_storage_router
from netconsole.backend.api.traffic_router import ws_router as traffic_ws_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(feature_router)
api_router.include_router(system_settings_router)
api_router.include_router(
    system_network_router,
    dependencies=[Depends(require_feature("web.ground_unattended"))],
)
api_router.include_router(site_storage_router)
api_router.include_router(
    command_reference_router,
    dependencies=[Depends(require_feature("web.command_reference"))],
)
api_router.include_router(device_compatibility_router)
api_router.include_router(
    ac_management_router,
    dependencies=[Depends(require_feature("web.ac_management"))],
)
api_router.include_router(
    ac_mesh_link_router,
    dependencies=[Depends(require_feature("web.rail_train_online"))],
)
api_router.include_router(
    job_center_router,
    dependencies=[Depends(require_feature("web.job_center"))],
)
api_router.include_router(task_router)
api_router.include_router(
    agent_router,
    dependencies=[Depends(require_feature("web.agent_management"))],
)
api_router.include_router(
    traffic_router,
    dependencies=[Depends(require_feature("network_tools.traffic"))],
)
api_router.include_router(
    device_management_router,
    dependencies=[Depends(require_feature("web.device_management"))],
)
api_router.include_router(
    network_tools_router,
    dependencies=[Depends(require_feature("web.network_tools_toolbox"))],
)
api_router.include_router(
    config_collection_router,
    dependencies=[Depends(require_feature("web.config_collection"))],
)
api_router.include_router(
    file_management_router,
    dependencies=[Depends(require_feature("web.file_management"))],
)
api_router.include_router(
    online_mr_router,
    dependencies=[Depends(require_feature("web.online_mr_realtime"))],
)
api_router.include_router(online_mr_control_router)
api_router.include_router(online_mr_agent_control_router)
api_router.include_router(
    rail_transit_base_data_router,
    dependencies=[Depends(require_feature("web.rail_transit_base_data"))],
)
api_router.include_router(
    train_communication_router,
    dependencies=[Depends(require_feature("web.train_communication_monitoring"))],
)
api_router.include_router(
    trackside_ap_business_router,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business"))],
)
api_router.include_router(wps_sync_router)
api_router.include_router(
    vehicle_mr_online_router,
    dependencies=[Depends(require_feature("web.rail_train_online"))],
)
api_router.include_router(ground_unattended_router)
api_router.include_router(
    mesh_analysis_router,
    dependencies=[Depends(require_feature("web.mesh_analysis"))],
)
api_router.include_router(
    wireless_dashboard_router,
    dependencies=[Depends(require_feature("web.rail_transit_wireless_dashboard"))],
)
api_router.include_router(
    system_maintenance_router,
    dependencies=[Depends(require_feature("web.logs"))],
)
ws_router = APIRouter()
ws_router.include_router(task_ws_router)
ws_router.include_router(
    agent_ws_router,
    dependencies=[Depends(require_feature("web.agent_management"))],
)
ws_router.include_router(
    traffic_ws_router,
    dependencies=[Depends(require_feature("network_tools.traffic"))],
)

__all__ = ["api_router", "ws_router"]
