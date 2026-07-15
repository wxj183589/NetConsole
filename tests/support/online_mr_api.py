from __future__ import annotations

from netconsole.services.online_mr.api_facade import OnlineMrApiFacade


def wire_online_mr_api_facade(app, paths):
    app.state.online_mr_api_facade = OnlineMrApiFacade(
        paths,
        app.state.online_mr_query_service,
        app.state.online_mr_web_control_service,
        app.state.online_mr_agent_web_control_service,
    )
    return app
