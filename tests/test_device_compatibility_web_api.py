from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode


ROOT = Path(__file__).resolve().parents[1]


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def test_device_compatibility_summary_reads_code_baseline_without_tasks(tmp_path: Path) -> None:
    paths = PathResolver(ROOT, tmp_path / "data-root")
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )

    with TestClient(app) as client:
        response = client.get("/api/device-compatibility/summary")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "Comware V7" in payload["platforms"]
    assert "Comware V9" in payload["platforms"]
    assert "交换机" in payload["roles"]
    assert "无线控制器" in payload["roles"]
    assert "车载 MR（Cloud AP）" in payload["roles"]
    assert "本地扫描候选不会显示到普通用户首页" in payload["disclaimer"]
    assert "password" not in response.text.lower()
    assert "token" not in response.text.lower()
