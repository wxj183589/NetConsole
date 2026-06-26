from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.models.online_mr_models import FpingConfig
from netconsole.services.fping_v3 import build_fping_args, parse_fping_lines, parse_fping_summary
from netconsole.services.online_mr_session_store import OnlineMrSession


class FpingProbeWorker(QThread):
    snapshot = Signal(object)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, session: OnlineMrSession, config: FpingConfig, tool_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.config = config.normalized()
        self.tool_path = tool_path
        self.process: subprocess.Popen | None = None
        self.stop_requested = False
        self._parsed_line_count = 0

    def run(self) -> None:
        if not self.config.enabled:
            self.completed.emit("disabled")
            return
        if not self.config.target:
            self.failed.emit("Ping target is empty")
            return
        try:
            self._start_process(self.tool_path)
            if self.process is not None:
                self.process.wait()
            self.parse_new_file_content()
            self.save_final_summary()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit("STOPPED" if self.stop_requested else "DONE")

    def _start_process(self, tool_path: Path) -> None:
        output = self.session.session_dir / "raw" / "Fping.txt"
        args = build_fping_args(
            tool_path,
            self.config.target,
            self.config.packet_size,
            self.config.interval_ms,
            self.config.loss_threshold_ms,
            output,
            continuous=self.config.continuous,
            write_file=self.config.write_file,
        )
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            creationflags=creationflags,
            cwd=tool_path.parent,
        )

    def stop(self) -> None:
        self.stop_requested = True
        if self.process is None:
            return
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)

    def parse_new_file_content(self) -> int:
        output = self.session.session_dir / "raw" / "Fping.txt"
        if not output.exists():
            return 0
        lines = output.read_text(encoding="utf-8", errors="replace").splitlines()
        new_lines = lines[self._parsed_line_count :]
        self._parsed_line_count = len(lines)
        rows = parse_fping_lines(new_lines, self.session.meta.started_at, default_target=self.config.target)
        if rows:
            self.session.append_ping_samples(rows, self.config.packet_size, self.config.interval_ms, self.config.loss_threshold_ms)
        return len(rows)

    def save_final_summary(self) -> dict[str, object]:
        output = self.session.session_dir / "raw" / "Fping.txt"
        if not output.exists():
            return {}
        text = output.read_text(encoding="utf-8", errors="replace")
        summary = parse_fping_summary(text, self.config.target)
        if len(summary) > 1:
            self.session.append_ping_summary(summary)
            (self.session.session_dir / "raw" / "Fping_final_summary.txt").write_text(text, encoding="utf-8")
        return summary
