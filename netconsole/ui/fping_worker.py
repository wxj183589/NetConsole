from __future__ import annotations

import os
import signal
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
            self.session.write_fping_final_summary("Status: high frequency ping disabled")
            self.completed.emit("disabled")
            return
        if not self.config.target:
            self.session.write_fping_final_summary("Status: failed\nReason: ping target is empty")
            self.failed.emit("Ping target is empty")
            return
        try:
            self._start_process(self.tool_path)
            if self.process is not None:
                self.process.wait()
            self.parse_new_file_content()
            self.save_final_summary()
        except Exception as exc:
            self.session.write_fping_final_summary(f"Status: failed\nReason: {exc}")
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
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
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
            self.session.write_fping_final_summary("Status: stopped\nReason: fping process was not started")
            return
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                try:
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                    self.process.wait(timeout=2)
                except Exception:
                    pass
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.parse_new_file_content()
        self.save_final_summary()

    def parse_new_file_content(self) -> int:
        output = self.session.session_dir / "raw" / "Fping.txt"
        if not output.exists():
            return 0
        lines = self._read_output_text(output).splitlines()
        new_lines = lines[self._parsed_line_count :]
        self._parsed_line_count = len(lines)
        rows = parse_fping_lines(new_lines, self.session.meta.started_at, default_target=self.config.target)
        if rows:
            self.session.append_ping_samples(rows, self.config.packet_size, self.config.interval_ms, self.config.loss_threshold_ms)
        return len(rows)

    def save_final_summary(self) -> dict[str, object]:
        output = self.session.session_dir / "raw" / "Fping.txt"
        if not output.exists():
            self.session.write_fping_final_summary("Status: no data\nReason: Fping.txt was not found")
            return {}
        try:
            text = self._read_output_text(output)
        except PermissionError as exc:
            self.session.write_fping_final_summary(
                "Status: fping file is still locked\n"
                f"Target: {self.config.target}\n"
                f"Reason: {exc}\n"
                "Suggestion: stop collection and retry parsing"
            )
            return {}
        summary = parse_fping_summary(text, self.config.target)
        if len(summary) <= 1:
            rows = parse_fping_lines(text.splitlines(), self.session.meta.started_at, default_target=self.config.target)
            if rows:
                sent = len(rows)
                received = sum(1 for row in rows if row.get("success"))
                latencies = [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]
                summary = {
                    "target_ip": self.config.target,
                    "sent": sent,
                    "received": received,
                    "lost": sent - received,
                    "loss_percent": ((sent - received) / sent * 100.0) if sent else 0.0,
                    "min_latency_ms": min(latencies) if latencies else None,
                    "max_latency_ms": max(latencies) if latencies else None,
                    "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
                }
        if len(summary) > 1:
            self.session.append_ping_summary(summary)
        self.session.write_fping_final_summary(self._format_summary(summary, text))
        return summary

    def _read_output_text(self, output: Path) -> str:
        return output.read_text(encoding="utf-8", errors="replace")

    def _format_summary(self, summary: dict[str, object], raw_text: str) -> str:
        if len(summary) <= 1:
            return (
                "Status: no data\n"
                f"Target: {self.config.target}\n"
                "Sent: 0\nReceived: 0\nLost: 0\n"
                "Loss: 0.00%\n"
                "Reason: no parseable fping samples"
            )
        sent = int(summary.get("sent") or 0)
        received = int(summary.get("received") or 0)
        lost = int(summary.get("lost") or max(0, sent - received))
        loss = float(summary.get("loss_percent") or ((lost / sent * 100.0) if sent else 0.0))
        return "\n".join(
            [
                "Status: normal" if sent else "Status: no data",
                f"Target: {summary.get('target_ip') or self.config.target}",
                f"Sent: {sent}",
                f"Received: {received}",
                f"Lost: {lost}",
                f"Loss: {loss:.2f}%",
                f"Average latency: {_summary_float(summary.get('avg_latency_ms'))} ms",
                f"Maximum latency: {_summary_float(summary.get('max_latency_ms'))} ms",
                f"Minimum latency: {_summary_float(summary.get('min_latency_ms'))} ms",
                f"Raw bytes: {len(raw_text.encode('utf-8', errors='replace'))}",
            ]
        )


def _summary_float(value: object) -> str:
    return "-" if value is None else f"{float(value):.2f}"
