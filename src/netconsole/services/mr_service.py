from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.mr_collect.engine import MRCollectEngine, MRCollectTask
from netconsole.core.mr_collect.session import MRSession


@dataclass
class MRService:
    engine: MRCollectEngine

    def start(self, task: MRCollectTask) -> MRSession:
        return self.engine.start_session(task)

    def stop(self, session_id: str) -> None:
        self.engine.stop_session(session_id)

    def get_session(self, session_id: str) -> MRSession | None:
        return self.engine.sessions.get(session_id)
