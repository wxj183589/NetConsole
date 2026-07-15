from __future__ import annotations

import asyncio
import html
import secrets
import socket
import threading

import uvicorn

from netconsole.backend.api.main import create_app
from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode


def available_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def run_server(server: uvicorn.Server) -> None:
    async def serve() -> None:
        loop = asyncio.get_running_loop()

        def handle_exception(current_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
            error = context.get("exception")
            if isinstance(error, ConnectionResetError) and getattr(error, "winerror", None) == 10054:
                return
            current_loop.default_exception_handler(context)

        loop.set_exception_handler(handle_exception)
        await server.serve()

    asyncio.run(serve())


def stop_server(server: uvicorn.Server, server_thread: threading.Thread) -> None:
    server.should_exit = True
    server_thread.join(timeout=5)
    if server_thread.is_alive():
        server.force_exit = True
        server_thread.join(timeout=2)


class DesktopWebServer:
    def __init__(self, *, paths: PathResolver, protect_session: bool = True) -> None:
        self.paths = paths
        self.port = available_local_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.session_token = secrets.token_urlsafe(32) if protect_session else ""
        app = create_app(
            RuntimeMode.DESKTOP,
            paths=paths,
            desktop_session_token=self.session_token or None,
        )
        app_logger.log_info(
            "DESKTOP_WEB_FRONTEND_RESOURCE",
            (
                f"frontend_root={app.state.frontend_root} "
                f"index={app.state.frontend_root / 'index.html'} "
                f"frontend_build_id={app.state.frontend_build_id or 'missing'} "
                f"backend_build_id={app.state.backend_build_id} "
                f"frontend_source_type={app.state.frontend_source_type}"
            ),
        )
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", access_log=False)
        )
        self.thread = threading.Thread(
            target=run_server,
            args=(self.server,),
            name="netconsole-web-api",
            daemon=True,
        )

    @property
    def started(self) -> bool:
        return bool(self.server.started)

    @property
    def thread_alive(self) -> bool:
        return self.thread.is_alive()

    def start(self) -> None:
        if not self.thread.is_alive() and not self.server.started:
            self.thread.start()

    def stop(self) -> None:
        if self.thread.is_alive():
            stop_server(self.server, self.thread)

    def bootstrap_html(self) -> str:
        if not self.session_token:
            return f'<meta http-equiv="refresh" content="0;url={html.escape(self.base_url, quote=True)}">'
        action = html.escape(f"{self.base_url}/__desktop_session", quote=True)
        token = html.escape(self.session_token, quote=True)
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>NetConsole Web</title></head><body>
<form id="desktop-session" method="post" action="{action}">
<input type="hidden" name="token" value="{token}"></form>
<script>document.getElementById('desktop-session').submit()</script>
</body></html>"""
