from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from netconsole.models.online_mr_agent import (
    OnlineMrAgentConnectionConfig,
    OnlineMrAgentDownloadResult,
    OnlineMrAgentPackageInfo,
    OnlineMrAgentPingResponse,
    OnlineMrAgentSystemStatus,
    OnlineMrAgentTaskStatusResponse,
    OnlineMrAgentToolsStatus,
    OnlineMrAgentToolStatus,
)
from netconsole.services.agent.http_client import (
    AgentClientError,
    AgentHttpClient,
    normalize_agent_base_url,
)
from netconsole.services.online_mr.errors import OnlineMrApplicationErrorCode


_ModelT = TypeVar("_ModelT", bound=BaseModel)
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]+")
_PACKAGE_DOWNLOAD_PATH = re.compile(
    r"/api/v1/packages/([A-Za-z0-9_.-]+)/download"
)


class OnlineMrAgentClientError(RuntimeError):
    def __init__(
        self,
        code: OnlineMrApplicationErrorCode | str,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        self.code = str(code)
        self.message = str(message or "Online MR Agent 请求失败").strip()
        self.status_code = status_code
        super().__init__(self.message)


class OnlineMrAgentHttpClient(AgentHttpClient):
    """Online MR Agent 只读状态与采集包下载客户端；不负责远程启动。"""

    def __init__(
        self,
        config: OnlineMrAgentConnectionConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        super().__init__(
            connect_timeout=config.timeout_sec,
            read_timeout=config.timeout_sec,
            transport=transport,
            verify_tls=config.verify_tls,
            user_agent=config.user_agent,
        )

    async def ping(self) -> OnlineMrAgentPingResponse:
        payload = await self._json("/api/v1/ping")
        result = self._model(OnlineMrAgentPingResponse, payload)
        if result.status.casefold() != "ok":
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_STATUS_FAILED,
                "Agent ping 状态异常",
            )
        return result

    async def get_status(self) -> OnlineMrAgentSystemStatus:
        payload = await self._json("/api/v1/status")
        return self._model(OnlineMrAgentSystemStatus, payload)

    async def get_tools_status(self) -> OnlineMrAgentToolsStatus:
        payload = await self._json("/api/v1/tools/status")
        tools = payload.get("tools")
        if not isinstance(tools, dict):
            self._invalid_response("Agent 工具状态缺少 tools")
        values: dict[str, OnlineMrAgentToolStatus] = {}
        for name in ("mr_collector", "fping", "iperf3"):
            item = tools.get(name)
            if not isinstance(item, dict):
                self._invalid_response(f"Agent 工具状态缺少 {name}")
            values[name] = self._model(OnlineMrAgentToolStatus, item)
        return OnlineMrAgentToolsStatus(**values)

    async def get_task(self, task_id: str) -> OnlineMrAgentTaskStatusResponse:
        selected = self._safe_id(task_id, "task_id")
        payload = await self._json(
            f"/api/v1/tasks/{selected}",
            not_found=OnlineMrApplicationErrorCode.AGENT_TASK_NOT_FOUND,
        )
        result = self._model(OnlineMrAgentTaskStatusResponse, payload)
        if result.task_id != selected or result.task_type != "mr_realtime_collect":
            self._invalid_response("Agent 返回的 Online MR Task 身份不一致")
        return result

    async def list_packages(self) -> tuple[OnlineMrAgentPackageInfo, ...]:
        payload = await self._payload("/api/v1/packages")
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            self._invalid_response("Agent package 列表格式无效")
        packages = []
        for item in payload:
            package = self._model(OnlineMrAgentPackageInfo, item)
            if not package.package_id:
                match = _PACKAGE_DOWNLOAD_PATH.fullmatch(
                    package.package_download_url
                )
                if match:
                    package = package.model_copy(update={"package_id": match.group(1)})
            packages.append(package)
        return tuple(packages)

    async def download_package(
        self,
        package_id: str,
        destination_dir: str | Path,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> OnlineMrAgentDownloadResult:
        selected = self._safe_id(package_id, "package_id")
        destination = Path(destination_dir)
        stamp = time.time_ns()
        final_path = destination / f"agent_download_{selected}_{stamp}.zip"
        partial_path = final_path.with_suffix(".zip.part")
        token = self.config.token.get_secret_value() or None
        headers = self._headers(token)
        headers["Accept"] = "application/zip, application/octet-stream"
        size = 0
        digest = hashlib.sha256()
        content_type = ""
        try:
            destination.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                headers=headers,
                transport=self.transport,
                verify=self.verify_tls,
            ) as client:
                async with client.stream(
                    "GET",
                    f"{self._base_url()}/api/v1/packages/{selected}/download",
                ) as response:
                    self._check_download_response(response)
                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                    )
                    declared = response.headers.get("content-length")
                    if declared:
                        try:
                            declared_size = int(declared)
                        except ValueError:
                            self._invalid_response("Agent package Content-Length 无效")
                        if declared_size < 0:
                            self._invalid_response("Agent package Content-Length 无效")
                        if declared_size > self.config.max_download_bytes:
                            self._too_large()
                    with partial_path.open("xb") as output:
                        async for chunk in response.aiter_bytes(
                            self.config.download_chunk_size
                        ):
                            if cancel_check is not None and cancel_check():
                                raise OnlineMrAgentClientError(
                                    OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED,
                                    "Agent package 下载已取消",
                                )
                            size += len(chunk)
                            if size > self.config.max_download_bytes:
                                self._too_large()
                            output.write(chunk)
                            digest.update(chunk)
            os.replace(partial_path, final_path)
        except OnlineMrAgentClientError:
            raise
        except httpx.TimeoutException as exc:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_TIMEOUT,
                "下载 Agent package 超时",
            ) from exc
        except httpx.ConnectError as exc:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_UNREACHABLE,
                "无法连接 Agent",
            ) from exc
        except httpx.HTTPError as exc:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED,
                "Agent package 下载中断",
            ) from exc
        except OSError as exc:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED,
                "Agent package 临时文件写入失败",
            ) from exc
        finally:
            try:
                partial_path.unlink(missing_ok=True)
            except OSError:
                pass
        return OnlineMrAgentDownloadResult(
            package_id=selected,
            path=final_path,
            sha256=digest.hexdigest(),
            size=size,
            content_type=content_type,
        )

    async def _json(
        self,
        path: str,
        *,
        not_found: OnlineMrApplicationErrorCode | None = None,
    ) -> dict[str, Any]:
        payload = await self._payload(path, not_found=not_found)
        if not isinstance(payload, dict):
            self._invalid_response("Agent data 字段格式无效")
        return payload

    async def _payload(
        self,
        path: str,
        *,
        not_found: OnlineMrApplicationErrorCode | None = None,
    ) -> Any:
        try:
            return await self._call_payload(
                "GET",
                self.config.base_url,
                path,
                self.config.token.get_secret_value() or None,
            )
        except AgentClientError as exc:
            raise self._mapped_error(exc, not_found=not_found) from exc
        except ValueError as exc:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_RESPONSE_INVALID,
                "Agent 地址无效",
            ) from exc

    def _base_url(self) -> str:
        try:
            return normalize_agent_base_url(self.config.base_url)
        except ValueError as exc:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_RESPONSE_INVALID,
                "Agent 地址无效",
            ) from exc

    @classmethod
    def _model(cls, model: type[_ModelT], payload: dict[str, Any]) -> _ModelT:
        try:
            selected = {
                name: payload[name] for name in model.model_fields if name in payload
            }
            return model.model_validate(selected)
        except ValidationError as exc:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_RESPONSE_INVALID,
                "Agent 响应字段无效",
            ) from exc

    @staticmethod
    def _safe_id(value: str, label: str) -> str:
        selected = str(value or "").strip()
        if not _SAFE_ID.fullmatch(selected):
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_RESPONSE_INVALID,
                f"{label} 格式无效",
            )
        return selected

    @staticmethod
    def _invalid_response(message: str) -> None:
        raise OnlineMrAgentClientError(
            OnlineMrApplicationErrorCode.AGENT_RESPONSE_INVALID,
            message,
        )

    @staticmethod
    def _too_large() -> None:
        raise OnlineMrAgentClientError(
            OnlineMrApplicationErrorCode.AGENT_PACKAGE_TOO_LARGE,
            "Agent package 超过下载大小限制",
        )

    @staticmethod
    def _mapped_error(
        error: AgentClientError,
        *,
        not_found: OnlineMrApplicationErrorCode | None,
    ) -> OnlineMrAgentClientError:
        if error.status_code == 404 and not_found is not None:
            return OnlineMrAgentClientError(
                not_found, "Agent 资源不存在", status_code=404
            )
        mapping = {
            "AGENT_TIMEOUT": (
                OnlineMrApplicationErrorCode.AGENT_TIMEOUT,
                "连接 Agent 超时",
            ),
            "AGENT_CONNECTION_FAILED": (
                OnlineMrApplicationErrorCode.AGENT_UNREACHABLE,
                "无法连接 Agent",
            ),
            "AGENT_UNAUTHORIZED": (
                OnlineMrApplicationErrorCode.AGENT_AUTH_FAILED,
                "Agent 认证失败",
            ),
            "AGENT_VERSION_UNSUPPORTED": (
                OnlineMrApplicationErrorCode.AGENT_VERSION_UNSUPPORTED,
                "Agent 版本不受支持",
            ),
            "AGENT_MR_COLLECTOR_NOT_FOUND": (
                OnlineMrApplicationErrorCode.AGENT_MR_COLLECTOR_MISSING,
                "Agent MR 采集器不可用",
            ),
            "AGENT_TRAFFIC_TOOL_NOT_FOUND": (
                OnlineMrApplicationErrorCode.AGENT_TOOL_MISSING,
                "Agent 流量工具不可用",
            ),
            "AGENT_INVALID_JSON": (
                OnlineMrApplicationErrorCode.AGENT_RESPONSE_INVALID,
                "Agent 响应不是有效 JSON",
            ),
            "AGENT_RESPONSE_INCOMPATIBLE": (
                OnlineMrApplicationErrorCode.AGENT_RESPONSE_INVALID,
                "Agent 响应格式不兼容",
            ),
        }
        code, message = mapping.get(
            error.code,
            (
                OnlineMrApplicationErrorCode.AGENT_STATUS_FAILED,
                "Agent 状态请求失败",
            ),
        )
        return OnlineMrAgentClientError(code, message, status_code=error.status_code)

    @staticmethod
    def _check_download_response(response: httpx.Response) -> None:
        if 300 <= response.status_code < 400:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED,
                "Agent package 下载不允许重定向",
                status_code=response.status_code,
            )
        if response.status_code in {401, 403}:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_AUTH_FAILED,
                "Agent 认证失败",
                status_code=response.status_code,
            )
        if response.status_code == 404:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_PACKAGE_NOT_READY,
                "Agent package 尚未就绪",
                status_code=404,
            )
        if not response.is_success:
            raise OnlineMrAgentClientError(
                OnlineMrApplicationErrorCode.AGENT_PACKAGE_DOWNLOAD_FAILED,
                "Agent package 下载失败",
                status_code=response.status_code,
            )


__all__ = ["OnlineMrAgentClientError", "OnlineMrAgentHttpClient"]
