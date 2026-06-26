from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from netconsole.core.mr_collect.ssh_client import SSHClient

MRSessionStatus = Literal["running", "stopped", "failed"]


@dataclass
class MRSession:
    session_id: str
    mr_id: str
    ssh: SSHClient | None = None
    start_time: datetime = field(default_factory=datetime.now)
    status: MRSessionStatus = "running"
    session_dir: Path | None = None
    mesh_buffer: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=3000))
    busy_buffer: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=3000))
    stats_buffer: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=3000))
    fping_buffer: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=3000))

    @property
    def running(self) -> bool:
        return self.status == "running"

    def stop(self) -> None:
        self.status = "stopped"

    def fail(self) -> None:
        self.status = "failed"
