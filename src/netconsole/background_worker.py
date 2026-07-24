from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Mapping
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_events import log_event, progress_event
from netconsole.services.job_center.job_runner import run_job as run_center_job
from netconsole.services.job_center.worker_protocol import configure_standard_streams, write_event
from netconsole.services.job_center.sensitive_bootstrap import (
    SensitiveBootstrap,
    SensitiveBootstrapError,
    read_sensitive_bootstrap,
)


def _emit(event: dict[str, Any]) -> None:
    write_event(event)


def _should_cancel(job: BackgroundJob) -> bool:
    return bool(job.cancel_path and Path(job.cancel_path).exists())


def run_job(job: BackgroundJob, sensitive_bootstrap: SensitiveBootstrap | None = None) -> int:
    diagnostics = sys.stderr or getattr(sys, "__stderr__", None) or io.StringIO()

    def emit_progress(stage: str, current: int, total: int, message: object) -> None:
        details = dict(message) if isinstance(message, Mapping) else {}
        message_text = str(details.pop("message", "") if details else message or "")
        _emit(progress_event(job.job_id, stage, current, total, message_text, details=details))
        if bool(job.params.get("_emit_log_events")) and message_text:
            _emit(log_event(job.job_id, message_text, stage=stage))

    with redirect_stdout(diagnostics):
        result = run_center_job(
            job,
            progress_callback=emit_progress,
            should_cancel=lambda: _should_cancel(job),
            sensitive_bootstrap=sensitive_bootstrap,
        )
    _emit(result.to_event())
    if result.ok:
        return 0
    if result.cancelled:
        return 2
    return 1


def main(argv: list[str] | None = None) -> int:
    configure_standard_streams()
    parser = argparse.ArgumentParser(description="NetConsole background worker")
    parser.add_argument("--job", required=True, help="后台任务 JSON 文件")
    args = parser.parse_args(argv)
    with Path(args.job).open("r", encoding="utf-8") as handle:
        job = BackgroundJob.from_dict(json.load(handle))
    bootstrap = None
    if bool(job.params.get("_requires_sensitive_bootstrap")):
        try:
            bootstrap = read_sensitive_bootstrap(sys.stdin.buffer)
        except SensitiveBootstrapError as exc:
            _emit({"type": "error", "job_id": job.job_id, "error": str(exc), "message": str(exc)})
            return 1
    return run_job(job, bootstrap)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
