from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_tasks import BackgroundTaskCancelled, run_background_task


def _emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _should_cancel(job: BackgroundJob) -> bool:
    return bool(job.cancel_path and Path(job.cancel_path).exists())


def run_job(job: BackgroundJob) -> int:
    try:
        result = run_background_task(
            job,
            progress_callback=lambda stage, current, total, message: _emit(
                {
                    "type": "progress",
                    "job_id": job.job_id,
                    "stage": stage,
                    "current": current,
                    "total": total,
                    "message": message,
                }
            ),
            should_cancel=lambda: _should_cancel(job),
        )
        _emit({"type": "finished", "job_id": job.job_id, "result": result, "message": "后台任务完成"})
        return 0
    except BackgroundTaskCancelled as exc:
        _emit({"type": "error", "job_id": job.job_id, "message": str(exc), "cancelled": True})
        return 2
    except Exception as exc:
        stack = traceback.format_exc()
        _emit({"type": "error", "job_id": job.job_id, "message": str(exc) or exc.__class__.__name__, "traceback": stack, "cancelled": False})
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NetConsole background worker")
    parser.add_argument("--job", required=True, help="后台任务 JSON 文件")
    args = parser.parse_args(argv)
    with Path(args.job).open("r", encoding="utf-8") as handle:
        job = BackgroundJob.from_dict(json.load(handle))
    return run_job(job)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
