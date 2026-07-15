from __future__ import annotations

import json

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.online_mr_agent_control import OnlineMrAgentWebStartRequestDTO
from netconsole.models.api.online_mr_control import OnlineMrWebStartRequestDTO
from netconsole.services.online_mr.agent_web_control_service import OnlineMrAgentWebControlService
from netconsole.services.online_mr.errors import OnlineMrSiteContextError, OnlineMrSiteContextErrorCode
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.online_mr.web_control_service import OnlineMrWebControlService


class OnlineMrApiFacade:
    """Online MR Web API 的当前局点与公开用例边界。"""

    def __init__(
        self,
        paths: PathResolver,
        query_service: OnlineMrQueryService,
        local_control: OnlineMrWebControlService,
        agent_control: OnlineMrAgentWebControlService,
    ) -> None:
        self.paths = paths
        self.query_service = query_service
        self.local_control = local_control
        self.agent_control = agent_control

    def current_site_id(self) -> str:
        try:
            payload = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise OnlineMrSiteContextError(
                OnlineMrSiteContextErrorCode.NOT_SELECTED,
                "主程序尚未选择局点",
                status_code=422,
            ) from exc
        except (OSError, UnicodeError) as exc:
            raise OnlineMrSiteContextError(
                OnlineMrSiteContextErrorCode.UNAVAILABLE,
                "当前局点上下文不可用",
                status_code=503,
            ) from exc
        except json.JSONDecodeError as exc:
            raise OnlineMrSiteContextError(
                OnlineMrSiteContextErrorCode.INVALID,
                "当前局点配置无效",
                status_code=422,
            ) from exc
        if not isinstance(payload, dict):
            raise OnlineMrSiteContextError(
                OnlineMrSiteContextErrorCode.INVALID,
                "当前局点配置无效",
                status_code=422,
            )
        if "current_site" not in payload or payload.get("current_site") in (None, ""):
            raise OnlineMrSiteContextError(
                OnlineMrSiteContextErrorCode.NOT_SELECTED,
                "主程序尚未选择局点",
                status_code=422,
            )
        value = payload.get("current_site")
        if not isinstance(value, str):
            raise OnlineMrSiteContextError(
                OnlineMrSiteContextErrorCode.INVALID,
                "当前局点配置无效",
                status_code=422,
            )
        try:
            site_id = SiteManager(self.paths).validate_site_name(value)
        except ValueError as exc:
            raise OnlineMrSiteContextError(
                OnlineMrSiteContextErrorCode.INVALID,
                "当前局点配置无效",
                status_code=422,
            ) from exc
        if not self.paths.site_dir(site_id).is_dir():
            raise OnlineMrSiteContextError(
                OnlineMrSiteContextErrorCode.NOT_FOUND,
                "当前局点不存在",
                status_code=404,
            )
        return site_id

    def current_session(self):
        return self.query_service.get_current_session(self.current_site_id())

    def recent_sessions(self, *, limit: int):
        return self.query_service.list_sessions(self.current_site_id(), limit=limit)

    def session_detail(self, session_id: str):
        return self.query_service.get_session(self.current_site_id(), session_id)

    def collectors(self, session_id: str):
        return self.query_service.list_collectors(self.current_site_id(), session_id)

    def preview(self, session_id: str):
        return self.query_service.get_realtime_preview(self.current_site_id(), session_id)

    def raw_tail(self, session_id: str, name: str, *, tail: int):
        return self.query_service.read_raw_tail(self.current_site_id(), session_id, name, tail=tail)

    def raw_summary(self, session_id: str):
        return self.query_service.get_raw_summary(self.current_site_id(), session_id)

    def local_status(self):
        return self.local_control.status(self.current_site_id())

    def local_operation(self, operation_id: str):
        return self.local_control.get_operation(operation_id)

    def start_local(self, payload: OnlineMrWebStartRequestDTO):
        site_id = self.current_site_id()
        return self.local_control.start(payload, current_site_id=site_id)

    def stop_local(self, operation_id: str):
        return self.local_control.stop(operation_id)

    def agent_capabilities(self):
        return self.agent_control.capabilities(self.current_site_id())

    def agent_profiles(self):
        return self.agent_control.profiles()

    def agent_readiness(self, profile_id: str):
        return self.agent_control.readiness(profile_id)

    def agent_status(self):
        return self.agent_control.status(self.current_site_id())

    def agent_operation(self, operation_id: str):
        return self.agent_control.get_operation(operation_id)

    def start_agent(self, payload: OnlineMrAgentWebStartRequestDTO):
        site_id = self.current_site_id()
        return self.agent_control.start(payload, current_site_id=site_id)

    def stop_agent(self, operation_id: str):
        return self.agent_control.stop(operation_id)


__all__ = ["OnlineMrApiFacade"]
