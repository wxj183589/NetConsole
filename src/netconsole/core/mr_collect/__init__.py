from __future__ import annotations

__all__ = ["MRCollectEngine", "MRCollectTask", "MRSession"]


def __getattr__(name: str):
    if name in {"MRCollectEngine", "MRCollectTask"}:
        from netconsole.core.mr_collect.engine import MRCollectEngine, MRCollectTask

        return {"MRCollectEngine": MRCollectEngine, "MRCollectTask": MRCollectTask}[name]
    if name == "MRSession":
        from netconsole.core.mr_collect.session import MRSession

        return MRSession
    raise AttributeError(name)
