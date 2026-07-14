from __future__ import annotations

from fastapi import APIRouter

from netconsole.backend.api.ac_mesh_link_router import router as ac_mesh_link_router
from netconsole.backend.api.ac_management_router import router as ac_management_router
from netconsole.backend.api.agent_router import router as agent_router
from netconsole.backend.api.agent_router import ws_router as agent_ws_router
from netconsole.backend.api.health import router as health_router
from netconsole.backend.api.job_center_router import router as job_center_router
from netconsole.backend.api.mesh_analysis_router import router as mesh_analysis_router
from netconsole.backend.api.online_mr_router import router as online_mr_router
from netconsole.backend.api.online_mr_control_router import router as online_mr_control_router
from netconsole.backend.api.rail_transit_base_data_router import router as rail_transit_base_data_router
from netconsole.backend.api.task_router import router as task_router
from netconsole.backend.api.task_router import ws_router
from netconsole.backend.api.train_communication_router import router as train_communication_router
from netconsole.backend.api.wireless_dashboard_router import router as wireless_dashboard_router
from netconsole.backend.api.traffic_router import router as traffic_router
from netconsole.backend.api.traffic_router import ws_router as traffic_ws_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(ac_management_router)
api_router.include_router(ac_mesh_link_router)
api_router.include_router(job_center_router)
api_router.include_router(task_router)
api_router.include_router(agent_router)
api_router.include_router(traffic_router)
api_router.include_router(online_mr_router)
api_router.include_router(online_mr_control_router)
api_router.include_router(rail_transit_base_data_router)
api_router.include_router(train_communication_router)
api_router.include_router(mesh_analysis_router)
api_router.include_router(wireless_dashboard_router)
ws_router.include_router(agent_ws_router)
ws_router.include_router(traffic_ws_router)

__all__ = ["api_router", "ws_router"]
